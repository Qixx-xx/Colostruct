"""Contract tests for core.asr (no model, no audio decoding)."""
from __future__ import annotations

import math
import unittest

from pydantic import ValidationError

from core.asr import ASRConfig, ASREngine, ASRResult, ASRSegment


def make_result(**overrides):
    payload = {
        "status": "success",
        "segments": [ASRSegment(segment_id="seg-001", start=0.0, end=1.0, text=" text")],
        "model": "base",
        "config": ASRConfig(),
        "elapsed_seconds": 0.1,
    }
    payload.update(overrides)
    return ASRResult(**payload)


class ASRConfigTests(unittest.TestCase):
    def test_defaults_are_the_confirmed_initial_values(self):
        config = ASRConfig()
        self.assertEqual(
            config.model_dump(),
            {
                "model_size": "base",
                "device": "cpu",
                "compute_type": "int8",
                "beam_size": 5,
                "vad_filter": True,
                "condition_on_previous_text": False,
                "language": None,
                "initial_prompt": None,
                "word_timestamps": False,
                "cpu_threads": None,
            },
        )

    def test_invalid_beam_size_rejected(self):
        with self.assertRaises(ValidationError):
            ASRConfig(beam_size=0)

    def test_invalid_device_rejected(self):
        with self.assertRaises(ValidationError):
            ASRConfig(device="tpu")

    def test_unknown_key_rejected(self):
        with self.assertRaises(ValidationError):
            ASRConfig(unknown_key=1)


class ASRSegmentTests(unittest.TestCase):
    def test_valid_id_format(self):
        self.assertEqual(
            ASRSegment(segment_id="seg-001", start=0.0, end=1.0, text="x").segment_id,
            "seg-001",
        )
        self.assertEqual(
            ASRSegment(segment_id="seg-1000", start=0.0, end=1.0, text="x").segment_id,
            "seg-1000",
        )

    def test_invalid_id_formats_rejected(self):
        for bad in ("seg-01", "segment-001", "seg-1", "001", "seg-abc"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):
                    ASRSegment(segment_id=bad, start=0.0, end=1.0, text="x")

    def test_negative_start_rejected(self):
        with self.assertRaises(ValidationError):
            ASRSegment(segment_id="seg-001", start=-0.1, end=1.0, text="x")

    def test_end_before_start_rejected(self):
        with self.assertRaises(ValidationError):
            ASRSegment(segment_id="seg-001", start=2.0, end=1.0, text="x")

    def test_nan_and_infinity_rejected(self):
        for bad in (math.nan, math.inf, -math.inf):
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):
                    ASRSegment(segment_id="seg-001", start=bad, end=1.0, text="x")
                with self.assertRaises(ValidationError):
                    ASRSegment(segment_id="seg-001", start=0.0, end=bad, text="x")

    def test_raw_text_is_preserved(self):
        segment = ASRSegment(segment_id="seg-001", start=0.0, end=1.0, text="  spaced text  ")
        self.assertEqual(segment.text, "  spaced text  ")


class ASRResultTests(unittest.TestCase):
    def test_schema_version_default(self):
        self.assertEqual(make_result().schema_version, "asr_result/v1")

    def test_invalid_schema_version_rejected(self):
        with self.assertRaises(ValidationError):
            make_result(schema_version="asr_result/v2")

    def test_success_must_not_carry_error_code(self):
        with self.assertRaises(ValidationError):
            make_result(error_code="NO_SPEECH")

    def test_success_requires_non_empty_text(self):
        with self.assertRaises(ValidationError):
            make_result(
                segments=[ASRSegment(segment_id="seg-001", start=0.0, end=1.0, text="   ")]
            )

    def test_failed_requires_error_code(self):
        with self.assertRaises(ValidationError):
            make_result(status="failed", segments=[])

    def test_partial_requires_error_code(self):
        with self.assertRaises(ValidationError):
            make_result(status="partial")

    def test_non_finite_duration_rejected(self):
        for bad in (math.nan, math.inf):
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):
                    make_result(duration=bad)

    def test_language_probability_range(self):
        with self.assertRaises(ValidationError):
            make_result(language_probability=1.5)
        with self.assertRaises(ValidationError):
            make_result(language_probability=-0.1)


class ASREngineConstructionTests(unittest.TestCase):
    def test_constructor_does_not_load_model(self):
        class BoomBackend:
            def load(self, config):
                raise AssertionError("load must be lazy")

            def transcribe(self, audio_path, config):
                raise AssertionError("unreachable")

        engine = ASREngine(backend=BoomBackend())
        self.assertEqual(engine.config.model_size, "base")


if __name__ == "__main__":
    unittest.main()
