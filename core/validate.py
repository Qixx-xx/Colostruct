"""Hallucination audit and rule engine for ColoStruct extraction results.

The LLM returns a :class:`~core.pathology_schema.ColoStructExtraction` whose
evidence contains only ``segment_id`` and ``quote``.  This module turns that
untrusted draft into an audited one:

1. **Evidence back-reference.** For every field with evidence, locate the
   referenced ASR segment, verify that the quote really occurs in that segment,
   and copy the segment's global ``start``/``end`` onto the evidence.  Quote
   matching ignores punctuation, whitespace, case, and full-width/half-width
   differences, and tolerates small typos via ``difflib.SequenceMatcher``.
   Numbers are treated strictly: a quote containing ``3.5`` will not match a
   segment containing ``35`` or ``4.5``.
2. **Temporal override audit.** Replay each ``OverrideLog`` and require the new
   evidence's segment to start strictly later than the old evidence's segment.
   A same-segment or earlier-segment override is flagged.
3. **Value integrity.** A quote must support the extracted value, not merely
   exist in the transcript.  Numbers in ``value`` must match the quote's
   numbers, including English number words (``five point five`` = ``5.5``);
   positive/negative polarity must agree; and core entity tokens such as
   ``colon`` in ``right colon`` must be present in the quote.
4. **LLM timestamp rejection.** The LLM must not return ``start``/``end``.
   Evidence whose timestamps do not match the referenced segment is flagged.
5. **Unreferenced conflict scan.** If another transcript segment explicitly
   mentions the field but was not cited, and its statement conflicts with the
   selected value, the field is flagged for review.
6. **Final state and export block.** A value with fully verified evidence is
   ``POPULATED``; a value with missing, unsupported, or failed evidence is
   ``FLAGGED``; an empty value is ``ABSENT`` unless its own evidence failed
   verification.  Export is blocked when no value-bearing field has at least
   one fully verified evidence span.

The audit is deliberately fail-closed.  A missing segment, missing timestamp,
bad quote, or unresolved override is logged and reflected in the field state;
none of those data problems raises.  Only a caller passing the wrong top-level
type gets a ``TypeError``.  The input object is mutated in place and returned
so the pipeline can chain ``extract -> audit -> review`` without an extra copy.
"""

from __future__ import annotations

import logging
import math
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Final

if __package__:
    from .pathology_schema import (
        ColoStructExtraction,
        Evidence,
        FieldModel,
        OverrideLog,
        StatusEnum,
    )
else:  # pragma: no cover - exercised when running ``python core/validate.py``
    from pathology_schema import (
        ColoStructExtraction,
        Evidence,
        FieldModel,
        OverrideLog,
        StatusEnum,
    )

__all__ = [
    "EVIDENCE_LLM_TIMESTAMP_MSG",
    "EVIDENCE_MISMATCH_MSG",
    "EVIDENCE_MISSING_MSG",
    "EVIDENCE_SEGMENT_MISSING_MSG",
    "EVIDENCE_TIMESTAMP_MSG",
    "EVIDENCE_TIMESTAMP_ORDER_MSG",
    "OVERRIDE_EVIDENCE_MSG",
    "OVERRIDE_ORDER_MSG",
    "UNREFERENCED_CONFLICT_MSG",
    "VALUE_NUMBER_MSG",
    "VALUE_POLARITY_MSG",
    "VALUE_SUPPORT_MSG",
    "audit_extraction",
]

logger = logging.getLogger(__name__)


#: Required message when a segment exists but the quote is not found in it.
EVIDENCE_MISMATCH_MSG: Final[str] = "证据匹配失败：原文片段中未找到该引用"

#: Message when the LLM references a segment id absent from the transcript.
EVIDENCE_SEGMENT_MISSING_MSG: Final[str] = "证据匹配失败：转写文本中不存在该 segment_id"

#: Message when the segment exists but its timestamps are missing or invalid.
EVIDENCE_TIMESTAMP_MSG: Final[str] = "证据匹配失败：片段时间戳无效"

#: Message when a segment has an end time earlier than its start time.
EVIDENCE_TIMESTAMP_ORDER_MSG: Final[str] = "证据匹配失败：片段时间戳顺序异常"

#: Message when a field has a value but no evidence at all.
EVIDENCE_MISSING_MSG: Final[str] = "证据缺失：字段有值但未提供任何证据"

#: Required message when an override moves to an earlier or identical segment.
OVERRIDE_ORDER_MSG: Final[str] = "时序异常：覆盖动作的时间顺序错误"

#: Message when override evidence itself cannot be located or verified.
OVERRIDE_EVIDENCE_MSG: Final[str] = "时序异常：覆盖动作的证据无法定位"

#: Message when the LLM supplies start/end timestamps itself.
EVIDENCE_LLM_TIMESTAMP_MSG: Final[str] = "证据匹配失败：LLM 不应生成 start/end 时间戳"

#: Message when field.value and the quote disagree on a number.
VALUE_NUMBER_MSG: Final[str] = "值校验失败：值中的数字与引用不一致"

#: Message when field.value and the quote have opposite polarity.
VALUE_POLARITY_MSG: Final[str] = "值校验失败：值与引用的否定/肯定极性相反"

