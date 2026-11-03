"""S1 adapter tests: ASRResult -> backend clean-segment dictionaries."""
from __future__ import annotations

import unittest

from core.asr import ASRConfig, ASRResult, ASRSegment
from core.asr_adapter import (
    AdaptedASR,
    ASRIntegrationError,
    NoSpeechError,
    adapt_asr_result,
)


def make_result(
    status="success",
    segments=None,
    error_code=None,
    warnings=None,
    run_metadata=None,
):
    return ASRResult(
        status=status,
        error_code=error_code,
        segments=segments
        if segments is not None
        else [ASRSegment(segment_id="seg-001", start=0.0, end=1.5, text=" hello")],
        warnings=warnings or [],
        model="base",
        config=ASRConfig(),
        elapsed_seconds=0.2,
        run_metadata=run_metadata if run_metadata is not None else {"audio_sha256": "abc"},
    )


class ASRAdapterTests(unittest.TestCase):
    def test_success_converts_to_plain_dicts(self):
        adapted = adapt_asr_result(make_result())
        self.assertIsInstance(adapted, AdaptedASR)
        self.assertEqual(adapted.status, "success")
        self.assertEqual(
            adapted.segments,
            [{"segment_id": "seg-001", "start": 0.0, "end": 1.5, "text": " hello"}],
        )
        self.assertIsInstance(adapted.segments[0], dict)

    def test_partial_with_segments_is_allowed_and_status_preserved(self):
        result = make_result(
            status="partial",
            error_code="PARTIAL_TRANSCRIPT",
            warnings=["dropped raw segment 1: end < start"],
            segments=[
                ASRSegment(segment_id="seg-001", start=0.0, end=1.0, text=" kept"),
                ASRSegment(segment_id="seg-002", start=1.0, end=2.0, text=" also"),
            ],
        )
        adapted = adapt_asr_result(result)
        self.assertEqual(adapted.status, "partial")
        self.assertEqual(adapted.error_code, "PARTIAL_TRANSCRIPT")
        self.assertEqual(adapted.warnings, ["dropped raw segment 1: end < start"])
        self.assertEqual(len(adapted.segments), 2)

    def test_partial_without_usable_speech_raises_no_speech(self):
        result = make_result(status="partial", error_code="NO_SPEECH", segments=[])
        with self.assertRaises(NoSpeechError) as caught:
            adapt_asr_result(result)
        self.assertEqual(caught.exception.status, "partial")
        self.assertEqual(caught.exception.error_code, "NO_SPEECH")
        self.assertEqual(caught.exception.warnings, [])

    def test_all_empty_text_raises_no_speech(self):
        result = make_result(
            status="partial",
            error_code="NO_SPEECH",
            segments=[ASRSegment(segment_id="seg-001", start=0.0, end=1.0, text="   ")],
        )
        with self.assertRaises(NoSpeechError):
            adapt_asr_result(result)

    def test_failed_raises_integration_error(self):
        result = make_result(
            status="failed",
            error_code="DECODE_ERROR",
            segments=[],
            warnings=["decode failed"],
        )
        with self.assertRaises(ASRIntegrationError) as caught:
            adapt_asr_result(result)
        self.assertIsInstance(caught.exception, ASRIntegrationError)
        self.assertEqual(caught.exception.status, "failed")
        self.assertEqual(caught.exception.error_code, "DECODE_ERROR")
        self.assertEqual(caught.exception.warnings, ["decode failed"])

    def test_text_ids_and_timestamps_are_preserved_verbatim(self):
        result = make_result(
            segments=[
                ASRSegment(
                    segment_id="seg-007",
                    start=3.25,
                    end=4.75,
                    text="  原始 text, 不改写  ",
                )
            ]
        )
        adapted = adapt_asr_result(result)
        self.assertEqual(adapted.segments[0]["segment_id"], "seg-007")
        self.assertEqual(adapted.segments[0]["text"], "  原始 text, 不改写  ")
        self.assertEqual(adapted.segments[0]["start"], 3.25)
        self.assertEqual(adapted.segments[0]["end"], 4.75)

    def test_no_segments_are_fabricated(self):
        result = make_result(
            segments=[
                ASRSegment(segment_id="seg-001", start=0.0, end=1.0, text=" a"),
                ASRSegment(segment_id="seg-002", start=1.0, end=2.0, text=" b"),
            ]
        )
        adapted = adapt_asr_result(result)
        self.assertEqual(len(adapted.segments), len(result.segments))
        self.assertEqual(
            [segment["segment_id"] for segment in adapted.segments],
            ["seg-001", "seg-002"],
        )

    def test_run_metadata_and_warnings_survive(self):
        result = make_result(
            warnings=["w1"],
            run_metadata={"audio_sha256": "deadbeef", "model_size": "base"},
        )
        adapted = adapt_asr_result(result)
        self.assertEqual(adapted.run_metadata["audio_sha256"], "deadbeef")
        self.assertEqual(adapted.warnings, ["w1"])


if __name__ == "__main__":
    unittest.main()
