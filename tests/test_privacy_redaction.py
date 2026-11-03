"""Privacy regression tests: synthetic markers must not reach public surfaces."""
from __future__ import annotations

import io
import logging
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from core.asr import (
    ASRConfig,
    ASREngine,
    ASRResult,
    ASRSegment,
    ModelLoadError,
    RawTranscription,
)
from core.asr_adapter import ASRIntegrationError, adapt_asr_result
from core.llm.client import LLMError, OllamaClient
from core.llm.service import (
    AGroupPipelineError,
    extract_clinical_info,
    extract_clinical_info_result,
)
from core.pathology_schema import PATHOLOGY_FIELD_KEYS

MARK = "SYNTHETIC_SECRET_MARKER_12345"
DEV_ROOT = Path(__file__).resolve().parents[1]

SEGMENTS = [
    {"segment_id": "seg-001", "start": 0.0, "end": 1.0, "text": " hello"},
    {"segment_id": "seg-002", "start": 1.0, "end": 2.0, "text": " world"},
]


def make_fields():
    fields = {key: {"value": None, "evidence": []} for key in PATHOLOGY_FIELD_KEYS}
    fields["tumour_site"] = {
        "value": "rectum",
        "evidence": [{"segment_id": "seg-001", "quote": "hello"}],
    }
    return fields


def pass_a_response():
    return {
        "corrected_segments": [
            {"segment_id": "seg-001", "corrected_text": " hi"},
            {"segment_id": "seg-002", "corrected_text": " there"},
        ],
        "override_logs": [],
    }


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


class ReportCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