#: Message when the quote does not support a core token in field.value.
VALUE_SUPPORT_MSG: Final[str] = "值校验失败：引用未支持值中的核心词"

#: Message when an unreferenced transcript segment mentions the field.
UNREFERENCED_CONFLICT_MSG: Final[str] = (
    "未引用冲突：转写文本中存在与字段相关但未引用的陈述"
)

#: Messages written by this audit.  A re-audit removes only these, preserving
#: messages contributed by other back-end rules.
_AUDIT_OWNED_MESSAGES: Final[frozenset[str]] = frozenset(
    {
        EVIDENCE_LLM_TIMESTAMP_MSG,
        EVIDENCE_MISMATCH_MSG,
        EVIDENCE_MISSING_MSG,
        EVIDENCE_SEGMENT_MISSING_MSG,
        EVIDENCE_TIMESTAMP_MSG,
        EVIDENCE_TIMESTAMP_ORDER_MSG,
        OVERRIDE_EVIDENCE_MSG,
        OVERRIDE_ORDER_MSG,
        UNREFERENCED_CONFLICT_MSG,
        VALUE_NUMBER_MSG,
        VALUE_POLARITY_MSG,
        VALUE_SUPPORT_MSG,
    }
)


#: Fuzzy matching is only attempted for quotes at least this long after
#: normalisation.  Short quotes must match exactly, which prevents a two- or
#: three-character fragment from matching half the transcript by accident.
MIN_FUZZY_QUOTE_LENGTH: Final[int] = 4

#: Minimum SequenceMatcher similarity for a fuzzy quote match.
FUZZY_MATCH_THRESHOLD: Final[float] = 0.85

#: Punctuation and whitespace are ignored for quote matching.  Chinese
#: characters remain because Python's Unicode ``\w`` includes them.
_NON_WORD_RE: Final[re.Pattern[str]] = re.compile(r"[\W_]+", re.UNICODE)

#: Pure-ASCII alphanumeric quote.  One- and two-character ASCII fragments are
#: too weak to be evidence (``is`` would otherwise match inside ``this``).
_ASCII_ALNUM_RE: Final[re.Pattern[str]] = re.compile(r"[a-z0-9]+")

#: English number words used by clinical dictation (``five point five``).
_NUMBER_WORD_VALUES: Final[dict[str, int]] = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
    "hundred": 100,
    "thousand": 1000,
}

#: Tokeniser for numbers: Arabic numerals and English words.
_NUMBER_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"\d+(?:\.\d+)?|[a-zA-Z]+")

#: Word tokeniser used by the value-support checks.
_WORD_RE: Final[re.Pattern[str]] = re.compile(r"[a-z]+")

#: Words that carry no entity signal on their own.  Polarity words are handled
#: by :func:`_polarity`; units and numbers are handled separately.
_SEMANTIC_STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        "a",
        "an",
        "the",
        "to",
        "of",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "and",
        "or",
        "with",
        "in",
        "at",
        "for",
        "on",
        "by",
        "from",
        "as",
        "that",
        "this",
        "no",
        "not",
        "without",
        "free",
        "present",
        "absent",
        "positive",
        "negative",
        "identified",
        "involved",
        "invasion",
        "metastasis",
        "metastases",
        "cm",
        "mm",
        "centimetre",
        "centimetres",
        "centimeter",
        "centimeters",
        "millimetre",
        "millimetres",
        "millimeter",
        "millimeters",
        "out",
        "tumour",
        "tumor",
    }
)

#: Positive clinical polarity markers.
_POSITIVE_MARKERS: Final[tuple[str, ...]] = (
    "present",
    "positive",
    "metastasis",
    "metastases",
    "metastatic",
    "invasive",
    "invasion",
    "involved",
    "identified",
)

#: Negative clinical polarity markers.
_NEGATIVE_MARKERS: Final[tuple[str, ...]] = (
    "absent",
    "negative",
    "no ",
    "not ",
    "without",
    "free of",
    "not identified",
    "no evidence",
    "0 out of",
)

#: Field-specific cue phrases for finding an *unreferenced* statement about
#: the same field.  The cues are normalised (no spaces/punctuation) and are
#: deliberately specific to avoid flagging unrelated sentences.
_FIELD_CONFLICT_CUES: Final[dict[str, tuple[str, ...]]] = {
    "tumour_site": ("tumoursite", "tumorsite", "tumourisat", "tumorisat"),
    "operative_procedure": ("operativeprocedure", "operation"),
    "tumour_dimension": (
        "tumourdimension",
        "tumordimension",
        "sizeoftumour",
        "sizeoftumor",
    ),
    "tumour_perforation": ("perforation",),
    "relation_to_anterior_peritoneal_reflection": (
        "anteriorperitonealreflection",
        "peritonealreflection",
    ),
    "plane_of_mesorectal_excision": (
        "mesorectalexcision",
        "planeofmesorectal",
    ),
    "histological_tumour_type": (
        "histologicaltumourtype",
        "histologicaltumortype",
        "histology",
    ),
    "histological_tumour_grade": (
        "histologicaltumourgrade",
        "tumourgrade",
        "tumorgrade",
    ),
    "extent_of_invasion": (
        "extentofinvasion",
        "invasiontopericolic",
        "invasiontosubserosa",
    ),
    "lymphatic_and_venous_invasion": (
        "lymphaticandvenousinvasion",
        "lymphovascularinvasion",
        "venousinvasion",
        "lymphaticinvasion",
    ),
    "perineural_invasion": ("perineuralinvasion", "perineural"),
    "lymph_node_status": ("lymphnodestatus", "lymphnode", "lymphnodes"),
    "tumour_deposits": ("tumourdeposits", "tumordeposits", "deposits"),
    "proximal_and_distal_margins": (
        "proximalanddistalmargins",
        "proximalmargin",
        "distalmargin",
        "proximal",
        "distal",
    ),
    "circumferential_margin": (
        "circumferentialmargin",
        "circumferential",
        "crm",
    ),
}


