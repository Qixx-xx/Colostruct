"""In-memory integration: A adapter -> official cleanup -> A service -> official validate.

The parent process installs the test stub via ``tests/__init__.py``; every
scenario therefore runs in a clean subprocess whose ``PYTHONPATH`` contains the
dev copy first and the official Colostruct checkout second. The child asserts
the real source files before exercising the pipeline.

Set ``COLOSTRUCT_REPO_ROOT`` to the Colostruct checkout, or run the tests from
that checkout so the repository root can be discovered automatically. Without
a checkout containing ``core/pathology_schema.py``, the tests are skipped with
an actionable message.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from tests import resolve_repo_root

DEV_ROOT = Path(__file__).resolve().parents[1]

CHILD_CODE = r"""
import json
import logging
import os
import sys

import core
import core.cleanup as cleanup_module
import core.pathology_schema as schema_module
import core.validate as validate_module
from core.asr import ASRConfig, ASRResult, ASRSegment
from core.asr_adapter import adapt_asr_result
from core.cleanup import clean_transcript
from core.llm.service import extract_clinical_info_result
from core.pathology_schema import (
    PATHOLOGY_FIELD_KEYS,
    ColoStructExtraction,
    Evidence,
)
from core.validate import (
    EVIDENCE_MISMATCH_MSG,
    EVIDENCE_SEGMENT_MISSING_MSG,
    audit_extraction,
)

SCENARIO = sys.argv[1]

RAW_SEGMENTS = [
    {"segment_id": "seg-001", "start": 0.0, "end": 2.0, "text": " um the tumour is 3 cm"},
    {"segment_id": "seg-002", "start": 2.0, "end": 3.0, "text": " no perforation seen"},
]


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def generate_json(self, *, system, user):
        self.calls.append({"system": system, "user": user})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeEngine:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def transcribe(self, audio_path):
        self.calls += 1
        return self.result


class WarningCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def asr_result():
    return ASRResult(
        status="success",
        segments=[
            ASRSegment(
                segment_id=item["segment_id"],
                start=item["start"],
                end=item["end"],
                text=item["text"],
            )
            for item in RAW_SEGMENTS
        ],
        model="base",
        config=ASRConfig(),
        elapsed_seconds=0.1,
    )


def cleaned_segments():
    return clean_transcript(adapt_asr_result(asr_result()).segments)


def fields_with(field_name, value, evidence):
    fields = {key: {"value": None, "evidence": []} for key in PATHOLOGY_FIELD_KEYS}
    fields[field_name] = {"value": value, "evidence": evidence}
    return fields


def pass_a_response(segments):
    return {
        "corrected_segments": [
            {"segment_id": item["segment_id"], "corrected_text": item["text"]}
            for item in segments
        ],
        "override_logs": [],
    }


def pass_b_response(field_name, value, evidence):
    return {"fields": fields_with(field_name, value, evidence)}


def status_value(field):
    return getattr(field.status, "value", str(field.status))


def run_service(field_name, value, evidence, segments):
    client = FakeClient(
        [
            pass_a_response(segments),
            pass_b_response(field_name, value, evidence),
        ]
    )
    result = extract_clinical_info_result(clean_segments=segments, client=client)
    return result, client


def audit_case(field_name, value, evidence, segments):
    result, client = run_service(field_name, value, evidence, segments)
    extraction = result.extraction
    field = extraction.fields[field_name]
    before = status_value(field)
    audited = audit_extraction(extraction, segments)
    after_field = audited.fields[field_name]
    return {
        "before_status": before,
        "after_status": status_value(after_field),
        "msg": after_field.validation_msg,
        "has_block": audited.has_block,
        "span": [
            after_field.evidence[0].start if after_field.evidence else None,
            after_field.evidence[0].end if after_field.evidence else None,
        ],
        "evidence_count": len(after_field.evidence),
        "same_object": audited is extraction,
        "extraction_class": type(audited).__name__,
        "extraction_module": type(audited).__module__,
    }


