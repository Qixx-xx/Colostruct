"""S2 service tests: ASR -> adapter -> cleanup -> Pass A/B -> AGroupResult."""
from __future__ import annotations

import unittest

from core.asr import ASRConfig, ASRResult, ASRSegment
from core.asr_adapter import ASRIntegrationError, NoSpeechError
from core.llm.client import LLMError
from core.llm.service import (
    AGroupPipelineError,
    extract_clinical_info,
    extract_clinical_info_result,
)
from core.pathology_schema import (
    PATHOLOGY_FIELD_KEYS,
    ColoStructExtraction,
    OverrideLog,
)


def segments():
    return [
        {"segment_id": "seg-001", "start": 0.0, "end": 1.0, "text": " hello"},
        {"segment_id": "seg-002", "start": 1.0, "end": 2.0, "text": " world"},
    ]


def asr_segments(values=None):
    values = values or segments()
    return [
        ASRSegment(
            segment_id=item["segment_id"],
            start=item["start"],
            end=item["end"],
            text=item["text"],
        )
        for item in values
    ]


def asr_result(status="success", error_code=None, values=None, warnings=None):
    return ASRResult(
        status=status,
        error_code=error_code,
        segments=asr_segments(values),
        warnings=warnings or [],
        model="base",
        config=ASRConfig(),
        elapsed_seconds=0.1,
    )


def pass_a_response(items=None, corrected=None, overrides=None):
    items = items or segments()
    corrected = corrected or {}
    return {
        "corrected_segments": [
            {
                "segment_id": item["segment_id"],
                "corrected_text": corrected.get(item["segment_id"], item["text"]),
            }
            for item in items
        ],
        "override_logs": overrides or [],
    }


def pass_b_response(segment_id="seg-001", quote="hello"):
    fields = {key: {"value": None, "evidence": []} for key in PATHOLOGY_FIELD_KEYS}
    fields["tumour_site"] = {
        "value": "rectum",
        "evidence": [{"segment_id": segment_id, "quote": quote}],
    }
    return {"fields": fields}


class FakeEngine:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def transcribe(self, audio_path):
        self.calls += 1
        return self.result


class RecordingCleaner:
    def __init__(self):
        self.calls = []

    def __call__(self, items):
        self.calls.append(items)
        return [dict(item) for item in items]


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