def _to_seconds(value: Any) -> float | None:
    """Convert a clean-segment timestamp to a finite, non-negative float.

    Args:
        value: Raw ``start`` or ``end`` value from a clean segment.

    Returns:
        The timestamp in seconds, or ``None`` when the value is a boolean,
        non-numeric, non-finite, or negative.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        seconds = float(value)
    elif isinstance(value, str):
        try:
            seconds = float(unicodedata.normalize("NFKC", value).strip())
        except ValueError:
            return None
    else:
        return None

    if not math.isfinite(seconds) or seconds < 0:
        return None
    return seconds


def _normalise_for_match(text: str) -> str:
    """Return a punctuation-free, case-folded comparison form of ``text``.

    NFKC normalisation handles full-width Latin letters and digits, which are
    common in mixed Cantonese/English ASR output.  Punctuation, whitespace, and
    underscores are removed; Chinese characters are preserved.
    """
    normalised = unicodedata.normalize("NFKC", text)
    return _NON_WORD_RE.sub("", normalised).casefold()


def _parse_number_words(tokens: list[str], start: int) -> tuple[float, int]:
    """Parse an English number phrase starting at ``tokens[start]``.

    Supports values such as ``five``, ``twenty two``, ``one hundred``, and
    ``five point five``.  Returns the value and the index after the phrase.
    """
    total = 0
    current = 0
    index = start

    while index < len(tokens) and tokens[index] in _NUMBER_WORD_VALUES:
        word = tokens[index]
        if word == "hundred":
            current = max(1, current) * 100
        elif word == "thousand":
            total += max(1, current) * 1000
            current = 0
        else:
            current += _NUMBER_WORD_VALUES[word]
        index += 1

    total += current

    if index < len(tokens) and tokens[index] == "point":
        index += 1
        fraction_digits: list[str] = []
        while index < len(tokens) and (
            tokens[index].isdigit() or tokens[index] in _NUMBER_WORD_VALUES
        ):
            if tokens[index].isdigit():
                fraction_digits.append(tokens[index])
            else:
                fraction_digits.append(str(_NUMBER_WORD_VALUES[tokens[index]]))
            index += 1
        if fraction_digits:
            total = float(f"{int(total)}.{''.join(fraction_digits)}")

    return float(total), index


def _numbers_in(text: str) -> list[float]:
    """Extract Arabic and English-word numbers from ``text`` in order.

    English number words are important because clinical ASR often emits
    ``five point five`` while the LLM writes ``5.5``.
    """
    normalised = unicodedata.normalize("NFKC", text).casefold()
    tokens = _NUMBER_TOKEN_RE.findall(normalised)
    numbers: list[float] = []
    index = 0

    while index < len(tokens):
        token = tokens[index]
        if token.isdigit() or re.fullmatch(r"\d+\.\d+", token):
            numbers.append(float(token))
            index += 1
        elif token in _NUMBER_WORD_VALUES:
            number, index = _parse_number_words(tokens, index)
            numbers.append(number)
        else:
            index += 1

    return numbers


def _numbers_preserved(quote: str, text: str) -> bool:
    """Require every number in ``quote`` to appear in ``text`` in order.

    Fuzzy matching must never turn ``3.5 cm`` into ``35 cm`` or ``3.5`` into
    ``4.5``.  Extracting the numbers before similarity scoring closes that
    clinical safety hole.  Extra numbers in the transcript are allowed because
    a quote is usually a substring of a longer sentence.
    """
    quote_numbers = _numbers_in(quote)
    if not quote_numbers:
        return True

    text_numbers = _numbers_in(text)
    position = 0
    for number in text_numbers:
        if position >= len(quote_numbers):
            break
        if math.isclose(
            number,
            quote_numbers[position],
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            position += 1
    return position == len(quote_numbers)


def _stem_token(token: str) -> str:
    """Apply a tiny English plural stemmer for token comparison."""
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith("es"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


def _semantic_tokens(text: str) -> list[str]:
    """Extract content tokens used by the value-support check."""
    tokens = _WORD_RE.findall(unicodedata.normalize("NFKC", text).casefold())
    result: list[str] = []
    for token in tokens:
        if token in _SEMANTIC_STOPWORDS:
            continue
        if token in _NUMBER_WORD_VALUES:
            continue
        result.append(_stem_token(token))
    return result


def _token_supported(token: str, quote_tokens: list[str]) -> bool:
    """Return whether one value token is represented in the quote tokens."""
    for quote_token in quote_tokens:
        if token == quote_token:
            return True
        if len(token) >= 4 and (token in quote_token or quote_token in token):
            return True
        if (
            SequenceMatcher(
                None,
                token,
                quote_token,
                autojunk=False,
            ).ratio()
            >= 0.8
        ):
            return True
    return False


def _polarity(text: str) -> int:
    """Return 1 for positive, -1 for negative, 0 for neutral/unknown."""
    normalised = (
        " "
        + " ".join(
            re.findall(
                r"[a-z0-9]+",
                unicodedata.normalize("NFKC", text).casefold(),
            )
        )
        + " "
    )

    if any(
        phrase in normalised
        for phrase in ("not applicable", "not assessed", "not stated")
    ):
        return 0
    if any(marker in normalised for marker in _NEGATIVE_MARKERS):
        return -1
    if any(marker in normalised for marker in _POSITIVE_MARKERS):
        return 1
    return 0


def _value_supported_by_quote(
    value: str,
    quote: str,
) -> tuple[bool, str | None]:
    """Check that a quote supports the field value's numbers and core terms.

    Returns:
        ``(True, None)`` when the quote supports the value; otherwise
        ``(False, reason)`` with one of the value-validation messages.
    """
    value_numbers = _numbers_in(value)
    if value_numbers:
        quote_numbers = _numbers_in(quote)
        position = 0
        for number in quote_numbers:
            if position >= len(value_numbers):
                break
            if math.isclose(
                number,
                value_numbers[position],
                rel_tol=0.0,
                abs_tol=1e-9,
            ):
                position += 1
        if position != len(value_numbers):
            return False, VALUE_NUMBER_MSG

    value_polarity = _polarity(value)
    if value_polarity != 0 and _polarity(quote) != value_polarity:
        return False, VALUE_POLARITY_MSG

    value_tokens = _semantic_tokens(value)
    quote_tokens = _semantic_tokens(quote)
    if any(not _token_supported(token, quote_tokens) for token in value_tokens):
        return False, VALUE_SUPPORT_MSG

    return True, None


def _best_partial_ratio(needle: str, haystack: str) -> float:
    """Return the best ``SequenceMatcher`` ratio for a quote-sized window.

    ``difflib.SequenceMatcher.ratio()`` compares the whole haystack, which is
    unfair when a short quote sits inside a long segment.  Sliding a window of
    the quote's length (plus or minus one character for insertions/deletions)
    gives a fairer typo tolerance score.
    """
    if not needle or not haystack:
        return 0.0

    if len(needle) >= len(haystack):
        return SequenceMatcher(
            None,
            needle,
            haystack,
            autojunk=False,
        ).ratio()

    best = 0.0
    window_sizes = {
        max(1, len(needle) - 1),
        len(needle),
        min(len(haystack), len(needle) + 1),
    }
    for size in sorted(window_sizes):
        if size > len(haystack):
            continue
        for start in range(len(haystack) - size + 1):
            ratio = SequenceMatcher(
                None,
                needle,
                haystack[start : start + size],
                autojunk=False,
            ).ratio()
            if ratio > best:
                best = ratio
                if best >= 0.999:
                    return best
    return best


def _quote_matches(quote: str, text: str) -> bool:
    """Return whether ``quote`` is supported by ``text``.

    Exact matches after normalisation are accepted immediately.  Shorter quotes
    must match exactly; longer quotes may differ by a small typo up to
    :data:`FUZZY_MATCH_THRESHOLD`.  Numbers are checked before any fuzzy logic.
    """
    if not isinstance(quote, str) or not isinstance(text, str):
        return False
    if not _numbers_preserved(quote, text):
        return False

    normalised_quote = _normalise_for_match(quote)
    normalised_text = _normalise_for_match(text)
    if not normalised_quote or not normalised_text:
        return False
    if normalised_quote in normalised_text:
        # A two-letter ASCII quote such as "is" can occur inside a longer word
        # ("this"); require a little more signal before accepting it.
        return not (
            _ASCII_ALNUM_RE.fullmatch(normalised_quote) and len(normalised_quote) < 3
        )
    if len(normalised_quote) < MIN_FUZZY_QUOTE_LENGTH:
        return False

    return (
        _best_partial_ratio(normalised_quote, normalised_text) >= FUZZY_MATCH_THRESHOLD
    )


def _segment_id_key(value: Any) -> str:
    """Normalise a segment id for exact lookup.

    Clean-segment ids may arrive as an integer, an integral float, or a string
    with surrounding whitespace.  Matching them consistently prevents a
    spurious "segment not found" result from a formatting difference.
    """
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _has_foreign_timestamps(
    evidence: Evidence,
    segment_index: dict[str, dict],
) -> bool:
    """Detect timestamps that did not come from the referenced segment.

    A re-audit fills evidence timestamps with the segment's exact start/end;
    those are treated as backend-owned and are not flagged again.  An LLM that
    invents different values is flagged.
    """
    if evidence.start is None and evidence.end is None:
        return False

    segment = segment_index.get(_segment_id_key(evidence.segment_id))
    if segment is None:
        return True

    segment_start = _to_seconds(segment.get("start"))
    segment_end = _to_seconds(segment.get("end"))
    if segment_start is None or segment_end is None:
        return True
    if evidence.start is None or evidence.end is None:
        return True

    return not (
        math.isclose(
            evidence.start,
            segment_start,
            rel_tol=0.0,
            abs_tol=1e-6,
        )
        and math.isclose(
            evidence.end,
            segment_end,
            rel_tol=0.0,
            abs_tol=1e-6,
        )
    )


def _unreferenced_conflicts(
    llm_result: ColoStructExtraction,
    segment_index: dict[str, dict],
    override_ids: dict[str, set[str]],
) -> dict[str, list[str]]:
    """Find field-related statements that were mentioned but not cited."""
    issues: dict[str, list[str]] = {}

    for field_name, field in llm_result.fields.items():
        value = field.value
        if not value or not field.evidence:
            continue

        cues = _FIELD_CONFLICT_CUES.get(field_name)
        if not cues:
            continue

        cited = {_segment_id_key(evidence.segment_id) for evidence in field.evidence}
        excluded = cited | override_ids.get(field_name, set())
        normalised_value = _normalise_for_match(value)
        if not normalised_value:
            continue

        for segment_id, segment in segment_index.items():
            if segment_id in excluded:
                continue
            text = segment.get("text")
            if not isinstance(text, str):
                continue

            normalised_text = _normalise_for_match(text)
            if not any(cue in normalised_text for cue in cues):
                continue
            if normalised_value in normalised_text:
                continue

            # For binary findings, a matching polarity is a duplicate mention,
            # not a conflict (e.g. value "absent" vs "no perforation").
            value_polarity = _polarity(value)
            text_polarity = _polarity(text)
            if value_polarity != 0 and text_polarity == value_polarity:
                continue

            issues.setdefault(field_name, []).append(UNREFERENCED_CONFLICT_MSG)
            logger.warning(
                "Unreferenced conflict: field=%s segment_id=%s",
                field_name,
                segment_id,
            )
            break

    return issues


def _build_segment_index(clean_segments: list[dict]) -> dict[str, dict]:
    """Index clean segments by ``segment_id`` for O(1) evidence lookup.

    Duplicate ids keep the first occurrence and log a warning.  Malformed
    entries are skipped rather than aborting the audit.
    """
    index: dict[str, dict] = {}
    for segment in clean_segments or []:
        if not isinstance(segment, dict):
            logger.warning(
                "Skipping clean segment of unsupported type: %s",
                type(segment).__name__,
            )
            continue

        raw_id = segment.get("segment_id")
        if raw_id is None or _segment_id_key(raw_id) == "":
            logger.warning("Skipping clean segment without a usable segment_id")
            continue

        key = _segment_id_key(raw_id)
        if key in index:
            logger.warning(
                "Duplicate segment_id %s in clean_segments; keeping the first",
                key,
            )
            continue
        index[key] = segment
    return index


def _split_messages(value: str | None) -> list[str]:
    """Split a validation message string into non-empty parts."""
    if not value:
        return []
    return [part.strip() for part in re.split(r"[；;]", value) if part.strip()]


def _reset_audit_messages(field: FieldModel) -> None:
    """Remove messages written by a previous run of this audit.

    Messages from other back-end rules are preserved.  This keeps a re-audit
    from leaving a stale "evidence mismatch" warning on a field that has since
    been corrected and is now ``POPULATED``.
    """
    existing = _split_messages(field.validation_msg)
    if not existing:
        return
    remaining = [part for part in existing if part not in _AUDIT_OWNED_MESSAGES]
    field.validation_msg = "；".join(remaining) if remaining else None


def _append_validation_message(field: FieldModel, message: str) -> None:
    """Append ``message`` to a field's validation text without duplicates."""
    if not message:
        return

    parts = _split_messages(field.validation_msg)
    if message not in parts:
        parts.append(message)
        field.validation_msg = "；".join(parts)