def source_info():
    return {
        "core_file": core.__file__,
        "cleanup_file": cleanup_module.__file__,
        "validate_file": validate_module.__file__,
        "schema_file": schema_module.__file__,
        "adapter_file": sys.modules[adapt_asr_result.__module__].__file__,
        "service_file": sys.modules[extract_clinical_info_result.__module__].__file__,
        "extraction_module": ColoStructExtraction.__module__,
        "tests_loaded": "tests" in sys.modules,
    }


def emit(payload):
    payload["sources"] = source_info()
    print(json.dumps(payload, ensure_ascii=False))


if SCENARIO == "full_chain":
    adapted = adapt_asr_result(asr_result())
    before = [dict(item) for item in adapted.segments]
    cleaned = clean_transcript(adapted.segments)
    result, client = run_service(
        "tumour_dimension",
        "3 cm",
        [{"segment_id": "seg-001", "quote": "3 cm"}],
        cleaned,
    )
    extraction = result.extraction
    field = extraction.fields["tumour_dimension"]
    before_status = status_value(field)
    audited = audit_extraction(extraction, cleaned)
    audited_field = audited.fields["tumour_dimension"]
    emit(
        {
            "before_texts": [item["text"] for item in before],
            "cleaned_texts": [item["text"] for item in cleaned],
            "cleaned_ids": [item["segment_id"] for item in cleaned],
            "cleaned_spans": [[item["start"], item["end"]] for item in cleaned],
            "extraction_class": type(audited).__name__,
            "extraction_module": type(audited).__module__,
            "same_object": audited is extraction,
            "before_status": before_status,
            "after_status": status_value(audited_field),
            "msg": audited_field.validation_msg,
            "has_block": audited.has_block,
            "span": [audited_field.evidence[0].start, audited_field.evidence[0].end],
            "quote": audited_field.evidence[0].quote,
            "pass_a_prompt_contains_cleaned": "the tumour is 3 cm" in client.calls[0]["user"],
            "pass_a_prompt_contains_raw_filler": " um " in client.calls[0]["user"],
        }
    )

elif SCENARIO == "missing_segment":
    cleaned = cleaned_segments()
    payload = audit_case(
        "tumour_dimension",
        "3 cm",
        [{"segment_id": "seg-999", "quote": "3 cm"}],
        cleaned,
    )
    payload["expected_msg"] = EVIDENCE_SEGMENT_MISSING_MSG
    emit(payload)

elif SCENARIO == "quote_mismatch":
    cleaned = cleaned_segments()
    payload = audit_case(
        "tumour_dimension",
        "3 cm",
        [{"segment_id": "seg-001", "quote": "5 cm"}],
        cleaned,
    )
    payload["expected_msg"] = EVIDENCE_MISMATCH_MSG
    emit(payload)

elif SCENARIO == "multi_evidence":
    cleaned = cleaned_segments()
    payload = audit_case(
        "tumour_dimension",
        "3 cm",
        [
            {"segment_id": "seg-001", "quote": "3 cm"},
            {"segment_id": "seg-001", "quote": "5 cm"},
        ],
        cleaned,
    )
    emit(payload)

elif SCENARIO == "negation_semantics":
    cleaned = cleaned_segments()
    payload = audit_case(
        "tumour_perforation",
        "perforation",
        [{"segment_id": "seg-002", "quote": "no perforation"}],
        cleaned,
    )
    payload["note"] = "Existing rule behaviour only; NOT a clinical-semantics validation."
    emit(payload)

elif SCENARIO == "audio_default_cleaner":
    raw = asr_result()
    expected_cleaned = clean_transcript(adapt_asr_result(raw).segments)
    client = FakeClient(
        [
            pass_a_response(expected_cleaned),
            pass_b_response(
                "tumour_dimension",
                "3 cm",
                [{"segment_id": "seg-001", "quote": "3 cm"}],
            ),
        ]
    )
    engine = FakeEngine(raw)
    result = extract_clinical_info_result(
        audio_path="fake-audio.wav",
        asr_engine=engine,
        client=client,
    )
    audited = audit_extraction(result.extraction, expected_cleaned)
    field = audited.fields["tumour_dimension"]
    emit(
        {
            "engine_calls": engine.calls,
            "pass_a_prompt_contains_cleaned": "the tumour is 3 cm" in client.calls[0]["user"],
            "pass_a_prompt_contains_raw_filler": " um " in client.calls[0]["user"],
            "extraction_class": type(audited).__name__,
            "has_block": audited.has_block,
            "after_status": status_value(field),
            "span": [field.evidence[0].start, field.evidence[0].end] if field.evidence else None,
            "quote": field.evidence[0].quote if field.evidence else None,
        }
    )

