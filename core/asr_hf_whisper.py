"""Whisper backend for Hugging Face Transformers checkpoints.

The backend is deliberately independent from the default faster-whisper path.
It accepts a local checkpoint directory or a Hugging Face model id, decodes
audio through PyAV, and returns the existing :class:`core.asr.RawTranscription`
shape. ``ASREngine`` still owns ``segment_id`` generation and status handling.

Model provenance is passed through ``RawTranscription.metadata`` so the engine
can record the actual backend/model instead of labelling every run as
faster-whisper.
"""
from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from importlib.metadata import version
from typing import Any, Callable

from .asr import (
    ASRError,
    ASRConfig,
    AudioNotFoundError,
    DecodeError,
    EmptyAudioError,
    InferenceError,
    InvalidBackendOutputError,
    ModelLoadError,
    RawTranscription,
    UnsupportedFormatError,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL_ID = "JackyHoCL/whisper-small-cantonese-yue-english"
DEFAULT_MODEL_REVISION = "bde975727e573bb92d4c4ee3c05a29a0f79fb195"
DEFAULT_LANGUAGE = "zh"
DEFAULT_CHUNK_SECONDS = 10.0
MAX_NEW_TOKENS = 444
SAMPLE_RATE = 16_000
TIMESTAMP_PRECISION_SECONDS = 0.02
TIMESTAMP_EPSILON_SECONDS = 1e-6
HALF_STEP_SECONDS = 0.01
SUPPORTED_LANGUAGES = frozenset({"zh", "en"})


def _transcription_window_ranges(
    total_samples: int,
    chunk_samples: int,
    min_tail_samples: int,
) -> list[tuple[int, int]]:
    """Create fixed windows, merging only a too-short final tail.

    Most audio keeps the configured maximum chunk length. A short final tail
    (for example 3.901 s at the end of a 73.901 s file) is merged into the
    preceding window so it is not processed as an isolated leaf below the
    recursive-split minimum. The merge is bounded by the preceding window plus
    that tail, i.e. at most ``chunk_samples + min_tail_samples``.
    """
    if not isinstance(total_samples, int) or isinstance(total_samples, bool):
        raise ValueError("total_samples must be an integer")
    if not isinstance(chunk_samples, int) or isinstance(chunk_samples, bool):
        raise ValueError("chunk_samples must be an integer")
    if not isinstance(min_tail_samples, int) or isinstance(min_tail_samples, bool):
        raise ValueError("min_tail_samples must be an integer")
    if total_samples < 0:
        raise ValueError("total_samples must be non-negative")
    if chunk_samples <= 0:
        raise ValueError("chunk_samples must be positive")
    if min_tail_samples < 0:
        raise ValueError("min_tail_samples must be non-negative")
    if total_samples == 0:
        return []

    ranges: list[tuple[int, int]] = []
    start = 0
    while start < total_samples:
        end = min(total_samples, start + chunk_samples)
        ranges.append((start, end))
        start = end

    # Only the final short tail is special; never change earlier windows.
    threshold = min(min_tail_samples, chunk_samples)
    if len(ranges) >= 2:
        tail_start, tail_end = ranges[-1]
        if tail_end - tail_start < threshold:
            previous_start, _ = ranges[-2]
            ranges[-2:] = [(previous_start, total_samples)]

    return ranges


@dataclass(frozen=True)
class ParsedChunk:
    """Parsed leaf output plus auditable timestamp normalizations."""

    segments: list[dict[str, Any]]
    normalizations: list[dict[str, Any]]


def _package_version(name: str) -> str | None:
    try:
        return version(name)
    except Exception:
        return None


def _resolve_language(requested: str | None, fallback: str) -> str:
    """Map the unsupported Whisper ``yue`` prompt to ``zh``.

    The verified checkpoint's tokenizer has no ``<|yue|>`` token; asking for
    ``yue`` silently resolves to ``<|translate|>``. The rewrite is logged as a
    warning and is not treated as a valid language prompt.
    """
    language = (requested or fallback or DEFAULT_LANGUAGE).strip().lower()
    if language == "yue":
        logger.warning("Whisper tokenizer has no <|yue|> token; using zh instead")
        language = "zh"
    if language not in SUPPORTED_LANGUAGES:
        raise ModelLoadError(
            f"unsupported Whisper language prompt {language!r}; "
            f"supported: {sorted(SUPPORTED_LANGUAGES)}"
        )
    return language


def _tokenizer_notimestamps_id(tokenizer: Any) -> int | None:
    try:
        token_id = tokenizer.convert_tokens_to_ids("<|notimestamps|>")
    except Exception:
        return None
    if isinstance(token_id, bool) or not isinstance(token_id, int) or token_id < 0:
        return None
    return int(token_id)


def _resolve_timestamp_begin(
    tokenizer: Any,
    no_timestamps_token_id: int | None = None,
) -> int:
    """Resolve the first timestamp id from the explicit Whisper contracts.

    Generation config's ``no_timestamps_token_id`` is authoritative; the
    tokenizer's explicit ``<|notimestamps|>`` token is a cross-check. If both
    are present and disagree, parsing must fail instead of guessing. The
    ``all_special_ids`` ordering is deliberately not used as a default.
    """
    config_begin = None
    if (
        no_timestamps_token_id is not None
        and not isinstance(no_timestamps_token_id, bool)
        and isinstance(no_timestamps_token_id, int)
        and no_timestamps_token_id >= 0
    ):
        config_begin = int(no_timestamps_token_id) + 1

    tokenizer_id = _tokenizer_notimestamps_id(tokenizer)
    tokenizer_begin = tokenizer_id + 1 if tokenizer_id is not None else None

    if config_begin is not None and tokenizer_begin is not None:
        if config_begin != tokenizer_begin:
            raise InvalidBackendOutputError(
                "Whisper no_timestamps token id differs between generation "
                "config and tokenizer"
            )
        return config_begin
    if config_begin is not None:
        return config_begin
    if tokenizer_begin is not None:
        return tokenizer_begin
    raise InvalidBackendOutputError("cannot determine Whisper timestamp token range")


def _timestamp_begin(tokenizer: Any) -> int:
    """Compatibility wrapper using only the tokenizer contract."""
    return _resolve_timestamp_begin(tokenizer, None)


def _timestamp_to_seconds(token_id: int, timestamp_begin: int) -> float:
    return (int(token_id) - timestamp_begin) * TIMESTAMP_PRECISION_SECONDS


def _is_ignorable_prefix_token(tokenizer: Any, token: int, special_ids: set[int]) -> bool:
    """Return whether a token before the first timestamp may be ignored."""
    if token in special_ids:
        return True
    decoded = tokenizer.decode([token], skip_special_tokens=True).strip()
    return not decoded


def _parse_timestamped_ids(
    token_ids: list[int],
    tokenizer: Any,
    *,
    offset_seconds: float,
    chunk_duration_seconds: float,
    total_duration_seconds: float,
    no_timestamps_token_id: int | None = None,
    normalize_final_chunk_end: bool = False,
) -> ParsedChunk:
    """Convert Whisper timestamp tokens into segments and audit events.

    Every timestamp event is validated before an empty result may be returned.
    Only the final closing timestamp of the last non-empty segment in a leaf is
    eligible for the optional half-step normalization.
    """
    if not math.isfinite(offset_seconds) or offset_seconds < 0:
        raise InvalidBackendOutputError("invalid chunk offset")
    if not math.isfinite(chunk_duration_seconds) or chunk_duration_seconds <= 0:
        raise InvalidBackendOutputError("invalid chunk duration")
    if not math.isfinite(total_duration_seconds) or total_duration_seconds < 0:
        raise InvalidBackendOutputError("invalid audio duration")

    begin = _resolve_timestamp_begin(tokenizer, no_timestamps_token_id)
    special_ids = {
        int(token)
        for token in (getattr(tokenizer, "all_special_ids", None) or [])
        if isinstance(token, int) and not isinstance(token, bool)
    }
    timestamp_events: list[dict[str, Any]] = []
    raw_segments: list[dict[str, Any]] = []
    current_start: float | None = None
    current_start_ordinal: int | None = None
    text_ids: list[int] = []
    ordinal = 0
    provisional_limit = (
        chunk_duration_seconds
        + TIMESTAMP_EPSILON_SECONDS
        + (HALF_STEP_SECONDS if normalize_final_chunk_end else 0.0)
    )

    for raw_token in token_ids:
        try:
            token = int(raw_token)
        except (TypeError, ValueError) as exc:
            raise InvalidBackendOutputError("non-numeric Whisper token id") from exc

        if token >= begin:
            ordinal += 1
            local_time = _timestamp_to_seconds(token, begin)
            if local_time < 0 or local_time > provisional_limit:
                raise InvalidBackendOutputError(
                    "Whisper timestamp lies outside the provisional chunk range"
                )

            timestamp_events.append({
                "ordinal": ordinal,
                "raw_local_time": local_time,
                "starts_segments": [],
                "ends_segments": [],
            })

            if current_start is None:
                current_start = local_time
                current_start_ordinal = ordinal
                text_ids = []
                continue

            if local_time < current_start:
                raise InvalidBackendOutputError("Whisper timestamps are not monotonic")

            text = tokenizer.decode(text_ids, skip_special_tokens=True).strip()
            if text:
                segment_index = len(raw_segments)
                raw_segments.append({
                    "start_ordinal": current_start_ordinal,
                    "end_ordinal": ordinal,
                    "raw_local_start": current_start,
                    "raw_local_end": local_time,
                    "text": text,
                })
                timestamp_events[current_start_ordinal - 1]["starts_segments"].append(
                    segment_index
                )
                timestamp_events[ordinal - 1]["ends_segments"].append(segment_index)

            current_start = local_time
            current_start_ordinal = ordinal
            text_ids = []
        elif current_start is None:
            if not _is_ignorable_prefix_token(tokenizer, token, special_ids):
                raise InvalidBackendOutputError(
                    "Whisper output contains ordinary text before its first timestamp"
                )
        else:
            text_ids.append(token)

    if current_start is not None and text_ids:
        trailing = tokenizer.decode(text_ids, skip_special_tokens=True).strip()
        if trailing:
            raise InvalidBackendOutputError(
                "Whisper output ended with text but no closing timestamp"
            )

    if not timestamp_events:
        decoded = tokenizer.decode(token_ids, skip_special_tokens=True).strip()
        if decoded:
            raise InvalidBackendOutputError("Whisper output contains no timestamp tokens")
        return ParsedChunk(segments=[], normalizations=[])

    # Candidate is the last non-empty segment's closing timestamp, and it must
    # also be the final timestamp event (no trailing empty timestamp interval).
    candidate_final = False
    eligible_ordinal: int | None = None
    if raw_segments:
        last_segment = raw_segments[-1]
        if last_segment["end_ordinal"] == timestamp_events[-1]["ordinal"]:
            candidate_final = True
            eligible_ordinal = int(last_segment["end_ordinal"])

    # Validate every timestamp event, including empty intervals and trailing
    # timestamps. This must happen before any empty-result return.
    allowed_normalization: dict[int, float] = {}
    for event in timestamp_events:
        raw_local = float(event["raw_local_time"])
        if raw_local <= chunk_duration_seconds + TIMESTAMP_EPSILON_SECONDS:
            continue
        overshoot = raw_local - chunk_duration_seconds
        is_allowed_final = (
            normalize_final_chunk_end
            and candidate_final
            and event["ordinal"] == eligible_ordinal
            and overshoot <= HALF_STEP_SECONDS + TIMESTAMP_EPSILON_SECONDS
        )
        if not is_allowed_final:
            raise InvalidBackendOutputError(
                "Whisper timestamp outside chunk is not an allowed final closing"
            )
        allowed_normalization[int(event["ordinal"])] = overshoot

    if not raw_segments:
        return ParsedChunk(segments=[], normalizations=[])

    final_segments: list[dict[str, Any]] = []
    normalizations: list[dict[str, Any]] = []
    last_segment_index = len(raw_segments) - 1

    for index, raw in enumerate(raw_segments):
        raw_start = float(raw["raw_local_start"])
        raw_end = float(raw["raw_local_end"])
        if raw_start > chunk_duration_seconds + TIMESTAMP_EPSILON_SECONDS:
            raise InvalidBackendOutputError("Whisper segment starts outside chunk")

        normalized_end = raw_end
        if raw_end > chunk_duration_seconds + TIMESTAMP_EPSILON_SECONDS:
            if index != last_segment_index:
                raise InvalidBackendOutputError(
                    "non-final Whisper segment ends outside chunk"
                )
            overshoot = allowed_normalization.get(int(raw["end_ordinal"]))
            if overshoot is None:
                raise InvalidBackendOutputError(
                    "final chunk end normalization was not authorized"
                )
            normalized_end = chunk_duration_seconds
            normalizations.append({
                "chunk_offset_s": offset_seconds,
                "chunk_duration_s": chunk_duration_seconds,
                "raw_local_end_s": raw_end,
                "normalized_local_end_s": normalized_end,
                "raw_global_end_s": offset_seconds + raw_end,
                "normalized_global_end_s": offset_seconds + normalized_end,
                "overshoot_s": overshoot,
                "reason": "final_leaf_chunk_end_half_step",
            })

        start = offset_seconds + raw_start
        end = offset_seconds + normalized_end
        if start >= end:
            raise InvalidBackendOutputError(
                "Whisper segment has non-positive duration"
            )
        if end > total_duration_seconds + TIMESTAMP_EPSILON_SECONDS:
            raise InvalidBackendOutputError(
                "Whisper segment extends beyond total audio duration"
            )
        final_segments.append({"start": start, "end": end, "text": raw["text"]})

    for prev, curr in zip(final_segments, final_segments[1:]):
        if curr["start"] < prev["end"] - TIMESTAMP_EPSILON_SECONDS:
            raise InvalidBackendOutputError(
                "Whisper chunk segments overlap or go backwards"
            )

    return ParsedChunk(
        segments=final_segments,
        normalizations=normalizations,
    )


def _decode_audio_16k_mono(audio_path: str) -> tuple[Any, str | None, float]:
    """Decode any PyAV-supported file to 16 kHz mono float32 samples.

    The audio is concatenated once; no unbounded per-source copies are kept.
    """
    try:
        import av
        import numpy as np
    except ImportError as exc:  # pragma: no cover - runtime dependency
        raise DecodeError("PyAV or NumPy is not installed") from exc

    if not os.path.isfile(audio_path):
        raise AudioNotFoundError("audio file not found")
    try:
        if os.path.getsize(audio_path) == 0:
            raise EmptyAudioError("audio file is empty")
    except OSError as exc:
        raise AudioNotFoundError("audio file is not readable") from exc

    try:
        container = av.open(audio_path)
    except FileNotFoundError as exc:
        raise AudioNotFoundError("audio file not found") from exc
    except Exception as exc:
        raise UnsupportedFormatError(
            f"cannot open audio container ({type(exc).__name__})"
        ) from exc

    try:
        streams = [s for s in container.streams if s.type == "audio"]
        if not streams:
            raise UnsupportedFormatError("audio file has no audio stream")
        audio_format = container.format.name if container.format else None
        resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        pieces = []
        for frame in container.decode(streams[0]):
            for out_frame in resampler.resample(frame):
                pieces.append(out_frame.to_ndarray().reshape(-1))
        if not pieces:
            raise DecodeError("audio file contains no decodable audio frames")
        pcm = np.concatenate(pieces).astype(np.float32) / 32768.0
        if pcm.size == 0:
            raise EmptyAudioError("audio file contains no samples")
    except ASRError:
        raise
    except Exception as exc:
        raise DecodeError(f"audio decode failed ({type(exc).__name__})") from exc
    finally:
        container.close()

    return pcm, audio_format, float(len(pcm) / SAMPLE_RATE)


class HFWhisperBackend:
    """Transformers Whisper backend for the existing ``ASRBackend`` Protocol.

    Args:
        model_path: Local checkpoint directory or Hugging Face model id.
        revision: Model revision recorded in metadata and used for downloads.
        device: ``cpu`` (default) or ``cuda``; CUDA requires a working PyTorch
            CUDA build and is not assumed.
        language: Default language prompt; ``zh`` or ``en``. ``yue`` is mapped
            to ``zh`` because the verified checkpoint has no yue token.
        chunk_length_s: Fixed non-overlapping window length. The default is
            10 seconds for CPU stability; Whisper's encoder supports up to
            roughly 30 seconds. Larger windows may trigger timestamp resets on
            repetitive audio and are guarded by the recursive split fallback.
        local_files_only: Do not contact the Hugging Face Hub.
        normalize_final_chunk_end: Opt-in half-step (10 ms) normalization for
            the last non-empty segment's closing timestamp of each successful
            leaf chunk. Defaults to False.
    """

    def __init__(
        self,
        model_path: str = DEFAULT_MODEL_ID,
        *,
        revision: str | None = DEFAULT_MODEL_REVISION,
        device: str = "cpu",
        language: str = DEFAULT_LANGUAGE,
        chunk_length_s: float = DEFAULT_CHUNK_SECONDS,
        local_files_only: bool = False,
        normalize_final_chunk_end: bool = False,
        _processor_factory: Callable[..., Any] | None = None,
        _model_factory: Callable[..., Any] | None = None,
    ) -> None:
        if not model_path or not isinstance(model_path, str):
            raise ValueError("model_path must be a non-empty string")
        if not math.isfinite(chunk_length_s) or chunk_length_s <= 0:
            raise ValueError("chunk_length_s must be a positive finite number")
        self.model_path = model_path
        self.revision = revision
        self.device = device
        self.language = language
        self.chunk_length_s = float(chunk_length_s)
        self.min_chunk_s = 2.0
        self.local_files_only = local_files_only
        self.normalize_final_chunk_end = bool(normalize_final_chunk_end)
        self._processor_factory = _processor_factory
        self._model_factory = _model_factory
        self._processor: Any = None
        self._model: Any = None
        self._torch: Any = None
        self._loaded = False
        self._effective_language = language
        self._effective_device = device

    def _provenance(self) -> dict[str, Any]:
        return {
            "backend": "transformers_whisper",
            "model_id": self.model_path,
            "model_revision": self.revision,
            "device": self._effective_device,
            "transformers_version": _package_version("transformers"),
            "torch_version": _package_version("torch"),
            "chunk_length_s": self.chunk_length_s,
        }

    def load(self, config: ASRConfig) -> None:
        """Load the processor/model once and resolve device/language."""
        if self._loaded:
            return

        self._effective_language = _resolve_language(config.language, self.language)
        requested_device = config.device or self.device
        if requested_device not in {"cpu", "cuda"}:
            raise ModelLoadError(f"unsupported device {requested_device!r}")

        try:
            if self._processor_factory is None or self._model_factory is None:
                from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor
                import torch
            else:
                AutoModelForSpeechSeq2Seq = None
                AutoProcessor = None
                torch = None

            if self._processor_factory is None:
                self._processor_factory = AutoProcessor.from_pretrained
            if self._model_factory is None:
                self._model_factory = AutoModelForSpeechSeq2Seq.from_pretrained
            self._torch = torch
            if requested_device == "cuda":
                if not bool(torch.cuda.is_available()):
                    raise ModelLoadError("CUDA requested but torch.cuda is unavailable")
                self._effective_device = "cuda"
            else:
                self._effective_device = "cpu"

            source_kwargs: dict[str, Any] = {
                "local_files_only": self.local_files_only,
            }
            if self.revision and not os.path.isdir(self.model_path):
                source_kwargs["revision"] = self.revision
            self._processor = self._processor_factory(self.model_path, **source_kwargs)
            self._model = self._model_factory(
                self.model_path,
                torch_dtype=torch.float32 if torch is not None else None,
                **source_kwargs,
            )
            if getattr(self._model, "generation_config", None) is not None:
                # Explicit language/task below must win over the checkpoint's
                # old forced prompt, which can otherwise point at en/translate.
                self._model.generation_config.forced_decoder_ids = None
            if getattr(self._model, "config", None) is not None:
                self._model.config.forced_decoder_ids = None
            self._model.to(self._effective_device)
            self._model.eval()
        except ModelLoadError:
            raise
        except ImportError as exc:
            raise ModelLoadError("torch/transformers is not installed") from exc
        except Exception as exc:
            raise ModelLoadError(f"{type(exc).__name__}: {exc}") from exc

        self._loaded = True

    def _transcribe_chunk(
        self,
        samples: Any,
        *,
        offset_seconds: float,
        total_duration_seconds: float,
    ) -> ParsedChunk:
        if self._model is None or self._processor is None:
            raise InferenceError("Whisper backend is not loaded")
        try:
            inputs = self._processor(
                samples,
                sampling_rate=SAMPLE_RATE,
                return_tensors="pt",
            )
            input_features = inputs["input_features"].to(self._effective_device)
            generate_kwargs: dict[str, Any] = {
                "language": self._effective_language,
                "task": "transcribe",
                "return_timestamps": True,
                "max_new_tokens": MAX_NEW_TOKENS,
            }
            attention_mask = getattr(inputs, "attention_mask", None)
            if attention_mask is None:
                attention_mask = self._torch.ones(
                    input_features.shape[0],
                    input_features.shape[2],
                    dtype=self._torch.long,
                    device=self._effective_device,
                )
            else:
                attention_mask = attention_mask.to(self._effective_device)
            with self._torch.inference_mode():
                output_ids = self._model.generate(
                    input_features,
                    attention_mask=attention_mask,
                    **generate_kwargs,
                )
            token_ids = output_ids[0].tolist() if hasattr(output_ids[0], "tolist") else list(output_ids[0])
        except Exception as exc:
            raise InferenceError(f"{type(exc).__name__}: {exc}") from exc

        return _parse_timestamped_ids(
            token_ids,
            self._processor.tokenizer,
            offset_seconds=offset_seconds,
            chunk_duration_seconds=len(samples) / SAMPLE_RATE,
            total_duration_seconds=total_duration_seconds,
            no_timestamps_token_id=getattr(
                getattr(self._model, "generation_config", None),
                "no_timestamps_token_id",
                None,
            ),
            normalize_final_chunk_end=self.normalize_final_chunk_end,
        )

    def _transcribe_window(
        self,
        samples: Any,
        *,
        offset_seconds: float,
        total_duration_seconds: float,
        depth: int = 0,
        leaf_counter: list[int] | None = None,
    ) -> ParsedChunk:
        """Transcribe one window, halving it only on timestamp validation errors.

        Successful leaves receive a 0-based, monotonically increasing leaf
        index. A failed parent consumes no leaf index; only its successful
        children do.
        """
        if leaf_counter is None:
            leaf_counter = [0]

        try:
            parsed = self._transcribe_chunk(
                samples,
                offset_seconds=offset_seconds,
                total_duration_seconds=total_duration_seconds,
            )
            leaf_index = leaf_counter[0]
            leaf_counter[0] += 1
            for event in parsed.normalizations:
                event["leaf_index"] = leaf_index
            return parsed
        except InvalidBackendOutputError:
            if len(samples) < int(2 * self.min_chunk_s * SAMPLE_RATE) or depth >= 4:
                raise
            midpoint = len(samples) // 2
            left = self._transcribe_window(
                samples[:midpoint],
                offset_seconds=offset_seconds,
                total_duration_seconds=total_duration_seconds,
                depth=depth + 1,
                leaf_counter=leaf_counter,
            )
            right = self._transcribe_window(
                samples[midpoint:],
                offset_seconds=offset_seconds + midpoint / SAMPLE_RATE,
                total_duration_seconds=total_duration_seconds,
                depth=depth + 1,
                leaf_counter=leaf_counter,
            )
            return ParsedChunk(
                segments=left.segments + right.segments,
                normalizations=left.normalizations + right.normalizations,
            )

    def transcribe(self, audio_path: str, config: ASRConfig) -> RawTranscription:
        """Decode, transcribe in fixed non-overlapping windows, return raw segments."""
        if not self._loaded:
            self.load(config)

        pcm, audio_format, duration = _decode_audio_16k_mono(audio_path)
        chunk_samples = max(1, int(round(self.chunk_length_s * SAMPLE_RATE)))
        all_segments: list[dict[str, Any]] = []
        all_normalizations: list[dict[str, Any]] = []
        leaf_counter = [0]

        for start_sample, end_sample in _transcription_window_ranges(
            len(pcm),
            chunk_samples,
            int(2 * self.min_chunk_s * SAMPLE_RATE),
        ):
            chunk = pcm[start_sample:end_sample]
            if len(chunk) == 0:
                continue
            offset_seconds = start_sample / SAMPLE_RATE
            parsed = self._transcribe_window(
                chunk,
                offset_seconds=offset_seconds,
                total_duration_seconds=duration,
                leaf_counter=leaf_counter,
            )
            for segment in parsed.segments:
                if all_segments and segment["start"] < all_segments[-1]["end"] - 1e-3:
                    raise InvalidBackendOutputError(
                        "Whisper chunk segments overlap or go backwards"
                    )
                all_segments.append(segment)
            all_normalizations.extend(parsed.normalizations)

        metadata = self._provenance()
        metadata["timestamp_normalization_enabled"] = self.normalize_final_chunk_end
        metadata["timestamp_normalizations"] = all_normalizations

        return RawTranscription(
            segments=all_segments,
            language=self._effective_language,
            duration=duration,
            audio_format=audio_format,
            metadata=metadata,
        )


__all__ = ["HFWhisperBackend", "DEFAULT_MODEL_ID", "DEFAULT_MODEL_REVISION"]