def _resolve_evidence(
    evidence: Evidence,
    segment_index: dict[str, dict],
) -> tuple[bool, str | None]:
    """Verify one evidence item and fill its global timestamps on success.

    The function is intentionally exception-free for expected data problems:
    missing segment ids, missing text, quote mismatches, and invalid timestamps
    all return a reason instead of raising.  On failure ``start`` and ``end``
    are cleared so a previous audit cannot leave a stale span behind.

    Args:
        evidence: LLM evidence containing ``segment_id`` and ``quote``.
        segment_index: Clean segments keyed by ``segment_id``.

    Returns:
        ``(True, None)`` when the quote is supported and timestamps were
        assigned; ``(False, reason)`` otherwise.
    """
    evidence.start = None
    evidence.end = None

    segment = segment_index.get(_segment_id_key(evidence.segment_id))
    if segment is None:
        return False, EVIDENCE_SEGMENT_MISSING_MSG

    text = segment.get("text")
    if not isinstance(text, str) or not text.strip():
        return False, EVIDENCE_MISMATCH_MSG
    if not _quote_matches(evidence.quote, text):
        return False, EVIDENCE_MISMATCH_MSG

    start = _to_seconds(segment.get("start"))
    end = _to_seconds(segment.get("end"))
    if start is None or end is None:
        return False, EVIDENCE_TIMESTAMP_MSG
    if end < start:
        return False, EVIDENCE_TIMESTAMP_ORDER_MSG

    evidence.start = start
    evidence.end = end
    return True, None