elif SCENARIO == "duplicate_ids":
    duplicate = clean_transcript(
        [
            {"segment_id": "seg-001", "start": 0.0, "end": 1.0, "text": "3 cm"},
            {"segment_id": "seg-001", "start": 1.0, "end": 2.0, "text": "5 cm"},
        ]
    )
    extraction = ColoStructExtraction(
        fields=fields_with(
            "tumour_dimension",
            "5 cm",
            [{"segment_id": "seg-001", "quote": "5 cm"}],
        )
    )
    before_status = status_value(extraction.fields["tumour_dimension"])
    capture = WarningCapture()
    validate_logger = logging.getLogger("core.validate")
    validate_logger.addHandler(capture)
    try:
        audited = audit_extraction(extraction, duplicate)
    finally:
        validate_logger.removeHandler(capture)
    field = audited.fields["tumour_dimension"]
    emit(
        {
            "cleanup_ids": [item["segment_id"] for item in duplicate],
            "cleanup_texts": [item["text"] for item in duplicate],
            "before_status": before_status,
            "after_status": status_value(field),
            "msg": field.validation_msg,
            "has_block": audited.has_block,
            "span": [field.evidence[0].start, field.evidence[0].end] if field.evidence else None,
            "duplicate_warning": any("Duplicate segment_id" in message for message in capture.messages),
        }
    )

else:
    raise SystemExit("unknown scenario: " + SCENARIO)
