"""Field-level Precision / Recall / F1 for the 15 pathology fields.

The evaluator treats each field as an exact-match value problem, with a
canonical ``[absent]`` class so unmentioned fields are scored rather than
silently skipped:

* gold absent + predicted absent -> true positive for the absent class;
* gold value + predicted absent -> false negative;
* gold absent + predicted value -> false positive;
* two different non-absent values -> one false positive and one false negative.

This is intentionally a **string-normalisation** metric.  It lowercases,
NFKC-normalises, collapses whitespace, normalises simple unit spacing
(``5.5 cm`` -> ``5.5cm``), fixes the common OCR form ``out 0f``, and strips
terminal punctuation.  It does not apply clinical synonym mappings; those must
be reviewed manually.  A field's ``flagged`` status is ignored for the value
metric, so a flagged but correct value still counts as correct.

Inputs
------
Each side may be a directory of per-case JSON files or one JSON file:

* ``{"fields": {...}}`` (Pass B / payload shape);
* ``{"reference_fields": {...}}`` (golden reference shape);
* ``{"extraction": {"fields": {...}}}`` (A-group ``AGroupResult``);
* a direct mapping with any of the 15 field keys.

Directories are matched by case id (JSON ``case_id``/``id``/``test_id`` or the
filename stem, with ``.expected``/``.pred``/``.gold`` suffixes removed).

Usage
-----
Mock data (default when no arguments are supplied)::

    python eval/run_f1.py

Real evaluation::

    python eval/run_f1.py --golden data/golden --predictions eval/predictions
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.pathology_schema import PATHOLOGY_FIELD_KEYS

ABSENT = "[absent]"


@dataclass(frozen=True)
class FieldScore:
    """Confusion counts and derived metrics for one pathology field."""

    tp: int
    fp: int
    fn: int

    @property
    def precision(self) -> float:
        """TP / (TP + FP), or 0 when nothing was predicted positive."""
        denominator = self.tp + self.fp
        return self.tp / denominator if denominator else 0.0

    @property
    def recall(self) -> float:
        """TP / (TP + FN), or 0 when gold has no positive instance."""
        denominator = self.tp + self.fn
        return self.tp / denominator if denominator else 0.0

    @property
    def f1(self) -> float:
        """Harmonic mean of precision and recall."""
        precision = self.precision
        recall = self.recall
        denominator = precision + recall
        return 2 * precision * recall / denominator if denominator else 0.0


def _canonical(value: Any) -> str:
    """Normalise one field value to a comparable string.

    ``None``, empty text, and the display sentinel ``[not mentioned]`` become
    :data:`ABSENT`.  A literal clinical value ``"absent"`` is **not** mapped to
    the absent class; it is a valid finding (for example perforation absent).
    """
    if value is None:
        return ABSENT
    if not isinstance(value, str):
        value = str(value)

    text = unicodedata.normalize("NFKC", value).strip()
    if not text:
        return ABSENT

    folded = text.casefold()
    folded = folded.strip(" .,;:")
    if folded in {"[not mentioned]", "not mentioned"}:
        return ABSENT

    folded = re.sub(r"\s+", " ", folded)
    folded = folded.replace("out 0f", "out of")
    folded = re.sub(r"(?<=\d)\s+(?=(?:cm|mm)\b)", "", folded)
    folded = re.sub(r"\s*([,;:])\s*", r"\1 ", folded)
    folded = folded.strip(" .,;:")
    return folded or ABSENT


def _field_value(entry: Any) -> str:
    """Extract and canonicalise one field entry."""
    if isinstance(entry, dict):
        raw_value = entry.get("value")
        status = entry.get("status")
        if raw_value is None and status in {"absent", "not_mentioned"}:
            return ABSENT
        return _canonical(raw_value)
    return _canonical(entry)


def _fields_from_item(item: dict[str, Any], source: Path) -> dict[str, Any]:
    """Find the 15-field mapping inside one gold or prediction object."""
    extraction = item.get("extraction")
    if isinstance(extraction, dict) and isinstance(extraction.get("fields"), dict):
        return extraction["fields"]

    for key in ("fields", "reference_fields"):
        candidate = item.get(key)
        if isinstance(candidate, dict):
            return candidate

    if any(key in item for key in PATHOLOGY_FIELD_KEYS):
        return item

    raise ValueError(
        f"{source}: object has no 'fields', 'reference_fields', "
        "'extraction.fields', or direct 15-field mapping"
    )


def _case_id(
    item: dict[str, Any],
    source: Path,
    index: int | None = None,
) -> str:
    """Resolve a stable case id from JSON metadata or the filename stem."""
    for key in ("case_id", "id", "test_id"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    stem = source.stem
    for suffix in (
        ".expected",
        ".prediction",
        ".pred",
        ".actual",
        ".result",
        ".extraction",
        ".gold",
        ".input",
    ):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break

    if index is not None:
        # A multi-case single file has no per-file stem to match on; use order.
        return f"case-{index}"
    return stem


def _canonical_fields(
    raw_fields: dict[str, Any],
    source: Path,
    case_id: str,
) -> dict[str, str]:
    """Return all 15 canonical values, treating missing keys as absent."""
    if not isinstance(raw_fields, dict):
        raise TypeError(f"{source} ({case_id}): fields must be a JSON object")

    values: dict[str, str] = {}
    for field_key in PATHOLOGY_FIELD_KEYS:
        if field_key in raw_fields:
            values[field_key] = _field_value(raw_fields[field_key])
        else:
            values[field_key] = ABSENT
    return values


def _load_json(path: Path) -> Any:
    """Load JSON with a clear path-specific error."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"File not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed JSON in {path}: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"Cannot read {path}: {exc}") from exc