def _audit_overrides(
    llm_result: ColoStructExtraction,
    segment_index: dict[str, dict],
) -> dict[str, list[str]]:
    """Audit override chronology and return issues keyed by field name.

    The override contract is strict: the new evidence's segment must start
    *after* the old evidence's segment.  A same-segment override is therefore
    flagged as well; this is deliberate because the contract uses segment
    start times rather than character offsets inside a segment.
    """
    issues: dict[str, list[str]] = {}

    for override in llm_result.override_logs:
        field = llm_result.fields.get(override.field_name)
        if field is None:
            logger.warning(
                "Override references unknown field: %s",
                override.field_name,
            )
            continue

        old_foreign = _has_foreign_timestamps(
            override.old_evidence,
            segment_index,
        )
        new_foreign = _has_foreign_timestamps(
            override.new_evidence,
            segment_index,
        )
        if old_foreign or new_foreign:
            issues.setdefault(override.field_name, []).append(
                EVIDENCE_LLM_TIMESTAMP_MSG
            )
            logger.warning(
                "LLM supplied override timestamps: field=%s",
                override.field_name,
            )

        old_ok, old_reason = _resolve_evidence(
            override.old_evidence,
            segment_index,
        )
        new_ok, new_reason = _resolve_evidence(
            override.new_evidence,
            segment_index,
        )

        if not old_ok or not new_ok:
            issues.setdefault(override.field_name, []).append(OVERRIDE_EVIDENCE_MSG)
            logger.warning(
                "Override evidence failed: field=%s old_ok=%s "
                "old_reason=%s new_ok=%s new_reason=%s",
                override.field_name,
                old_ok,
                old_reason,
                new_ok,
                new_reason,
            )
            continue

        old_start = override.old_evidence.start
        new_start = override.new_evidence.start
        if old_start is None or new_start is None:
            issues.setdefault(override.field_name, []).append(OVERRIDE_EVIDENCE_MSG)
            logger.warning(
                "Override timestamp missing after resolution: field=%s",
                override.field_name,
            )
            continue

        if new_start <= old_start:
            issues.setdefault(override.field_name, []).append(OVERRIDE_ORDER_MSG)
            logger.warning(
                "Override order anomaly: field=%s old_start=%.3f new_start=%.3f",
                override.field_name,
                old_start,
                new_start,
            )

    return issues