class PrivacyRedactionTests(unittest.TestCase):
    def test_pass_a_marker_not_in_diagnostics_or_logs(self):
        client = FakeClient([LLMError(MARK), {"fields": make_fields()}])
        service_logger = logging.getLogger("core.llm.service")
        capture = ReportCapture()
        service_logger.addHandler(capture)
        try:
            result = extract_clinical_info_result(clean_segments=SEGMENTS, client=client)
        finally:
            service_logger.removeHandler(capture)

        warnings = [w for stage in result.diagnostics.stages for w in stage.warnings]
        self.assertNotIn(MARK, " ".join(warnings))
        self.assertNotIn(MARK, "\n".join(capture.messages))
        statuses = {stage.stage: stage.status for stage in result.diagnostics.stages}
        self.assertEqual(statuses, {"pass_a": "failed", "pass_b": "success"})
        self.assertEqual(warnings, ["LLMError"])

    def test_pass_b_marker_not_in_exception_or_diagnostics(self):
        client = FakeClient([pass_a_response(), RuntimeError(MARK)])
        with self.assertRaises(AGroupPipelineError) as caught:
            extract_clinical_info_result(clean_segments=SEGMENTS, client=client)
        exc = caught.exception
        self.assertNotIn(MARK, str(exc))
        self.assertNotIn(MARK, repr(exc))
        warnings = [w for stage in exc.diagnostics.stages for w in stage.warnings]
        self.assertNotIn(MARK, " ".join(warnings))
        self.assertEqual(exc.stage, "pass_b")
        self.assertEqual(exc.cause_type, "RuntimeError")
        self.assertIsNone(exc.__cause__)
        self.assertIsNone(exc.__context__)
        self.assertFalse(hasattr(exc, "cause"))
        self.assertFalse(hasattr(exc, "_AGroupPipelineError__original"))
        self.assertNotIn("_AGroupPipelineError__original", exc.__dict__)
        self.assertNotIn(MARK, repr(exc.__dict__))
        self.assertNotIn(MARK, str(exc.__dict__))

    def test_http_error_body_not_in_llm_error(self):
        def fake_urlopen(request, timeout=None):
            raise HTTPError(
                request.full_url,
                500,
                "server error",
                {},
                io.BytesIO(("body " + MARK).encode("utf-8")),
            )

        with patch("core.llm.client.urlopen", fake_urlopen):
            with self.assertRaises(LLMError) as caught:
                OllamaClient().generate_json(system="system", user="user")
        self.assertNotIn(MARK, str(caught.exception))
        self.assertIn("500", str(caught.exception))

    def test_asr_invalid_timestamp_marker_not_in_warnings(self):
        class BadSegmentBackend:
            def load(self, config):
                return None

            def transcribe(self, audio_path, config):
                return RawTranscription(
                    segments=[{"start": MARK, "end": 1.0, "text": "x"}]
                )

        result = ASREngine(ASRConfig(), backend=BadSegmentBackend()).transcribe(
            str(DEV_ROOT / "A_GROUP_README.md")
        )
        self.assertNotIn(MARK, " ".join(result.warnings))
        self.assertTrue(any("dropped" in warning for warning in result.warnings))
        self.assertEqual(result.error_code, "INVALID_BACKEND_OUTPUT")

    def test_asr_backend_exception_marker_not_in_error(self):
        class BadBackend:
            def load(self, config):
                return None

            def transcribe(self, audio_path, config):
                raise RuntimeError(MARK)

        result = ASREngine(ASRConfig(), backend=BadBackend()).transcribe(
            str(DEV_ROOT / "A_GROUP_README.md")
        )
        self.assertNotIn(MARK, result.error or "")
        self.assertNotIn(MARK, " ".join(result.warnings))
        self.assertEqual(result.error_code, "INFERENCE_ERROR")

    def test_asr_model_load_marker_not_in_error(self):
        class LoadFailBackend:
            def load(self, config):
                raise ModelLoadError(MARK)

            def transcribe(self, audio_path, config):
                raise AssertionError("unreachable")

        result = ASREngine(ASRConfig(), backend=LoadFailBackend()).transcribe(
            str(DEV_ROOT / "A_GROUP_README.md")
        )
        self.assertNotIn(MARK, result.error or "")
        self.assertEqual(result.error_code, "MODEL_LOAD_FAILED")

    def test_adapter_exception_exposes_only_safe_fields(self):
        class BadBackend:
            def load(self, config):
                return None

            def transcribe(self, audio_path, config):
                raise RuntimeError(MARK)

        result = ASREngine(ASRConfig(), backend=BadBackend()).transcribe(
            str(DEV_ROOT / "A_GROUP_README.md")
        )
        with self.assertRaises(ASRIntegrationError) as caught:
            adapt_asr_result(result)
        exc = caught.exception
        self.assertFalse(hasattr(exc, "asr_result"))
        self.assertFalse(hasattr(exc, "error"))
        self.assertNotIn(MARK, str(exc))
        self.assertEqual(exc.status, "failed")
        self.assertEqual(exc.error_code, "INFERENCE_ERROR")



    def test_adapter_drops_unknown_warnings_from_exception(self):
        result = ASRResult(
            status="failed",
            error_code="DECODE_ERROR",
            error="decode failed",
            warnings=[MARK, "dropped raw segment 1: end < start"],
            model="base",
            config=ASRConfig(),
            elapsed_seconds=0.1,
        )
        with self.assertRaises(ASRIntegrationError) as caught:
            adapt_asr_result(result)
        exc = caught.exception
        self.assertNotIn(MARK, " ".join(exc.warnings))
        self.assertEqual(exc.status, "failed")
        self.assertEqual(exc.error_code, "DECODE_ERROR")
        self.assertFalse(hasattr(exc, "asr_result"))
        self.assertFalse(hasattr(exc, "error"))

    def test_old_api_still_raises_original_exception(self):
        # Historical compatibility: the old entry deliberately re-raises the
        # original exception object, including its text; this is documented and
        # must not be used as the new API's diagnostics path.
        client = FakeClient([pass_a_response(), RuntimeError(MARK)])
        with self.assertRaises(RuntimeError) as caught:
            extract_clinical_info(SEGMENTS, client=client)
        self.assertNotIsInstance(caught.exception, AGroupPipelineError)
        self.assertIn(MARK, str(caught.exception))


    def test_normal_adapter_uses_same_warning_allowlist(self):
        result = ASRResult(
            status="success",
            segments=[ASRSegment(segment_id="seg-001", start=0.0, end=1.0, text="hello")],
            warnings=[MARK, "dropped non-finite duration"],
            model="base",
            config=ASRConfig(),
            elapsed_seconds=0.1,
        )
        adapted = adapt_asr_result(result)
        self.assertNotIn(MARK, " ".join(adapted.warnings))
        self.assertIn("dropped non-finite duration", adapted.warnings)

    def test_normal_and_exception_warning_rules_match(self):
        warnings = [MARK, "dropped non-finite duration"]
        normal = ASRResult(
            status="success",
            segments=[ASRSegment(segment_id="seg-001", start=0.0, end=1.0, text="hello")],
            warnings=warnings,
            model="base",
            config=ASRConfig(),
            elapsed_seconds=0.1,
        )
        adapted = adapt_asr_result(normal)

        failed = ASRResult(
            status="failed",
            error_code="DECODE_ERROR",
            warnings=warnings,
            model="base",
            config=ASRConfig(),
            elapsed_seconds=0.1,
        )
        with self.assertRaises(ASRIntegrationError) as caught:
            adapt_asr_result(failed)
        self.assertEqual(adapted.warnings, caught.exception.warnings)
        self.assertNotIn(MARK, " ".join(adapted.warnings))

if __name__ == "__main__":
    unittest.main()