class ServiceResultTests(unittest.TestCase):
    def test_full_chain_builds_all_five_parts(self):
        cleaner = RecordingCleaner()
        client = FakeClient(
            [
                pass_a_response(
                    corrected={"seg-001": " hi", "seg-002": " there"},
                    overrides=[
                        {
                            "field_name": "tumour_site",
                            "old_evidence": {"segment_id": "seg-001", "quote": "hello"},
                            "new_evidence": {"segment_id": "seg-002", "quote": "world"},
                        }
                    ],
                ),
                pass_b_response(),
            ]
        )
        engine = FakeEngine(asr_result())
        result = extract_clinical_info_result(
            audio_path="case.wav",
            asr_engine=engine,
            cleaner=cleaner,
            client=client,
        )

        self.assertEqual(
            set(result.model_dump().keys()),
            {"extraction", "pass_a_result", "field_uncertainties", "diagnostics", "schema_version"},
        )
        self.assertEqual(result.schema_version, "a_group_result/v1")
        self.assertEqual(engine.calls, 1)
        self.assertEqual(len(cleaner.calls), 1)
        self.assertTrue(all(isinstance(item, dict) for item in cleaner.calls[0]))
        self.assertEqual(result.extraction.fields["tumour_site"].value, "rectum")

        self.assertEqual(result.pass_a_result.status, "success")
        # P2's PassASegment strips surrounding whitespace; the raw ASR text is
        # checked at the adapter/cleaner boundary instead.
        self.assertEqual(result.pass_a_result.segments[0].original_text.strip(), "hello")
        self.assertEqual(result.pass_a_result.segments[0].corrected_text.strip(), "hi")
        self.assertEqual(cleaner.calls[0][0]["text"], " hello")

        self.assertEqual([stage.stage for stage in result.diagnostics.stages], ["pass_a", "pass_b"])
        self.assertEqual([stage.status for stage in result.diagnostics.stages], ["success", "success"])
        self.assertEqual(result.field_uncertainties, {})

    def test_pass_b_receives_complete_original_clean_segments(self):
        client = FakeClient(
            [
                pass_a_response(corrected={"seg-001": " hi", "seg-002": " there"}),
                pass_b_response(),
            ]
        )
        extract_clinical_info_result(
            audio_path="case.wav",
            asr_engine=FakeEngine(asr_result()),
            cleaner=RecordingCleaner(),
            client=client,
        )
        pass_b_prompt = client.calls[1]["user"]
        self.assertIn("original_clean_asr_segments", pass_b_prompt)
        self.assertIn(" hello", pass_b_prompt)
        self.assertIn(" world", pass_b_prompt)
        self.assertIn(" hi", pass_b_prompt)
        self.assertIn(" there", pass_b_prompt)

    def test_override_logs_are_converted_to_backend_objects(self):
        client = FakeClient(
            [
                pass_a_response(
                    overrides=[
                        {
                            "field_name": "tumour_site",
                            "old_evidence": {"segment_id": "seg-001", "quote": "hello"},
                            "new_evidence": {"segment_id": "seg-002", "quote": "world"},
                        }
                    ]
                ),
                pass_b_response(),
            ]
        )
        result = extract_clinical_info_result(
            audio_path="case.wav",
            asr_engine=FakeEngine(asr_result()),
            cleaner=RecordingCleaner(),
            client=client,
        )
        logs = result.extraction.override_logs
        self.assertEqual(len(logs), 1)
        self.assertIsInstance(logs[0], OverrideLog)
        self.assertEqual(logs[0].field_name, "tumour_site")
        self.assertEqual(logs[0].old_evidence.segment_id, "seg-001")
        self.assertEqual(logs[0].old_evidence.quote, "hello")
        self.assertEqual(logs[0].new_evidence.segment_id, "seg-002")
        self.assertEqual(logs[0].new_evidence.quote, "world")

    def test_old_entry_returns_extraction_and_keeps_overrides(self):
        client = FakeClient(
            [
                pass_a_response(
                    overrides=[
                        {
                            "field_name": "tumour_site",
                            "old_evidence": {"segment_id": "seg-001", "quote": "hello"},
                            "new_evidence": {"segment_id": "seg-002", "quote": "world"},
                        }
                    ]
                ),
                pass_b_response(),
            ]
        )
        extraction = extract_clinical_info(segments(), client=client)
        self.assertIsInstance(extraction, ColoStructExtraction)
        self.assertEqual(len(extraction.override_logs), 1)
        self.assertIsInstance(extraction.override_logs[0], OverrideLog)

    def test_pass_a_failure_is_recorded_and_pass_b_runs(self):
        client = FakeClient([LLMError("pass a down"), pass_b_response()])
        result = extract_clinical_info_result(
            audio_path="case.wav",
            asr_engine=FakeEngine(asr_result()),
            cleaner=RecordingCleaner(),
            client=client,
        )
        stages = {stage.stage: stage for stage in result.diagnostics.stages}
        self.assertEqual(stages["pass_a"].status, "failed")
        self.assertEqual(stages["pass_a"].error_code, "PASS_A_FAILED")
        self.assertEqual(stages["pass_b"].status, "success")
        self.assertEqual(result.pass_a_result.status, "failed")
        self.assertEqual(result.pass_a_result.segments[0].corrected_text.strip(), "hello")
        self.assertEqual(len(client.calls), 2)
        self.assertTrue(result.has_failed_stage)
        pass_b_prompt = client.calls[1]["user"]
        self.assertIn("original_clean_asr_segments", pass_b_prompt)
        self.assertIn(" hello", pass_b_prompt)
        self.assertIn(" world", pass_b_prompt)

    def test_skip_pass_a_is_recorded(self):
        client = FakeClient([pass_b_response()])
        result = extract_clinical_info_result(
            audio_path="case.wav",
            asr_engine=FakeEngine(asr_result()),
            cleaner=RecordingCleaner(),
            client=client,
            skip_pass_a=True,
        )
        stages = {stage.stage: stage for stage in result.diagnostics.stages}
        self.assertEqual(stages["pass_a"].status, "skipped")
        self.assertEqual(result.pass_a_result.status, "skipped")
        self.assertTrue(result.pass_a_result.skip_reason)
        self.assertEqual(len(client.calls), 1)
        self.assertIn("original_clean_asr_segments", client.calls[0]["user"])

    def test_pass_b_failure_raises_with_diagnostics(self):
        client = FakeClient([pass_a_response(), LLMError("pass b down")])
        with self.assertRaises(AGroupPipelineError) as caught:
            extract_clinical_info_result(
                audio_path="case.wav",
                asr_engine=FakeEngine(asr_result()),
                cleaner=RecordingCleaner(),
                client=client,
            )
        self.assertEqual(caught.exception.stage, "pass_b")
        statuses = {stage.stage: stage.status for stage in caught.exception.diagnostics.stages}
        self.assertEqual(statuses["pass_a"], "success")
        self.assertEqual(statuses["pass_b"], "failed")

    def test_asr_failed_blocks_before_llm(self):
        client = FakeClient([])
        with self.assertRaises(ASRIntegrationError):
            extract_clinical_info_result(
                audio_path="case.wav",
                asr_engine=FakeEngine(
                    ASRResult(
                        status="failed",
                        error_code="DECODE_ERROR",
                        segments=[],
                        model="base",
                        config=ASRConfig(),
                        elapsed_seconds=0.1,
                    )
                ),
                cleaner=RecordingCleaner(),
                client=client,
            )
        self.assertEqual(client.calls, [])

    def test_no_speech_blocks_before_llm(self):
        client = FakeClient([])
        with self.assertRaises(NoSpeechError):
            extract_clinical_info_result(
                audio_path="case.wav",
                asr_engine=FakeEngine(
                    ASRResult(
                        status="partial",
                        error_code="NO_SPEECH",
                        segments=[],
                        model="base",
                        config=ASRConfig(),
                        elapsed_seconds=0.1,
                    )
                ),
                cleaner=RecordingCleaner(),
                client=client,
            )
        self.assertEqual(client.calls, [])

    def test_partial_with_segments_continues(self):
        client = FakeClient([pass_a_response(), pass_b_response()])
        result = extract_clinical_info_result(
            audio_path="case.wav",
            asr_engine=FakeEngine(
                asr_result(
                    status="partial",
                    error_code="PARTIAL_TRANSCRIPT",
                    warnings=["dropped raw segment 9: end < start"],
                )
            ),
            cleaner=RecordingCleaner(),
            client=client,
        )
        self.assertEqual(result.extraction.fields["tumour_site"].value, "rectum")
        self.assertEqual(len(client.calls), 2)

    def test_requires_exactly_one_input(self):
        with self.assertRaises(ValueError):
            extract_clinical_info_result()
        with self.assertRaises(ValueError):
            extract_clinical_info_result(audio_path="a.wav", clean_segments=segments())



    def test_new_api_pass_a_type_error_propagates(self):
        client = FakeClient([TypeError("programming bug")])
        with self.assertRaises(TypeError):
            extract_clinical_info_result(
                audio_path="case.wav",
                asr_engine=FakeEngine(asr_result()),
                cleaner=RecordingCleaner(),
                client=client,
            )
        self.assertEqual(len(client.calls), 1)

    def test_new_api_pass_a_value_error_propagates(self):
        client = FakeClient([ValueError("bad input")])
        with self.assertRaises(ValueError):
            extract_clinical_info_result(
                audio_path="case.wav",
                asr_engine=FakeEngine(asr_result()),
                cleaner=RecordingCleaner(),
                client=client,
            )
        self.assertEqual(len(client.calls), 1)

    def test_old_entry_pass_a_failure_raises_and_skips_pass_b(self):
        client = FakeClient([LLMError("pass a down")])
        with self.assertRaises(LLMError):
            extract_clinical_info(segments(), client=client)
        self.assertEqual(len(client.calls), 1)

    def test_old_entry_pass_b_failure_reraises_original_exception(self):
        client = FakeClient([pass_a_response(), LLMError("pass b down")])
        with self.assertRaises(LLMError):
            extract_clinical_info(segments(), client=client)
        self.assertEqual(len(client.calls), 2)

    def test_old_entry_pass_b_unexpected_exception_reraises_original(self):
        client = FakeClient([pass_a_response(), RuntimeError("unexpected")])
        with self.assertRaises(RuntimeError) as caught:
            extract_clinical_info(segments(), client=client)
        self.assertNotIsInstance(caught.exception, AGroupPipelineError)

if __name__ == "__main__":
    unittest.main()