def audit_extraction(
    llm_result: ColoStructExtraction,
    clean_segments: list[dict],
) -> ColoStructExtraction:
    """Audit an LLM extraction against cleaned ASR segments.

    The audit mutates ``llm_result`` in place and returns the same object.  It
    fills every verified evidence span with the referenced segment's
    ``start``/``end``, rewrites field statuses from the evidence outcome, and
    evaluates the export block.

    Status rules:
        * value empty, no failed evidence: ``ABSENT``;
        * value empty but evidence failed verification: ``FLAGGED``;
        * value present, no evidence: ``FLAGGED`` with a missing-evidence
          message;
        * value present, at least one evidence item failed quote, value,
          number, polarity, or LLM-timestamp validation: ``FLAGGED``;
        * value present, all evidence verified and value-supported:
          ``POPULATED``;
        * temporal override anomaly: ``FLAGGED`` with the override message;
        * unreferenced conflict: ``FLAGGED`` with the conflict message.

    Export block:
        ``has_block`` is true when there is at least one value-bearing field and
        no value-bearing field has a fully verified evidence span.  "Fully
        verified" means quote exists, value support passes, and the evidence
        did not carry LLM-supplied timestamps.  That covers "all quotes were
        fabricated", "all values were unsupported by their quotes", and "every
        value was returned without evidence".  A partial hallucination leaves
        the export enabled because a human can still review the flagged field.

        This value is the *initial* backend decision.  It is a plain mutable
        field: after a doctor confirms review and resolves all pending flags,
        the front-end may set ``has_block = False`` without calling this
        function again.  Re-running the audit would recompute it from the
        evidence, so this audit is not the human-review unlock endpoint.

    Args:
        llm_result: Untrusted extraction returned by the LLM.  It is mutated.
        clean_segments: Cleaned ASR segments, each with ``segment_id``,
            ``text``, ``start``, and ``end``.

    Returns:
        The same ``llm_result`` object after audit.

    Raises:
        TypeError: Only if ``llm_result`` is not a ``ColoStructExtraction``.
    """
    if not isinstance(llm_result, ColoStructExtraction):
        raise TypeError(
            "llm_result must be a ColoStructExtraction, "
            f"got {type(llm_result).__name__}"
        )

    segment_index = _build_segment_index(clean_segments)

    override_ids: dict[str, set[str]] = {}
    for override in llm_result.override_logs:
        ids = override_ids.setdefault(override.field_name, set())
        ids.add(_segment_id_key(override.old_evidence.segment_id))
        ids.add(_segment_id_key(override.new_evidence.segment_id))

    value_fields = 0
    value_evidence_checked = 0
    value_evidence_matched = 0

    for field_name, field in llm_result.fields.items():
        _reset_audit_messages(field)
        value_present = bool(field.value)
        if value_present:
            value_fields += 1

        evidence_items = field.evidence
        if not evidence_items:
            if value_present:
                field.status = StatusEnum.FLAGGED
                _append_validation_message(field, EVIDENCE_MISSING_MSG)
                logger.warning(
                    "Missing evidence: field=%s value_len=%d",
                    field_name,
                    len(field.value or ""),
                )
            else:
                field.status = StatusEnum.ABSENT
            continue

        matched = 0
        failed = 0
        for evidence in evidence_items:
            foreign_timestamps = _has_foreign_timestamps(
                evidence,
                segment_index,
            )
            ok, reason = _resolve_evidence(evidence, segment_index)

            if foreign_timestamps:
                failed += 1
                _append_validation_message(
                    field,
                    EVIDENCE_LLM_TIMESTAMP_MSG,
                )
                logger.warning(
                    "LLM supplied timestamps: field=%s segment_id=%s",
                    field_name,
                    evidence.segment_id,
                )
                if not ok:
                    message = reason or EVIDENCE_MISMATCH_MSG
                    _append_validation_message(field, message)
                    logger.warning(
                        "Evidence audit failed: field=%s segment_id=%s "
                        "quote_len=%d reason=%s",
                        field_name,
                        evidence.segment_id,
                        len(evidence.quote),
                        message,
                    )
                continue

            if not ok:
                failed += 1
                message = reason or EVIDENCE_MISMATCH_MSG
                _append_validation_message(field, message)
                logger.warning(
                    "Evidence audit failed: field=%s segment_id=%s "
                    "quote_len=%d reason=%s",
                    field_name,
                    evidence.segment_id,
                    len(evidence.quote),
                    message,
                )
                continue

            if value_present:
                supported, support_reason = _value_supported_by_quote(
                    field.value,
                    evidence.quote,
                )
                if not supported:
                    failed += 1
                    _append_validation_message(
                        field,
                        support_reason or VALUE_SUPPORT_MSG,
                    )
                    logger.warning(
                        "Value support failed: field=%s segment_id=%s reason=%s",
                        field_name,
                        evidence.segment_id,
                        support_reason or VALUE_SUPPORT_MSG,
                    )
                    continue

            matched += 1
            logger.debug(
                "Evidence verified: field=%s segment_id=%s quote_len=%d",
                field_name,
                evidence.segment_id,
                len(evidence.quote),
            )

        if value_present:
            value_evidence_checked += len(evidence_items)
            value_evidence_matched += matched
            field.status = (
                StatusEnum.POPULATED
                if failed == 0 and matched == len(evidence_items)
                else StatusEnum.FLAGGED
            )
        else:
            # An absent field with fabricated evidence must not hide the
            # hallucination behind an empty value.
            field.status = StatusEnum.FLAGGED if failed else StatusEnum.ABSENT

    conflict_issues = _unreferenced_conflicts(
        llm_result,
        segment_index,
        override_ids,
    )
    for field_name, messages in conflict_issues.items():
        field = llm_result.fields.get(field_name)
        if field is None:
            continue
        for message in messages:
            _append_validation_message(field, message)
        field.status = StatusEnum.FLAGGED

    override_issues = _audit_overrides(llm_result, segment_index)
    for field_name, messages in override_issues.items():
        field = llm_result.fields.get(field_name)
        if field is None:
            continue
        for message in messages:
            _append_validation_message(field, message)
        field.status = StatusEnum.FLAGGED

    severe_hallucination = value_fields > 0 and (
        value_evidence_checked == 0 or value_evidence_matched == 0
    )
    llm_result.has_block = severe_hallucination

    flagged_count = sum(
        1 for field in llm_result.fields.values() if field.status is StatusEnum.FLAGGED
    )
    logger.info(
        "Audit complete: value_fields=%d verified_evidence=%d/%d "
        "flagged=%d has_block=%s",
        value_fields,
        value_evidence_matched,
        value_evidence_checked,
        flagged_count,
        severe_hallucination,
    )
    if severe_hallucination:
        logger.error(
            "Blocking export: no value-bearing field has verified evidence "
            "(value_fields=%d verified=%d/%d)",
            value_fields,
            value_evidence_matched,
            value_evidence_checked,
        )

    return llm_result


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    clean_segments = [
        {
            "segment_id": "seg-001",
            "text": "呢個 tumour 大概 3 cm",
            "start": 0.0,
            "end": 2.5,
        },
        {
            "segment_id": "seg-002",
            "text": "但係我睇到 4 cm，其實 5 cm，遠端切緣 5 cm",
            "start": 2.5,
            "end": 5.0,
        },
        {
            "segment_id": "seg-003",
            "text": "淋巴結 2/14 有轉移，遠端切緣 1 cm",
            "start": 5.0,
            "end": 7.0,
        },
    ]

    llm_result = ColoStructExtraction(
        fields={
            "tumour_dimension": FieldModel(
                value="3 cm",
                evidence=[
                    Evidence(
                        segment_id="seg-001",
                        quote="呢個 tumour 大概 3 cm",
                    )
                ],
                status=StatusEnum.POPULATED,
            ),
            "lymph_node_status": FieldModel(
                value="2/14",
                evidence=[
                    Evidence(
                        segment_id="seg-003",
                        quote="所有淋巴結都係陰性",
                    )
                ],
                status=StatusEnum.POPULATED,
            ),
            "proximal_and_distal_margins": FieldModel(
                value="5 cm",
                evidence=[
                    Evidence(
                        segment_id="seg-002",
                        quote="遠端切緣 5 cm",
                    )
                ],
                status=StatusEnum.POPULATED,
            ),
        },
        override_logs=[
            OverrideLog(
                field_name="proximal_and_distal_margins",
                old_evidence=Evidence(
                    segment_id="seg-003",
                    quote="遠端切緣 1 cm",
                ),
                new_evidence=Evidence(
                    segment_id="seg-002",
                    quote="遠端切緣 5 cm",
                ),
            )
        ],
    )

    audited = audit_extraction(llm_result, clean_segments)

    print("AUDITED EXTRACTION")
    print(audited.model_dump_json(indent=2))

    # The perfect match must carry the segment's timestamps.
    dimension = audited.fields["tumour_dimension"]
    assert dimension.status is StatusEnum.POPULATED
    assert dimension.evidence[0].start == 0.0
    assert dimension.evidence[0].end == 2.5

    # The fabricated quote must be flagged and must not retain timestamps.
    nodes = audited.fields["lymph_node_status"]
    assert nodes.status is StatusEnum.FLAGGED
    assert nodes.evidence[0].start is None
    assert nodes.evidence[0].end is None
    assert EVIDENCE_MISMATCH_MSG in (nodes.validation_msg or "")

    # The override field's evidence is real, but its override chronology is
    # inverted: the "new" statement is in an earlier segment than the "old".
    margin = audited.fields["proximal_and_distal_margins"]
    assert margin.status is StatusEnum.FLAGGED
    assert margin.evidence[0].start == 2.5
    assert margin.evidence[0].end == 5.0
    assert OVERRIDE_ORDER_MSG in (margin.validation_msg or "")
    assert audited.override_logs[0].old_evidence.start == 5.0
    assert audited.override_logs[0].new_evidence.start == 2.5

    # One value-bearing field has verified evidence, so the mixed draft is
    # reviewable rather than globally blocked.
    assert audited.has_block is False

    # Punctuation tolerance: the quote adds punctuation the ASR text lacks, and
    # the field begins at the Pydantic default ABSENT but must become POPULATED.
    punctuation = ColoStructExtraction(
        fields={
            "tumour_dimension": FieldModel(
                value="3 cm",
                evidence=[
                    Evidence(
                        segment_id="seg-001",
                        quote="呢個 tumour，大概 3 cm。",
                    )
                ],
            )
        }
    )
    audited_punctuation = audit_extraction(punctuation, clean_segments)
    assert audited_punctuation.fields["tumour_dimension"].status is StatusEnum.POPULATED
    assert audited_punctuation.fields["tumour_dimension"].evidence[0].start == 0.0

    # An out-of-range segment id must not raise KeyError: it becomes a field
    # flag and triggers the export block for this value-only draft.
    missing_segment = ColoStructExtraction(
        fields={
            "tumour_site": FieldModel(
                value="rectum",
                evidence=[
                    Evidence(
                        segment_id="seg-999",
                        quote="呢個 tumour",
                    )
                ],
            )
        }
    )
    audited_missing = audit_extraction(missing_segment, clean_segments)
    assert audited_missing.fields["tumour_site"].status is StatusEnum.FLAGGED
    assert EVIDENCE_SEGMENT_MISSING_MSG in (
        audited_missing.fields["tumour_site"].validation_msg or ""
    )
    assert audited_missing.has_block is True

    # A draft whose only value has fabricated evidence must block export.
    blocking = ColoStructExtraction(
        fields={
            "tumour_site": FieldModel(
                value="rectum",
                evidence=[
                    Evidence(
                        segment_id="seg-001",
                        quote="完全捏造嘅引用",
                    )
                ],
                status=StatusEnum.POPULATED,
            )
        }
    )
    audited_blocking = audit_extraction(blocking, clean_segments)
    assert audited_blocking.fields["tumour_site"].status is StatusEnum.FLAGGED
    assert audited_blocking.has_block is True

    # Front-end contract: has_block is the initial backend decision and remains
    # a plain mutable field.  After human review the UI may unlock export
    # without calling this audit again.
    audited_blocking.has_block = False
    assert audited_blocking.has_block is False

    # A single typo in a longer quote is tolerated, but a changed number is not.
    fuzzy = ColoStructExtraction(
        fields={
            "tumour_dimension": FieldModel(
                value="3 cm",
                evidence=[
                    Evidence(
                        segment_id="seg-001",
                        quote="呢個 tumor 大概 3 cm",
                    )
                ],
            )
        }
    )
    audited_fuzzy = audit_extraction(fuzzy, clean_segments)
    assert audited_fuzzy.fields["tumour_dimension"].status is StatusEnum.POPULATED

    wrong_number = ColoStructExtraction(
        fields={
            "tumour_dimension": FieldModel(
                value="4 cm",
                evidence=[
                    Evidence(
                        segment_id="seg-001",
                        quote="呢個 tumour 大概 4 cm",
                    )
                ],
            )
        }
    )
    audited_wrong_number = audit_extraction(wrong_number, clean_segments)
    assert audited_wrong_number.fields["tumour_dimension"].status is StatusEnum.FLAGGED
    assert audited_wrong_number.has_block is True

    print("\nAll validate assertions passed.")
