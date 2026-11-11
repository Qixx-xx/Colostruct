"""Offline tests for the Transformers Whisper backend.

No torch/transformers model is loaded here; fake factories and fake audio
decoding keep these tests fast and deterministic.
"""
from __future__ import annotations

import math
import os
import unittest
from unittest.mock import Mock, patch

from core.asr import ASRConfig, ASREngine, InferenceError, InvalidBackendOutputError
from core.asr_hf_whisper import (
    HFWhisperBackend,
    ParsedChunk,
    _transcription_window_ranges,
    _parse_timestamped_ids,
    _resolve_timestamp_begin,
)


class FakeTokenizer:
    """Timestamp range starts at 200; each 0.02 s is one token id."""

    all_special_ids = [100, 101, 199]

    def __init__(self) -> None:
        self.text = {42: "alpha", 43: "beta"}

    def decode(self, token_ids, skip_special_tokens=True):
        parts = []
        for token in token_ids:
            token = int(token)
            if skip_special_tokens and token in self.all_special_ids:
                continue
            parts.append(self.text.get(token, "text"))
        return " ".join(parts)

    def convert_tokens_to_ids(self, token):
        return 199 if token == "<|notimestamps|>" else -1


class FakeTensor:
    def __init__(self, value=None):
        self.value = value
        self.shape = (1, 80, 3000)

    def to(self, device):
        return self


class FakeInputs:
    def __init__(self):
        self.input_features = FakeTensor()
        self.attention_mask = FakeTensor()

    def __getitem__(self, key):
        return getattr(self, key)


class FakeProcessor:
    tokenizer = FakeTokenizer()

    def __call__(self, samples, sampling_rate, return_tensors):
        return FakeInputs()


class FakeGenerationConfig:
    forced_decoder_ids = [[1, 50259]]
    no_timestamps_token_id = 199