"""


class CleanupValidateIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_path = resolve_repo_root()
        cls.repo = str(cls.repo_path)
        cls.schema_path = (cls.repo_path / "core" / "pathology_schema.py").resolve()
        cls.cleanup_path = (cls.repo_path / "core" / "cleanup.py").resolve()
        cls.validate_path = (cls.repo_path / "core" / "validate.py").resolve()
        for required in (cls.schema_path, cls.cleanup_path, cls.validate_path):
            if not required.is_file():
                raise unittest.SkipTest("official module not found: " + str(required))

    def run_scenario(self, scenario):
        env = os.environ.copy()
        env["COLOSTRUCT_REPO_ROOT"] = self.repo
        env["PYTHONPATH"] = str(DEV_ROOT) + os.pathsep + self.repo
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        completed = subprocess.run(
            [sys.executable, "-c", CHILD_CODE, scenario],
            cwd=str(DEV_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
        )
        if completed.returncode != 0:
            self.fail(
                "child failed for scenario %r\nSTDERR:\n%s\nSTDOUT:\n%s"
                % (scenario, completed.stderr, completed.stdout)
            )
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        self.assertTrue(lines, "child produced no JSON output")
        payload = json.loads(lines[-1])
        self.assert_sources(payload["sources"])
        return payload

    def assert_sources(self, sources):
        self.assertEqual(Path(sources["schema_file"]).resolve(), self.schema_path)
        self.assertEqual(Path(sources["cleanup_file"]).resolve(), self.cleanup_path)
        self.assertEqual(Path(sources["validate_file"]).resolve(), self.validate_path)
        self.assertEqual(
            Path(sources["adapter_file"]).resolve(),
            (DEV_ROOT / "core" / "asr_adapter.py").resolve(),
        )
        self.assertEqual(
            Path(sources["service_file"]).resolve(),
            (DEV_ROOT / "core" / "llm" / "service.py").resolve(),
        )
        self.assertIsNone(sources["core_file"])
        self.assertFalse(sources["tests_loaded"])
        self.assertEqual(sources["extraction_module"], "core.pathology_schema")

    def test_full_chain_cleanup_then_validate(self):
        payload = self.run_scenario("full_chain")
        self.assertEqual(
            payload["before_texts"],
            [" um the tumour is 3 cm", " no perforation seen"],
        )
        self.assertEqual(
            payload["cleaned_texts"],
            ["the tumour is 3 cm", "no perforation seen"],
        )
        self.assertEqual(payload["cleaned_ids"], ["seg-001", "seg-002"])
        self.assertEqual(payload["cleaned_spans"], [[0.0, 2.0], [2.0, 3.0]])
        self.assertEqual(payload["extraction_class"], "ColoStructExtraction")
        self.assertEqual(payload["extraction_module"], "core.pathology_schema")
        self.assertTrue(payload["same_object"])
        self.assertEqual(payload["before_status"], "absent")
        self.assertEqual(payload["after_status"], "populated")
        self.assertIsNone(payload["msg"])
        self.assertFalse(payload["has_block"])
        self.assertEqual(payload["span"], [0.0, 2.0])
        self.assertEqual(payload["quote"], "3 cm")
        self.assertTrue(payload["pass_a_prompt_contains_cleaned"])
        self.assertFalse(payload["pass_a_prompt_contains_raw_filler"])

    def test_missing_segment_id_is_flagged(self):
        payload = self.run_scenario("missing_segment")
        self.assertEqual(payload["before_status"], "absent")
        self.assertEqual(payload["after_status"], "flagged")
        self.assertEqual(payload["msg"], payload["expected_msg"])
        self.assertTrue(payload["has_block"])
        self.assertEqual(payload["span"], [None, None])
        self.assertTrue(payload["same_object"])

    def test_quote_mismatch_is_flagged(self):
        payload = self.run_scenario("quote_mismatch")
        self.assertEqual(payload["before_status"], "absent")
        self.assertEqual(payload["after_status"], "flagged")
        self.assertEqual(payload["msg"], payload["expected_msg"])
        self.assertTrue(payload["has_block"])
        self.assertEqual(payload["span"], [None, None])

    def test_multi_evidence_partial_failure(self):
        payload = self.run_scenario("multi_evidence")
        self.assertEqual(payload["before_status"], "absent")
        self.assertEqual(payload["after_status"], "flagged")
        self.assertEqual(payload["evidence_count"], 2)
        # Current rule: one verified evidence is enough to keep has_block False,
        # even though the field itself is FLAGGED.
        self.assertFalse(payload["has_block"])
        self.assertEqual(payload["span"], [0.0, 2.0])

    def test_negation_semantics_current_rule(self):
        payload = self.run_scenario("negation_semantics")
        self.assertEqual(payload["before_status"], "absent")
        # Explicit expectation of the CURRENT rule: value "perforation" has no
        # polarity marker, so token support accepts the quote "no perforation".
        self.assertEqual(payload["after_status"], "populated")
        self.assertFalse(payload["has_block"])
        self.assertIn("NOT a clinical-semantics", payload["note"])

    def test_audio_path_default_cleaner(self):
        payload = self.run_scenario("audio_default_cleaner")
        self.assertEqual(payload["engine_calls"], 1)
        self.assertTrue(payload["pass_a_prompt_contains_cleaned"])
        self.assertFalse(payload["pass_a_prompt_contains_raw_filler"])
        self.assertEqual(payload["extraction_class"], "ColoStructExtraction")
        self.assertEqual(payload["after_status"], "populated")
        self.assertFalse(payload["has_block"])
        self.assertEqual(payload["span"], [0.0, 2.0])
        self.assertEqual(payload["quote"], "3 cm")

    def test_duplicate_segment_ids_keep_first(self):
        payload = self.run_scenario("duplicate_ids")
        self.assertEqual(payload["cleanup_ids"], ["seg-001", "seg-001"])
        self.assertEqual(payload["cleanup_texts"], ["3 cm", "5 cm"])
        self.assertEqual(payload["before_status"], "absent")
        # Evidence "5 cm" refers to the duplicate id; the index keeps the first
        # segment ("3 cm"), so the quote fails.
        self.assertEqual(payload["after_status"], "flagged")
        self.assertTrue(payload["has_block"])
        self.assertEqual(payload["span"], [None, None])
        self.assertTrue(payload["duplicate_warning"])


if __name__ == "__main__":
    unittest.main()