def load_cases(path: Path, label: str) -> dict[str, dict[str, str]]:
    """Load gold or prediction cases from a directory or a single JSON file."""
    if not path.exists():
        raise ValueError(f"{label} path does not exist: {path}")

    cases: dict[str, dict[str, str]] = {}

    if path.is_dir():
        files = sorted(file for file in path.glob("*.json") if file.is_file())
        if not files:
            raise ValueError(f"{label} directory contains no JSON files: {path}")

        for file in files:
            data = _load_json(file)
            if not isinstance(data, dict):
                raise TypeError(f"{file}: top-level JSON must be an object")
            case_id = _case_id(data, file)
            if case_id in cases:
                raise ValueError(f"Duplicate case id {case_id!r} in {path}")
            raw_fields = _fields_from_item(data, file)
            cases[case_id] = _canonical_fields(raw_fields, file, case_id)

        return cases

    data = _load_json(path)
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict) and isinstance(data.get("cases"), list):
        items = data["cases"]
    elif isinstance(data, dict):
        items = [data]
    else:
        raise TypeError(f"{path}: top-level JSON must be an object or a list")

    if not items:
        raise ValueError(f"{path}: no cases found")

    single = len(items) == 1
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise TypeError(f"{path}: case {index} is not a JSON object")
        case_id = _case_id(item, path, None if single else index)
        if case_id in cases:
            raise ValueError(f"Duplicate case id {case_id!r} in {path}")
        raw_fields = _fields_from_item(item, path)
        cases[case_id] = _canonical_fields(raw_fields, path, case_id)

    return cases


def compute_scores(
    gold_cases: dict[str, dict[str, str]],
    predicted_cases: dict[str, dict[str, str]],
) -> dict[str, FieldScore]:
    """Compute per-field confusion counts and metrics."""
    if not gold_cases:
        raise ValueError("No gold cases to evaluate")

    gold_ids = set(gold_cases)
    predicted_ids = set(predicted_cases)
    missing = sorted(gold_ids - predicted_ids)
    extra = sorted(predicted_ids - gold_ids)
    if missing or extra:
        raise ValueError(
            "Gold/prediction case mismatch: "
            f"missing={missing or 'none'} extra={extra or 'none'}"
        )

    scores: dict[str, FieldScore] = {}
    for field_key in PATHOLOGY_FIELD_KEYS:
        tp = fp = fn = 0

        for case_id in gold_ids:
            gold_value = gold_cases[case_id][field_key]
            predicted_value = predicted_cases[case_id][field_key]

            if gold_value == predicted_value:
                tp += 1
                continue

            if predicted_value != ABSENT:
                fp += 1
            if gold_value != ABSENT:
                fn += 1

        scores[field_key] = FieldScore(tp=tp, fp=fp, fn=fn)

    return scores


