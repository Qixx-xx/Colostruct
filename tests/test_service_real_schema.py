"""Real B-schema integration tests for the A-group service (S3).

The parent test process installs the test stub via ``tests/__init__.py``, so
every scenario runs in a clean subprocess whose ``PYTHONPATH`` contains the dev
copy first and the official Colostruct checkout second. The child asserts that
``core.pathology_schema`` really comes from the official repository before it
calls the service.

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
import os
import sys

import core
import core.pathology_schema as schema
from core.pathology_schema import (
    PATHOLOGY_FIELD_KEYS,
    ColoStructExtraction,
    Evidence,
    OverrideLog,
)
from core.llm.client import LLMError
from core.llm.service import (
    AGroupPipelineError,
    extract_clinical_info,
    extract_clinical_info_result,
)

SCENARIO = sys.argv[1]


def schema_info():
    return {
        "core_file": core.__file__,
        "core_path": list(getattr(core, "__path__", [])),
        "schema_file": schema.__file__,
        "tests_loaded": "tests" in sys.modules,
        "extraction_module": ColoStructExtraction.__module__,
        "evidence_module": Evidence.__module__,
        "override_module": OverrideLog.__module__,
        "extraction_class": ColoStructExtraction.__name__,
    }


def emit(payload):
    payload["schema"] = schema_info()
    print(json.dumps(payload, ensure_ascii=False))


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def generate_json(self, *, system, user):
        self.calls += 1
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def segments():
    return [
        {"segment_id": "seg-001", "start": 0.0, "end": 1.0, "text": " hello"},
        {"segment_id": "seg-002", "start": 1.0, "end": 2.0, "text": " world"},
    ]


def pass_a_response():
    return {
        "corrected_segments": [
            {"segment_id": "seg-001", "corrected_text": " hi"},
            {"segment_id": "seg-002", "corrected_text": " there"},
        ],
        "override_logs": [
            {
                "field_name": "tumour_site",
                "old_evidence": {"segment_id": "seg-001", "quote": "hello"},
                "new_evidence": {"segment_id": "seg-002", "quote": "world"},
            }
        ],
    }


def full_fields():
    return {key: {"value": None, "evidence": []} for key in PATHOLOGY_FIELD_KEYS}


def fields_with_evidence(segment_id="seg-001", quote="hello"):
    fields = full_fields()
    fields["tumour_site"] = {
        "value": "rectum",
        "evidence": [{"segment_id": segment_id, "quote": quote}],
    }
    return fields


def field_status(field):
    return getattr(field.status, "value", str(field.status))


if SCENARIO == "success":
    client = FakeClient([pass_a_response(), {"fields": fields_with_evidence()}])
    result = extract_clinical_info_result(clean_segments=segments(), client=client)
    log = result.extraction.override_logs[0]
    evidence = result.extraction.fields["tumour_site"].evidence[0]
    emit(
        {
            "agroup_keys": list(result.model_dump().keys()),
            "extraction_class": type(result.extraction).__name__,
            "fields_count": len(result.extraction.fields),
            "tumour_value": result.extraction.fields["tumour_site"].value,
            "evidence_id": evidence.segment_id,
            "evidence_quote": evidence.quote,
            "evidence_start": evidence.start,
            "evidence_end": evidence.end,
            "override_class": type(log).__name__,
            "override_is_real": isinstance(log, OverrideLog),
            "old_evidence_class": type(log.old_evidence).__name__,
            "new_evidence_class": type(log.new_evidence).__name__,
            "old_id": log.old_evidence.segment_id,
            "old_quote": log.old_evidence.quote,
            "new_id": log.new_evidence.segment_id,
            "new_quote": log.new_evidence.quote,
            "diagnostics": [[stage.stage, stage.status] for stage in result.diagnostics.stages],
            "client_calls": client.calls,
        }
    )

elif SCENARIO == "pass_a_fallback":
    client = FakeClient([LLMError("pass a down"), {"fields": fields_with_evidence()}])
    result = extract_clinical_info_result(clean_segments=segments(), client=client)
    emit(
        {
            "diagnostics": [[stage.stage, stage.status] for stage in result.diagnostics.stages],
            "extraction_class": type(result.extraction).__name__,
            "override_count": len(result.extraction.override_logs),
            "client_calls": client.calls,
        }
    )

elif SCENARIO == "pass_b_failure":
    client = FakeClient([pass_a_response(), RuntimeError("pass b down")])
    try:
        extract_clinical_info_result(clean_segments=segments(), client=client)
        emit({"exception_type": None})
    except AGroupPipelineError as exc:
        emit(
            {
                "exception_type": type(exc).__name__,
                "stage": exc.stage,
                "cause_type": exc.cause_type,
                "client_calls": client.calls,
            }
        )

elif SCENARIO == "old_pass_a_failure":
    client = FakeClient([LLMError("pass a down")])
    try:
        extract_clinical_info(segments(), client=client)
        emit({"exception_type": None, "client_calls": client.calls})
    except Exception as exc:
        emit({"exception_type": type(exc).__name__, "client_calls": client.calls})

elif SCENARIO == "old_pass_b_failure":
    client = FakeClient([pass_a_response(), RuntimeError("pass b down")])
    try:
        extract_clinical_info(segments(), client=client)
        emit({"exception_type": None, "client_calls": client.calls})
    except Exception as exc:
        emit(
            {
                "exception_type": type(exc).__name__,
                "is_wrapper": isinstance(exc, AGroupPipelineError),
                "client_calls": client.calls,
            }
        )

elif SCENARIO == "empty_segments":
    client = FakeClient([])
    try:
        extract_clinical_info_result(clean_segments=[], client=client)
        emit({"exception_type": None, "client_calls": client.calls})
    except Exception as exc:
        emit({"exception_type": type(exc).__name__, "client_calls": client.calls})

elif SCENARIO == "missing_evidence":
    client = FakeClient([pass_a_response(), {"fields": full_fields()}])
    result = extract_clinical_info_result(clean_segments=segments(), client=client)
    field = result.extraction.fields["tumour_site"]
    emit(
        {
            "fields_count": len(result.extraction.fields),
            "value": field.value,
            "evidence_count": len(field.evidence),
            "status": field_status(field),
            "extraction_class": type(result.extraction).__name__,
        }
    )

elif SCENARIO == "empty_text":
    empty = [{"segment_id": "seg-001", "start": 0.0, "end": 1.0, "text": ""}]
    pass_a = {
        "corrected_segments": [{"segment_id": "seg-001", "corrected_text": ""}],
        "override_logs": [],
    }
    client = FakeClient([pass_a, {"fields": full_fields()}])
    result = extract_clinical_info_result(clean_segments=empty, client=client)
    emit(
        {
            "extraction_class": type(result.extraction).__name__,
            "fields_count": len(result.extraction.fields),
            "client_calls": client.calls,
        }
    )

elif SCENARIO == "invalid_segment_id":
    fields = full_fields()
    fields["tumour_site"] = {
        "value": "rectum",
        "evidence": [{"segment_id": "seg-999", "quote": "hello"}],
    }
    client = FakeClient([pass_a_response(), {"fields": fields}])
    result = extract_clinical_info_result(clean_segments=segments(), client=client)
    evidence = result.extraction.fields["tumour_site"].evidence[0]
    emit(
        {
            "evidence_id": evidence.segment_id,
            "evidence_quote": evidence.quote,
            "evidence_class": type(evidence).__name__,
            "audit_ran": False,
        }
    )

else:
    raise SystemExit("unknown scenario: " + SCENARIO)
"""


class RealSchemaServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_path = resolve_repo_root()
        cls.repo = str(cls.repo_path)
        cls.schema_path = (cls.repo_path / "core" / "pathology_schema.py").resolve()

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
                "real-schema child failed for scenario %r\nSTDERR:\n%s\nSTDOUT:\n%s"
                % (scenario, completed.stderr, completed.stdout)
            )
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        self.assertTrue(lines, "child produced no JSON output")
        payload = json.loads(lines[-1])
        self.assert_schema_source(payload["schema"])
        return payload

    def assert_schema_source(self, info):
        self.assertEqual(Path(info["schema_file"]).resolve(), self.schema_path)
        self.assertIsNone(info["core_file"])
        self.assertFalse(info["tests_loaded"])
        self.assertEqual(info["extraction_module"], "core.pathology_schema")
        self.assertEqual(info["evidence_module"], "core.pathology_schema")
        self.assertEqual(info["override_module"], "core.pathology_schema")
        self.assertEqual(info["extraction_class"], "ColoStructExtraction")

    def test_success_returns_real_schema_and_override_objects(self):
        payload = self.run_scenario("success")
        self.assertEqual(
            payload["agroup_keys"],
            ["extraction", "pass_a_result", "field_uncertainties", "diagnostics", "schema_version"],
        )
        self.assertEqual(payload["extraction_class"], "ColoStructExtraction")
        self.assertEqual(payload["fields_count"], 15)
        self.assertEqual(payload["tumour_value"], "rectum")
        self.assertEqual(payload["evidence_id"], "seg-001")
        self.assertEqual(payload["evidence_quote"], "hello")
        self.assertIsNone(payload["evidence_start"])
        self.assertIsNone(payload["evidence_end"])
        self.assertEqual(payload["override_class"], "OverrideLog")
        self.assertTrue(payload["override_is_real"])
        self.assertEqual(payload["old_evidence_class"], "Evidence")
        self.assertEqual(payload["new_evidence_class"], "Evidence")
        self.assertEqual(payload["old_id"], "seg-001")
        self.assertEqual(payload["old_quote"], "hello")
        self.assertEqual(payload["new_id"], "seg-002")
        self.assertEqual(payload["new_quote"], "world")
        self.assertEqual(payload["diagnostics"], [["pass_a", "success"], ["pass_b", "success"]])
        self.assertEqual(payload["client_calls"], 2)

    def test_pass_a_llm_error_falls_back_to_real_schema(self):
        payload = self.run_scenario("pass_a_fallback")
        self.assertEqual(payload["diagnostics"], [["pass_a", "failed"], ["pass_b", "success"]])
        self.assertEqual(payload["extraction_class"], "ColoStructExtraction")
        self.assertEqual(payload["override_count"], 0)
        self.assertEqual(payload["client_calls"], 2)

    def test_pass_b_failure_wraps_with_original_cause(self):
        payload = self.run_scenario("pass_b_failure")
        self.assertEqual(payload["exception_type"], "AGroupPipelineError")
        self.assertEqual(payload["stage"], "pass_b")
        self.assertEqual(payload["cause_type"], "RuntimeError")
        self.assertEqual(payload["client_calls"], 2)

    def test_old_api_pass_a_failure_propagates_without_pass_b(self):
        payload = self.run_scenario("old_pass_a_failure")
        self.assertEqual(payload["exception_type"], "LLMError")
        self.assertEqual(payload["client_calls"], 1)

    def test_old_api_pass_b_failure_propagates_original(self):
        payload = self.run_scenario("old_pass_b_failure")
        self.assertEqual(payload["exception_type"], "RuntimeError")
        self.assertFalse(payload["is_wrapper"])
        self.assertEqual(payload["client_calls"], 2)

    def test_empty_segments_rejected_before_schema(self):
        payload = self.run_scenario("empty_segments")
        self.assertEqual(payload["exception_type"], "ValueError")
        self.assertEqual(payload["client_calls"], 0)

    def test_missing_evidence_uses_real_schema_defaults(self):
        payload = self.run_scenario("missing_evidence")
        self.assertEqual(payload["fields_count"], 15)
        self.assertIsNone(payload["value"])
        self.assertEqual(payload["evidence_count"], 0)
        self.assertEqual(payload["status"], "absent")
        self.assertEqual(payload["extraction_class"], "ColoStructExtraction")

    def test_empty_text_segment_is_accepted_by_real_schema(self):
        payload = self.run_scenario("empty_text")
        self.assertEqual(payload["extraction_class"], "ColoStructExtraction")
        self.assertEqual(payload["fields_count"], 15)
        self.assertEqual(payload["client_calls"], 2)

    def test_invalid_segment_id_is_structurally_accepted_but_not_audited(self):
        payload = self.run_scenario("invalid_segment_id")
        self.assertEqual(payload["evidence_id"], "seg-999")
        self.assertEqual(payload["evidence_quote"], "hello")
        self.assertEqual(payload["evidence_class"], "Evidence")
        # The schema only enforces a non-empty string; existence in clean_segments
        # is the job of core.validate.audit_extraction, which was NOT run here.
        self.assertFalse(payload["audit_ran"])


if __name__ == "__main__":
    unittest.main()