class FakeModel:
    def __init__(self, outputs=None, error=None):
        self.outputs = outputs or [[200, 42, 250]]
        self.error = error
        self.generation_config = FakeGenerationConfig()
        self.calls = 0

    def to(self, device):
        return self

    def eval(self):
        return self

    def generate(self, input_features, attention_mask=None, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return self.outputs


class FakeTorch:
    long = "long"
    float32 = "float32"

    class inference_mode:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    @staticmethod
    def ones(*args, **kwargs):
        return FakeTensor()


def timestamp_id(seconds: float) -> int:
    return 200 + int(round(seconds / 0.02))


def parse_result(
    ids,
    *,
    chunk_duration=1.0,
    total_duration=1.0,
    offset=0.0,
    no_ts=199,
    normalize=False,
):
    return _parse_timestamped_ids(
        ids,
        FakeTokenizer(),
        offset_seconds=offset,
        chunk_duration_seconds=chunk_duration,
        total_duration_seconds=total_duration,
        no_timestamps_token_id=no_ts,
        normalize_final_chunk_end=normalize,
    )


def parse(ids, **kwargs):
    return parse_result(ids, **kwargs).segments


class HFWhisperBackendTests(unittest.TestCase):
    def make_backend(self, model=None, normalize=False, chunk_length=1.0):
        model = model or FakeModel()
        backend = HFWhisperBackend(
            model_path="fake-model",
            chunk_length_s=chunk_length,
            normalize_final_chunk_end=normalize,
            _processor_factory=lambda *a, **k: FakeProcessor(),
            _model_factory=lambda *a, **k: model,
        )
        backend.load(ASRConfig())
        backend._torch = FakeTorch()
        return backend, model

    def test_short_tail_is_merged_for_73901_seconds(self):
        total_samples = int(round(73.901 * 16000))
        chunk_samples = int(round(10.0 * 16000))
        min_tail = 4 * 16000
        ranges = _transcription_window_ranges(
            total_samples, chunk_samples, min_tail
        )
        self.assertEqual(len(ranges), 7)
        self.assertEqual(ranges[0][0], 0)
        self.assertEqual(ranges[-1][1], total_samples)
        lengths = [end - start for start, end in ranges]
        self.assertEqual(lengths[:-1], [chunk_samples] * 6)
        self.assertGreaterEqual(lengths[-1], min_tail)
        self.assertLessEqual(lengths[-1], chunk_samples + min_tail)
        # Windows are contiguous and cover the audio exactly once.
        self.assertEqual(
            [start for start, _ in ranges],
            [0] + [end for _, end in ranges[:-1]],
        )
        self.assertEqual(sum(lengths), total_samples)

    def test_short_tail_rules_for_other_lengths(self):
        cases = {
            int(round(5.855 * 16000)): 1,
            int(round(10.0 * 16000)): 1,
            int(round(10.1 * 16000)): 1,
            int(round(11.0 * 16000)): 1,
            int(round(14.0 * 16000)): 2,
            int(round(20.0 * 16000)): 2,
            int(round(73.901 * 16000)): 7,
        }
        chunk_samples = int(round(10.0 * 16000))
        min_tail = 4 * 16000
        for total_samples, expected_count in cases.items():
            ranges = _transcription_window_ranges(
                total_samples, chunk_samples, min_tail
            )
            self.assertEqual(len(ranges), expected_count)
            self.assertEqual(ranges[0][0], 0)
            self.assertEqual(ranges[-1][1], total_samples)
            self.assertTrue(all(end - start > 0 for start, end in ranges))
            self.assertEqual(
                [start for start, _ in ranges],
                [0] + [end for _, end in ranges[:-1]],
            )

    def test_73901_audio_does_not_call_a_short_tail_window(self):
        backend, _ = self.make_backend(chunk_length=10.0)
        total_samples = int(round(73.901 * 16000))
        with patch(
            "core.asr_hf_whisper._decode_audio_16k_mono",
            return_value=([0.0] * total_samples, "wav", 73.901),
        ):
            result = backend.transcribe("fake.wav", ASRConfig())
        self.assertEqual(len(result.segments), 7)
        self.assertGreaterEqual(len(result.segments), 1)
        self.assertAlmostEqual(result.segments[0]["start"], 0.0)
        self.assertLessEqual(result.segments[-1]["end"], 73.901 + 1e-6)
        for segment in result.segments:
            self.assertGreaterEqual(segment["start"], 0.0)
            self.assertLessEqual(segment["start"], segment["end"])
            self.assertLessEqual(segment["end"], 73.901 + 1e-6)

    def test_model_loading_happens_once(self):
        calls = {"processor": 0, "model": 0}

        def processor_factory(*args, **kwargs):
            calls["processor"] += 1
            return FakeProcessor()

        def model_factory(*args, **kwargs):
            calls["model"] += 1
            return FakeModel()

        backend = HFWhisperBackend(
            model_path="fake-model",
            _processor_factory=processor_factory,
            _model_factory=model_factory,
        )
        backend.load(ASRConfig())
        backend.load(ASRConfig())
        self.assertEqual(calls, {"processor": 1, "model": 1})

    def test_normal_timestamp_parsing(self):
        parsed = parse_result([timestamp_id(0), 42, timestamp_id(1)])
        self.assertEqual(len(parsed.segments), 1)
        self.assertEqual(parsed.segments[0]["text"], "alpha")
        self.assertEqual(parsed.segments[0]["start"], 0.0)
        self.assertAlmostEqual(parsed.segments[0]["end"], 1.0)

    def test_empty_text_is_skipped(self):
        self.assertEqual(parse([timestamp_id(0), timestamp_id(1)]), [])

    def test_missing_timestamp_is_rejected(self):
        with self.assertRaises(InvalidBackendOutputError):
            parse([42, 43])

    def test_unclosed_trailing_text_is_rejected(self):
        with self.assertRaises(InvalidBackendOutputError):
            parse([timestamp_id(0), 42])

    def test_non_monotonic_timestamps_are_rejected(self):
        with self.assertRaises(InvalidBackendOutputError):
            parse([
                timestamp_id(0),
                42,
                timestamp_id(0.5),
                43,
                timestamp_id(0.4),
            ])

    def test_non_finite_offset_is_rejected(self):
        with self.assertRaises(InvalidBackendOutputError):
            parse(
                [timestamp_id(0), 42, timestamp_id(0.5)],
                offset=math.nan,
                total_duration=10.0,
            )

    def test_multiple_chunks_receive_offsets(self):
        backend, _ = self.make_backend()
        with patch(
            "core.asr_hf_whisper._decode_audio_16k_mono",
            return_value=([0.0] * 32000, "wav", 2.0),
        ):
            result = backend.transcribe("fake.wav", ASRConfig())
        self.assertEqual(result.duration, 2.0)
        self.assertEqual(len(result.segments), 2)
        self.assertAlmostEqual(result.segments[0]["start"], 0.0)
        self.assertAlmostEqual(result.segments[1]["start"], 1.0)
        self.assertLessEqual(result.segments[0]["end"], result.segments[1]["start"])

    def test_inference_error_is_mapped(self):
        backend, _ = self.make_backend(FakeModel(error=RuntimeError("boom")))
        with patch(
            "core.asr_hf_whisper._decode_audio_16k_mono",
            return_value=([0.0] * 16000, "wav", 1.0),
        ):
            with self.assertRaises(InferenceError):
                backend.transcribe("fake.wav", ASRConfig())

    def test_audio_decode_error_is_propagated(self):
        backend, _ = self.make_backend()
        with patch(
            "core.asr_hf_whisper._decode_audio_16k_mono",
            side_effect=InvalidBackendOutputError("bad audio"),
        ):
            with self.assertRaises(InvalidBackendOutputError):
                backend.transcribe("fake.wav", ASRConfig())

    def test_window_is_split_after_timestamp_error(self):
        backend, _ = self.make_backend()
        backend._transcribe_chunk = Mock(
            side_effect=[
                InvalidBackendOutputError("timestamp reset"),
                ParsedChunk([{"start": 0.0, "end": 1.0, "text": "left"}], []),
                ParsedChunk([{"start": 4.0, "end": 5.0, "text": "right"}], []),
            ]
        )
        result = backend._transcribe_window(
            [0.0] * (8 * 16000),
            offset_seconds=0.0,
            total_duration_seconds=8.0,
            leaf_counter=[0],
        )
        self.assertEqual([s["text"] for s in result.segments], ["left", "right"])
        self.assertEqual(backend._transcribe_chunk.call_count, 3)

    def test_empty_output_without_timestamps_is_allowed(self):
        self.assertEqual(parse([]), [])

    def test_language_yue_is_mapped_to_zh(self):
        backend = HFWhisperBackend(
            model_path="fake-model",
            _processor_factory=lambda *a, **k: FakeProcessor(),
            _model_factory=lambda *a, **k: FakeModel(),
        )
        backend.load(ASRConfig(language="yue"))
        self.assertEqual(backend._effective_language, "zh")

    # P0: local timestamps must be checked against the current chunk duration.
    def test_chunk_0_to_9_seconds_passes(self):
        segments = parse(
            [timestamp_id(0), 42, timestamp_id(9)],
            chunk_duration=10.0,
            total_duration=60.0,
        )
        self.assertAlmostEqual(segments[0]["end"], 9.0)

    def test_chunk_exact_end_is_allowed(self):
        segments = parse(
            [timestamp_id(0), 42, timestamp_id(10)],
            chunk_duration=10.0,
            total_duration=60.0,
        )
        self.assertAlmostEqual(segments[0]["end"], 10.0)

    def test_chunk_10_02_seconds_is_rejected(self):
        with self.assertRaises(InvalidBackendOutputError):
            parse(
                [timestamp_id(0), 42, timestamp_id(10.02)],
                chunk_duration=10.0,
                total_duration=60.0,
            )

    def test_chunk_20_seconds_is_rejected_even_if_total_allows(self):
        with self.assertRaises(InvalidBackendOutputError):
            parse(
                [timestamp_id(0), 42, timestamp_id(20)],
                chunk_duration=10.0,
                total_duration=60.0,
            )

    def test_last_partial_chunk_uses_its_own_duration(self):
        segments = parse(
            [timestamp_id(0), 42, timestamp_id(2.12)],
            chunk_duration=2.12,
            total_duration=12.12,
            offset=10.0,
        )
        self.assertAlmostEqual(segments[0]["start"], 10.0)
        self.assertAlmostEqual(segments[0]["end"], 12.12)

    # P1: timestamp_begin must come from explicit contract, not sorted special ids.
    def test_timestamp_begin_from_generation_config(self):
        self.assertEqual(_resolve_timestamp_begin(FakeTokenizer(), 199), 200)

    def test_timestamp_begin_from_tokenizer(self):
        self.assertEqual(_resolve_timestamp_begin(FakeTokenizer(), None), 200)

    def test_timestamp_begin_sources_agree(self):
        self.assertEqual(_resolve_timestamp_begin(FakeTokenizer(), 199), 200)

    def test_timestamp_begin_sources_disagree_is_rejected(self):
        with self.assertRaises(InvalidBackendOutputError):
            _resolve_timestamp_begin(FakeTokenizer(), 198)

    def test_timestamp_begin_sources_missing_is_rejected(self):
        class NoIds(FakeTokenizer):
            def convert_tokens_to_ids(self, token):
                return -1

        with self.assertRaises(InvalidBackendOutputError):
            _resolve_timestamp_begin(NoIds(), None)

    def test_all_special_ids_order_does_not_change_result(self):
        tokenizer = FakeTokenizer()
        tokenizer.all_special_ids = [199, 100, 101]
        self.assertEqual(_resolve_timestamp_begin(tokenizer, None), 200)

    # P1: ordinary text before the first timestamp must not be silently dropped.
    def test_special_prefix_is_allowed(self):
        parsed = parse_result([100, timestamp_id(0), 42, timestamp_id(1)])
        self.assertEqual(len(parsed.segments), 1)

    def test_ordinary_text_prefix_is_rejected(self):
        with self.assertRaises(InvalidBackendOutputError):
            parse([42, timestamp_id(0), 43, timestamp_id(1)])

    # P2: HF provenance must remove faster-whisper-specific version keys.
    def test_backend_metadata_removes_faster_whisper_keys(self):
        metadata = ASREngine()._run_metadata(
            None, None, None, "start", 1.0, 2.0,
            backend_metadata={
                "backend": "transformers_whisper",
                "model_id": "fake-model",
            },
        )
        self.assertEqual(metadata["backend"], "transformers_whisper")
        self.assertNotIn("faster_whisper_version", metadata)
        self.assertNotIn("ctranslate2_version", metadata)

    def test_default_metadata_keeps_faster_whisper_keys(self):
        metadata = ASREngine()._run_metadata(None, None, None, "start", 1.0, 2.0)
        self.assertIn("faster_whisper_version", metadata)
        self.assertIn("ctranslate2_version", metadata)

    # Normalization: empty output must be validated before returning empty.
    def test_empty_output_trailing_timestamp_5ms_over_is_rejected(self):
        with self.assertRaises(InvalidBackendOutputError):
            parse_result(
                [timestamp_id(0), timestamp_id(2.12)],
                chunk_duration=2.115,
                total_duration=2.115,
                normalize=True,
            )

    def test_empty_output_trailing_timestamp_10ms_over_is_rejected(self):
        with self.assertRaises(InvalidBackendOutputError):
            parse_result(
                [timestamp_id(0), timestamp_id(2.12)],
                chunk_duration=2.11,
                total_duration=2.11,
                normalize=True,
            )

    def test_empty_output_trailing_timestamp_15ms_over_is_rejected(self):
        with self.assertRaises(InvalidBackendOutputError):
            parse_result(
                [timestamp_id(0), timestamp_id(2.12)],
                chunk_duration=2.105,
                total_duration=2.105,
                normalize=True,
            )

    def test_empty_output_all_timestamps_within_chunk_is_allowed(self):
        parsed = parse_result(
            [timestamp_id(0), timestamp_id(2.10)],
            chunk_duration=2.115,
            total_duration=2.115,
            normalize=True,
        )
        self.assertEqual(parsed.segments, [])
        self.assertEqual(parsed.normalizations, [])

    def test_empty_output_single_overstart_timestamp_is_rejected(self):
        with self.assertRaises(InvalidBackendOutputError):
            parse_result(
                [timestamp_id(2.12)],
                chunk_duration=2.115,
                total_duration=2.115,
                normalize=True,
            )

    def test_segment_followed_by_overflowing_empty_interval_is_rejected(self):
        with self.assertRaises(InvalidBackendOutputError):
            parse_result(
                [timestamp_id(0), 42, timestamp_id(1.0), timestamp_id(2.12)],
                chunk_duration=2.115,
                total_duration=2.115,
                normalize=True,
            )

    def test_final_closing_5ms_over_accepts_and_normalizes(self):
        parsed = parse_result(
            [timestamp_id(0), 42, timestamp_id(2.12)],
            chunk_duration=2.115,
            total_duration=4.23,
            offset=2.115,
            normalize=True,
        )
        self.assertEqual(len(parsed.segments), 1)
        self.assertAlmostEqual(parsed.segments[0]["end"], 4.23)
        self.assertEqual(len(parsed.normalizations), 1)
        event = parsed.normalizations[0]
        self.assertAlmostEqual(event["raw_local_end_s"], 2.12)
        self.assertAlmostEqual(event["normalized_local_end_s"], 2.115)
        self.assertAlmostEqual(event["raw_global_end_s"], 4.235)
        self.assertAlmostEqual(event["normalized_global_end_s"], 4.23)
        self.assertAlmostEqual(event["overshoot_s"], 0.005)

    def test_final_closing_10ms_over_accepts_at_boundary(self):
        parsed = parse_result(
            [timestamp_id(0), 42, timestamp_id(2.12)],
            chunk_duration=2.11,
            total_duration=2.11,
            normalize=True,
        )
        self.assertEqual(len(parsed.normalizations), 1)
        self.assertAlmostEqual(parsed.segments[0]["end"], 2.11)

    def test_final_closing_15ms_over_is_rejected(self):
        with self.assertRaises(InvalidBackendOutputError):
            parse_result(
                [timestamp_id(0), 42, timestamp_id(2.12)],
                chunk_duration=2.105,
                total_duration=2.105,
                normalize=True,
            )

    def test_final_closing_20ms_over_is_rejected(self):
        with self.assertRaises(InvalidBackendOutputError):
            parse_result(
                [timestamp_id(0), 42, timestamp_id(2.12)],
                chunk_duration=2.10,
                total_duration=2.10,
                normalize=True,
            )

    def test_final_closing_overflow_rejected_when_flag_off(self):
        with self.assertRaises(InvalidBackendOutputError):
            parse_result(
                [timestamp_id(0), 42, timestamp_id(2.12)],
                chunk_duration=2.115,
                total_duration=2.115,
                normalize=False,
            )

    def test_trailing_special_token_does_not_break_final_closing(self):
        parsed = parse_result(
            [timestamp_id(0), 42, timestamp_id(2.12), 199],
            chunk_duration=2.115,
            total_duration=2.115,
            normalize=True,
        )
        self.assertEqual(len(parsed.segments), 1)
        self.assertEqual(len(parsed.normalizations), 1)

    def test_trailing_ordinary_text_is_rejected(self):
        with self.assertRaises(InvalidBackendOutputError):
            parse_result(
                [timestamp_id(0), 42, timestamp_id(2.12), 43],
                chunk_duration=2.115,
                total_duration=2.115,
                normalize=True,
            )

    def test_start_timestamp_overflow_is_rejected(self):
        with self.assertRaises(InvalidBackendOutputError):
            parse_result(
                [timestamp_id(2.12), 42, timestamp_id(2.18)],
                chunk_duration=2.115,
                total_duration=2.18,
                normalize=True,
            )

    def test_internal_closing_overflow_is_rejected(self):
        with self.assertRaises(InvalidBackendOutputError):
            parse_result(
                [
                    timestamp_id(0),
                    42,
                    timestamp_id(2.12),
                    43,
                    timestamp_id(2.18),
                ],
                chunk_duration=2.115,
                total_duration=2.18,
                normalize=True,
            )

    def test_recursive_leaves_receive_sequential_indices(self):
        backend, _ = self.make_backend()
        backend._transcribe_chunk = Mock(
            side_effect=[
                InvalidBackendOutputError("split"),
                ParsedChunk(
                    [{"start": 0.0, "end": 1.0, "text": "left"}],
                    [{"reason": "test", "leaf_index": -1}],
                ),
                ParsedChunk(
                    [{"start": 4.0, "end": 5.0, "text": "right"}],
                    [{"reason": "test", "leaf_index": -1}],
                ),
            ]
        )
        parsed = backend._transcribe_window(
            [0.0] * (8 * 16000),
            offset_seconds=0.0,
            total_duration_seconds=8.0,
            leaf_counter=[0],
        )
        self.assertEqual(
            [event["leaf_index"] for event in parsed.normalizations],
            [0, 1],
        )
        self.assertEqual([s["text"] for s in parsed.segments], ["left", "right"])

    def test_recursive_children_receive_global_offsets(self):
        backend, _ = self.make_backend()
        offsets = []

        def fake_chunk(samples, *, offset_seconds, total_duration_seconds):
            offsets.append(offset_seconds)
            if len(offsets) == 1:
                raise InvalidBackendOutputError("split")
            return ParsedChunk(
                [{"start": offset_seconds, "end": offset_seconds + 1.0, "text": "x"}],
                [],
            )

        backend._transcribe_chunk = fake_chunk
        parsed = backend._transcribe_window(
            [0.0] * (8 * 16000),
            offset_seconds=0.0,
            total_duration_seconds=8.0,
            leaf_counter=[0],
        )
        self.assertEqual(offsets, [0.0, 0.0, 4.0])
        self.assertEqual(
            [s["start"] for s in parsed.segments],
            [0.0, 4.0],
        )

    def test_backend_metadata_records_normalization_state(self):
        backend, _ = self.make_backend()
        with patch(
            "core.asr_hf_whisper._decode_audio_16k_mono",
            return_value=([0.0] * 16000, "wav", 1.0),
        ):
            result = backend.transcribe("fake.wav", ASRConfig())
        self.assertFalse(result.metadata["timestamp_normalization_enabled"])
        self.assertEqual(result.metadata["timestamp_normalizations"], [])

    @unittest.skipUnless(
        os.getenv("COLOSTRUCT_HF_WHISPER_MODEL"),
        "set COLOSTRUCT_HF_WHISPER_MODEL to run real tokenizer test",
    )
    def test_real_checkpoint_tokenizer_timestamp_sequence(self):
        from transformers import AutoProcessor

        model_path = os.environ["COLOSTRUCT_HF_WHISPER_MODEL"]
        processor = AutoProcessor.from_pretrained(
            model_path, local_files_only=True
        )
        tokenizer = processor.tokenizer
        no_ts = tokenizer.convert_tokens_to_ids("<|notimestamps|>")
        begin = _resolve_timestamp_begin(tokenizer, no_ts)
        text_ids = tokenizer.encode("test", add_special_tokens=False)
        parsed = _parse_timestamped_ids(
            [begin, *text_ids, begin + 50],
            tokenizer,
            offset_seconds=0.0,
            chunk_duration_seconds=2.0,
            total_duration_seconds=2.0,
            no_timestamps_token_id=no_ts,
            normalize_final_chunk_end=True,
        )
        self.assertEqual(len(parsed.segments), 1)
        self.assertAlmostEqual(parsed.segments[0]["start"], 0.0)
        self.assertAlmostEqual(parsed.segments[0]["end"], 1.0)
        self.assertTrue(parsed.segments[0]["text"].strip())


if __name__ == "__main__":
    unittest.main()