def macro_f1(scores: dict[str, FieldScore]) -> float:
    """Unweighted mean of the 15 field F1 values."""
    if not scores:
        raise ValueError("No field scores to average")
    return sum(score.f1 for score in scores.values()) / len(scores)


def print_scores(
    scores: dict[str, FieldScore],
    case_count: int,
) -> None:
    """Print per-field TP/FP/FN, precision, recall, and F1 plus macro-F1."""
    print(f"Cases: {case_count}")
    print(
        f"{'Field':<48}{'TP':>5}{'FP':>5}{'FN':>5}"
        f"{'Precision':>11}{'Recall':>9}{'F1':>9}"
    )
    print("-" * 96)

    for field_key in PATHOLOGY_FIELD_KEYS:
        score = scores[field_key]
        print(
            f"{field_key:<48}"
            f"{score.tp:>5}{score.fp:>5}{score.fn:>5}"
            f"{score.precision:>11.4f}{score.recall:>9.4f}{score.f1:>9.4f}"
        )

    print("-" * 96)
    print(f"Macro-F1: {macro_f1(scores):.4f}")


def evaluate(
    golden_path: Path,
    prediction_path: Path,
) -> dict[str, FieldScore]:
    """Load both sides, compute metrics, and print the field table."""
    gold_cases = load_cases(golden_path, "golden")
    predicted_cases = load_cases(prediction_path, "predictions")
    scores = compute_scores(gold_cases, predicted_cases)
    print_scores(scores, len(gold_cases))
    return scores


def _mock_fields(**values: str | None) -> dict[str, str | None]:
    """Build a complete 15-field mapping for the mock evaluation."""
    fields: dict[str, str | None] = {key: None for key in PATHOLOGY_FIELD_KEYS}
    fields.update(values)
    return fields


def run_mock() -> dict[str, FieldScore]:
    """Run an offline two-case mock that exercises absent and mismatch logic."""
    gold = {
        "CASE-MOCK-1": _mock_fields(
            tumour_site="right colon",
            tumour_perforation="absent",
            lymph_node_status="no metastasis, 0 out of 22",
        ),
        "CASE-MOCK-2": _mock_fields(
            tumour_site="sigmoid colon",
            histological_tumour_type="adenocarcinoma",
            circumferential_margin="negative",
            tumour_perforation="absent",
        ),
    }
    predicted = {
        "CASE-MOCK-1": _mock_fields(
            tumour_site="right colon",
            tumour_perforation="absent",
        ),
        "CASE-MOCK-2": _mock_fields(
            tumour_site="rectum",
            histological_tumour_type="adenosquamous carcinoma",
            circumferential_margin="negative",
            tumour_perforation="absent",
        ),
    }

    print("=== Mock data: gold vs predicted ===")
    scores = compute_scores(gold, predicted)
    print_scores(scores, len(gold))

    assert len(scores) == len(PATHOLOGY_FIELD_KEYS)
    macro = macro_f1(scores)
    assert 0.0 <= macro <= 1.0
    assert scores["tumour_perforation"].f1 == 1.0
    # One case has a gold value (FN) and one is correctly absent (TP).
    assert scores["lymph_node_status"].f1 == 0.5
    return scores


def main() -> None:
    """CLI entry point; no arguments runs the mock evaluation."""
    parser = argparse.ArgumentParser(
        description="Compute 15-field P/R/F1 for ColoStruct outputs."
    )
    parser.add_argument(
        "--golden",
        type=Path,
        default=None,
        help="Golden JSON file or directory.",
    )
    parser.add_argument(
        "--predictions",
        type=Path,
        default=None,
        help="Model-output JSON file or directory.",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Run the built-in mock evaluation instead of files.",
    )
    args = parser.parse_args()

    if args.mock or (args.golden is None and args.predictions is None):
        run_mock()
        return

    if args.golden is None or args.predictions is None:
        parser.error("--golden and --predictions must be supplied together")

    try:
        evaluate(args.golden, args.predictions)
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"run_f1: {exc}") from exc


if __name__ == "__main__":
    main()
