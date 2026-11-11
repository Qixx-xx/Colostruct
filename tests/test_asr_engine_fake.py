"""ASR engine tests with FakeBackend only (no model, no network)."""
from __future__ import annotations

import os
import tempfile
import unittest

import inspect

from pydantic import ValidationError

from core.asr import (
    ASRBackend,
    ASRConfig,
    ASREngine,
    ASRResult,
    ASRSegment,
    DecodeError,
    InferenceError,
    InvalidBackendOutputError,
    ModelLoadError,
    UnsupportedFormatError,
    _FasterWhisperBackend,
)
from tests.fake_asr_backend import FakeBackend


class ASREngineFakeTests(unittest.TestCase):
    def make_audio(self, data=b"x"):
        handle, path = tempfile.mkstemp(suffix=".wav")
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return path

    def make_engine(self, **kwargs):
        backend = FakeBackend(**kwargs)
        return ASREngine(backend=backend), backend

    def test_normal_transcription_success(self):
        path = self.make_audio()
        engine, _ = self.make_engine()
        result = engine.transcribe(path)
        self.assertEqual(result.status, "success")
        self.assertIsNone(result.error_code)
        self.assertEqual([s.segment_id for s in result.segments], ["seg-001", "seg-002"])
        self.assertEqual(result.segments[0].text, " hello")  # raw text untouched
        self.assertEqual(result.segments[0].start, 0.0)
        self.assertEqual(result.segments[1].end, 4.0)
        self.assertEqual(result.schema_version, "asr_result/v1")

    def test_empty_text_segment_is_kept(self):
        path = self.make_audio()
        engine, _ = self.make_engine(
            segments=[
                {"start": 0.0, "end": 1.0, "text": ""},
                {"start": 1.0, "end": 2.0, "text": " ok"},
            ]
        )
        result = engine.transcribe(path)
        self.assertEqual(result.status, "success")
        self.assertEqual(len(result.segments), 2)
        self.assertEqual(result.segments[0].text, "")

    def test_all_empty_text_is_no_speech(self):
        path = self.make_audio()
        engine, _ = self.make_engine(
            segments=[{"start": 0.0, "end": 1.0, "text": "  "}]
        )
        result = engine.transcribe(path)
        self.assertEqual(result.status, "partial")
        self.assertEqual(result.error_code, "NO_SPEECH")

    def test_zero_segments_is_no_speech(self):
        path = self.make_audio()
        engine, _ = self.make_engine(segments=[])
        result = engine.transcribe(path)
        self.assertEqual(result.status, "partial")
        self.assertEqual(result.error_code, "NO_SPEECH")
        self.assertEqual(result.segments, [])

    def test_some_invalid_timestamps_is_partial(self):
        path = self.make_audio()
        engine, _ = self.make_engine(
            segments=[
                {"start": 0.0, "end": 1.0, "text": " good"},
                {"start": 2.0, "end": 1.0, "text": " bad"},
            ]
        )
        result = engine.transcribe(path)
        self.assertEqual(result.status, "partial")
        self.assertEqual(result.error_code, "PARTIAL_TRANSCRIPT")
        self.assertEqual(len(result.segments), 1)
        self.assertEqual(result.segments[0].segment_id, "seg-001")
        self.assertTrue(any("dropped" in warning for warning in result.warnings))

    def test_all_invalid_timestamps_is_failed(self):
        path = self.make_audio()
        engine, _ = self.make_engine(
            segments=[{"start": 2.0, "end": 1.0, "text": " bad"}]
        )
        result = engine.transcribe(path)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_code, "INVALID_BACKEND_OUTPUT")
        self.assertEqual(result.segments, [])

    def test_nan_timestamps_are_rejected(self):
        path = self.make_audio()
        engine, _ = self.make_engine(
            segments=[
                {"start": float("nan"), "end": 1.0, "text": " a"},
                {"start": 1.0, "end": 2.0, "text": " b"},
            ]
        )
        result = engine.transcribe(path)
        self.assertEqual(result.status, "partial")
        self.assertEqual(result.error_code, "PARTIAL_TRANSCRIPT")
        self.assertEqual(len(result.segments), 1)

        engine2, _ = self.make_engine(
            segments=[{"start": 0.0, "end": float("inf"), "text": " a"}]
        )
        result2 = engine2.transcribe(path)
        self.assertEqual(result2.status, "failed")
        self.assertEqual(result2.error_code, "INVALID_BACKEND_OUTPUT")

    def test_model_load_failure_is_cached(self):
        path = self.make_audio()
        engine, backend = self.make_engine(load_error=ModelLoadError("boom"))
        first = engine.transcribe(path)
        second = engine.transcribe(path)
        self.assertEqual(first.status, "failed")
        self.assertEqual(first.error_code, "MODEL_LOAD_FAILED")
        self.assertEqual(second.error_code, "MODEL_LOAD_FAILED")
        self.assertEqual(backend.load_calls, 1)
        self.assertEqual(backend.transcribe_calls, 0)

    def test_inference_failure(self):
        path = self.make_audio()
        engine, _ = self.make_engine(transcribe_error=InferenceError("crash"))
        result = engine.transcribe(path)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_code, "INFERENCE_ERROR")

    def test_backend_error_message_is_preserved(self):
        path = self.make_audio()
        engine, _ = self.make_engine(
            transcribe_error=InvalidBackendOutputError(
                "Whisper timestamp lies outside the provisional chunk range"
            )
        )
        result = engine.transcribe(path)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_code, "INVALID_BACKEND_OUTPUT")
        self.assertIn("InvalidBackendOutputError", result.error or "")
        self.assertIn("timestamp lies outside", result.error or "")
        self.assertNotIn(path, result.error or "")

    def test_duration_far_from_last_end_is_not_partial(self):
        path = self.make_audio()
        engine, _ = self.make_engine(duration=100.0)
        result = engine.transcribe(path)
        self.assertEqual(result.status, "success")
        self.assertIsNone(result.error_code)
        self.assertEqual(result.duration, 100.0)

    def test_non_finite_duration_is_sanitized_without_changing_status(self):
        path = self.make_audio()
        engine, _ = self.make_engine(duration=float("nan"), language_probability=float("nan"))
        result = engine.transcribe(path)
        # duration is metadata only: it is sanitised, never treated as a real value,
        # and never changes the transcript status.
        self.assertEqual(result.status, "success")
        self.assertIsNone(result.duration)
        self.assertIsNone(result.language_probability)
        self.assertTrue(any("duration" in warning for warning in result.warnings))

    def test_zero_duration_does_not_change_status(self):
        path = self.make_audio()
        engine, _ = self.make_engine(duration=0.0)
        result = engine.transcribe(path)
        self.assertEqual(result.status, "success")
        self.assertEqual(result.duration, 0.0)

    def test_missing_duration_does_not_change_status(self):
        path = self.make_audio()
        engine, _ = self.make_engine(duration=None)
        result = engine.transcribe(path)
        self.assertEqual(result.status, "success")
        self.assertIsNone(result.duration)

    def test_unsupported_format_maps_to_failed_code(self):
        path = self.make_audio()
        engine, _ = self.make_engine(transcribe_error=UnsupportedFormatError("bad container"))
        result = engine.transcribe(path)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_code, "UNSUPPORTED_FORMAT")
        self.assertEqual(result.segments, [])

    def test_decode_error_maps_to_failed_code(self):
        path = self.make_audio()
        engine, _ = self.make_engine(transcribe_error=DecodeError("bad stream"))
        result = engine.transcribe(path)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_code, "DECODE_ERROR")
        self.assertEqual(result.segments, [])

    def test_error_message_does_not_leak_audio_path(self):
        path = self.make_audio()
        engine, _ = self.make_engine(transcribe_error=DecodeError(f"failed on {path}"))
        result = engine.transcribe(path)
        self.assertEqual(result.error_code, "DECODE_ERROR")
        self.assertNotIn(path, result.error or "")
        self.assertNotIn(os.path.basename(path), result.error or "")

    def test_failed_result_rejects_non_empty_segments(self):
        with self.assertRaises(ValidationError):
            ASRResult(
                status="failed",
                error_code="DECODE_ERROR",
                segments=[ASRSegment(segment_id="seg-001", start=0.0, end=1.0, text="x")],
                model="base",
                config=ASRConfig(),
                elapsed_seconds=0.0,
            )

    def test_failed_result_without_segments_is_valid(self):
        result = ASRResult(
            status="failed",
            error_code="DECODE_ERROR",
            segments=[],
            model="base",
            config=ASRConfig(),
            elapsed_seconds=0.0,
        )
        self.assertEqual(result.segments, [])

    def test_backend_load_signatures_match_protocol(self):
        expected = ["self", "config"]
        self.assertEqual(list(inspect.signature(ASRBackend.load).parameters), expected)
        self.assertEqual(list(inspect.signature(FakeBackend.load).parameters), expected)
        self.assertEqual(list(inspect.signature(_FasterWhisperBackend.load).parameters), expected)

    def test_segment_ids_unique_and_well_formed(self):
        path = self.make_audio()
        engine, _ = self.make_engine(
            segments=[
                {"start": 0.0, "end": 1.0, "text": " a"},
                {"start": 1.0, "end": 2.0, "text": " b"},
                {"start": 2.0, "end": 3.0, "text": " c"},
            ]
        )
        result = engine.transcribe(path)
        ids = [segment.segment_id for segment in result.segments]
        self.assertEqual(ids, ["seg-001", "seg-002", "seg-003"])
        self.assertEqual(len(ids), len(set(ids)))
        for segment_id in ids:
            self.assertRegex(segment_id, r"^seg-\d{3,}$")

    def test_model_is_loaded_once_and_reused(self):
        path = self.make_audio()
        engine, backend = self.make_engine()
        engine.transcribe(path)
        engine.transcribe(path)
        self.assertEqual(backend.load_calls, 1)
        self.assertEqual(backend.transcribe_calls, 2)

    def test_missing_file_does_not_load_model(self):
        engine, backend = self.make_engine()
        result = engine.transcribe(os.path.join(tempfile.gettempdir(), "no-such-audio-xyz.wav"))
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_code, "AUDIO_NOT_FOUND")
        self.assertEqual(backend.load_calls, 0)

    def test_empty_file_does_not_load_model(self):
        path = self.make_audio(data=b"")
        engine, backend = self.make_engine()
        result = engine.transcribe(path)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_code, "EMPTY_AUDIO")
        self.assertEqual(backend.load_calls, 0)

    def test_non_list_segments_is_invalid_backend_output(self):
        path = self.make_audio()
        engine, _ = self.make_engine(segments="not-a-list")
        result = engine.transcribe(path)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_code, "INVALID_BACKEND_OUTPUT")



    def test_model_load_failure_error_does_not_leak_audio_path(self):
        path = self.make_audio()
        engine, _ = self.make_engine(load_error=ModelLoadError(f"cannot load for {path}"))
        result = engine.transcribe(path)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_code, "MODEL_LOAD_FAILED")
        self.assertNotIn(path, result.error or "")
        self.assertNotIn(os.path.basename(path), result.error or "")

    def test_success_allows_non_empty_segments(self):
        result = ASRResult(
            status="success",
            segments=[ASRSegment(segment_id="seg-001", start=0.0, end=1.0, text=" ok")],
            model="base",
            config=ASRConfig(),
            elapsed_seconds=0.0,
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(len(result.segments), 1)

    def test_partial_allows_non_empty_segments(self):
        result = ASRResult(
            status="partial",
            error_code="PARTIAL_TRANSCRIPT",
            segments=[ASRSegment(segment_id="seg-001", start=0.0, end=1.0, text=" ok")],
            model="base",
            config=ASRConfig(),
            elapsed_seconds=0.0,
        )
        self.assertEqual(result.status, "partial")
        self.assertEqual(len(result.segments), 1)

if __name__ == "__main__":
    unittest.main()
