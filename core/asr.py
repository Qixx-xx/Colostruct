"""ASR interface for the A-group pipeline.

This module is the ASR boundary: audio in, structured transcript out. It is
independent from the LLM extraction layer (``core.llm``) and never constructs
``AGroupResult``. The caller decides what to do with ``status="failed"``.

Contract summary (see ``P3_B_ASR_CONTRACT_DESIGN.md``):

* ``ASREngine`` loads the model lazily on first ``transcribe`` and reuses it;
* a failed model load is cached and never retried by the same engine;
* ``ASRSegment.text`` keeps the raw faster-whisper text (no strip/rewrite);
* ``segment_id`` is ``seg-001``-style and unique within one result only;
* timestamps are seconds (float) and must be finite;
* ``duration``/``duration_after_vad`` are recorded but never used to judge
  transcript completeness.
"""
from __future__ import annotations

import hashlib
import math
import os
import platform
import time
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "asr_result/v1"

AsrStatus = Literal["success", "partial", "failed"]


class ASRError(Exception):
    """Base class for errors that map onto an ``ASRResult.error_code``."""

    code = "ASR_ERROR"


class AudioNotFoundError(ASRError):
    code = "AUDIO_NOT_FOUND"


class EmptyAudioError(ASRError):
    code = "EMPTY_AUDIO"


class UnsupportedFormatError(ASRError):
    code = "UNSUPPORTED_FORMAT"


class DecodeError(ASRError):
    code = "DECODE_ERROR"


class ModelLoadError(ASRError):
    code = "MODEL_LOAD_FAILED"


class InferenceError(ASRError):
    code = "INFERENCE_ERROR"


class InvalidBackendOutputError(ASRError):
    code = "INVALID_BACKEND_OUTPUT"


def _finite(value: float) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("value must be finite")
    return number


def _redact(message: str, audio_path: str | None) -> str:
    """Remove the audio path (and basename) from user-visible error text."""
    if not message or not audio_path:
        return message
    candidates = {audio_path, os.path.abspath(audio_path), os.path.basename(audio_path)}
    for candidate in sorted(candidates, key=len, reverse=True):
        if candidate:
            message = message.replace(candidate, "<audio>")
    return message


def _error_detail(exc: BaseException) -> str:
    """Keep the exception type and a redacted message for diagnostics."""
    name = type(exc).__name__
    message = str(exc).strip()
    return f"{name}: {message}" if message else name


def _segment_failure_label(exc: BaseException) -> str:
    """Return a stable, non-free-text reason for a dropped segment."""
    if isinstance(exc, KeyError):
        return "missing required field"
    if isinstance(exc, TypeError):
        return "invalid field type"
    if isinstance(exc, ValueError):
        return "invalid timestamp/text value"
    return type(exc).__name__


def _finite_or_none(value, label=None, warnings=None):
    """Coerce to a finite float; degrade to None instead of failing the batch."""
    if value is None:
        return None
    try:
        return _finite(value)
    except (TypeError, ValueError):
        if warnings is not None and label:
            warnings.append(f"dropped non-finite {label}")
        return None


class ASRConfig(BaseModel):
    """ASR parameters. Defaults are the machine's initial defaults, not a final
    model choice. ``extra="forbid"`` catches misspelled configuration keys.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    model_size: str = Field(default="base", min_length=1)
    device: Literal["cpu", "cuda"] = "cpu"
    compute_type: str = Field(default="int8", min_length=1)
    beam_size: int = Field(default=5, ge=1)
    vad_filter: bool = True
    condition_on_previous_text: bool = False
    language: str | None = Field(default=None, min_length=1)
    initial_prompt: str | None = None
    word_timestamps: bool = False
    cpu_threads: int | None = Field(default=None, ge=1)


class ASRSegment(BaseModel):
    """One ASR segment. ``text`` is raw model output and is never rewritten."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    segment_id: str = Field(pattern=r"^seg-\d{3,}$")
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    text: str

    @field_validator("start", "end")
    @classmethod
    def _timestamps_finite(cls, value: float) -> float:
        return _finite(value)

    @model_validator(mode="after")
    def _timestamps_ordered(self) -> "ASRSegment":
        if self.end < self.start:
            raise ValueError("end must be >= start")
        return self


class ASRResult(BaseModel):
    """Structured ASR outcome. ``status`` follows the P3-B rules strictly."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    schema_version: Literal["asr_result/v1"] = SCHEMA_VERSION
    status: AsrStatus
    error_code: str | None = None
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)
    segments: list[ASRSegment] = Field(default_factory=list)
    language: str | None = None
    language_probability: float | None = Field(default=None, ge=0.0, le=1.0)
    duration: float | None = Field(default=None, ge=0.0)
    duration_after_vad: float | None = Field(default=None, ge=0.0)
    model: str
    config: ASRConfig
    elapsed_seconds: float = Field(ge=0.0)
    run_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("language_probability", "duration", "duration_after_vad", "elapsed_seconds")
    @classmethod
    def _numbers_finite(cls, value: float | None) -> float | None:
        if value is None:
            return None
        return _finite(value)

    @model_validator(mode="after")
    def _status_consistency(self) -> "ASRResult":
        if self.status == "success":
            if self.error_code is not None:
                raise ValueError("success must not carry error_code")
            if not any(segment.text.strip() for segment in self.segments):
                raise ValueError("success requires at least one non-empty text segment")
        else:
            if self.error_code is None:
                raise ValueError(f"{self.status} requires error_code")
            if self.status == "failed" and self.segments:
                raise ValueError("failed must not carry segments")
        return self


@dataclass
class RawTranscription:
    """Backend output before engine normalisation (no ids, no status)."""

    segments: list[dict[str, Any]]
    language: str | None = None
    language_probability: float | None = None
    duration: float | None = None
    duration_after_vad: float | None = None
    audio_format: str | None = None
    #: Backend-owned provenance (for example model_id/revision/device).
    #: Existing backends may leave this empty; the engine merges it into
    #: ``ASRResult.run_metadata`` without changing the faster-whisper path.
    metadata: dict[str, Any] = field(default_factory=dict)


class ASRBackend(Protocol):
    """Backend boundary; injectable for tests (no model, no network)."""

    def load(self, config: ASRConfig) -> None: ...

    def transcribe(self, audio_path: str, config: ASRConfig) -> RawTranscription: ...


def _probe_audio(audio_path: str) -> tuple[str | None, float | None]:
    """Read container metadata only (no decoding, no transcription)."""
    try:
        import av
    except ImportError as exc:  # pragma: no cover - PyAV is a runtime dependency
        raise DecodeError("PyAV is not installed") from exc
    try:
        with av.open(audio_path) as container:
            codec = next(
                (stream.codec_context.name for stream in container.streams if stream.type == "audio"),
                None,
            )
            fmt = container.format.name if container.format else None
            duration = None
            if container.duration is not None:
                duration = _finite(float(container.duration) / 1_000_000)
            label = "/".join(part for part in (fmt, codec) if part) or None
            return label, duration
    except FileNotFoundError as exc:
        raise AudioNotFoundError("audio file not found") from exc
    except Exception as exc:  # av raises InvalidDataError for corrupt/unsupported files
        if type(exc).__name__ in {"InvalidDataError", "UnsupportedFormatError"}:
            raise UnsupportedFormatError(
                f"unsupported audio format ({type(exc).__name__})"
            ) from exc
        raise DecodeError(f"failed to decode audio ({type(exc).__name__})") from exc


class _FasterWhisperBackend:
    """Real backend. Imports faster-whisper only when the model is loaded."""

    def __init__(self) -> None:
        self._model: Any = None

    def load(self, config: ASRConfig) -> None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise ModelLoadError("faster-whisper is not installed") from exc
        kwargs: dict[str, Any] = {}
        if config.cpu_threads is not None:
            kwargs["cpu_threads"] = config.cpu_threads
        try:
            self._model = WhisperModel(
                config.model_size,
                device=config.device,
                compute_type=config.compute_type,
                **kwargs,
            )
        except Exception as exc:
            raise ModelLoadError(f"{type(exc).__name__}: {exc}") from exc

    def transcribe(self, audio_path: str, config: ASRConfig) -> RawTranscription:
        audio_format, container_duration = _probe_audio(audio_path)
        try:
            segments, info = self._model.transcribe(
                audio_path,
                language=config.language,
                beam_size=config.beam_size,
                vad_filter=config.vad_filter,
                condition_on_previous_text=config.condition_on_previous_text,
                initial_prompt=config.initial_prompt,
                word_timestamps=config.word_timestamps,
            )
            raw_segments = [
                {"start": segment.start, "end": segment.end, "text": segment.text}
                for segment in segments
            ]
        except ASRError:
            raise
        except Exception as exc:
            raise InferenceError(f"{type(exc).__name__}: {exc}") from exc

        duration = getattr(info, "duration", None)
        duration = container_duration if duration is None else duration
        return RawTranscription(
            segments=raw_segments,
            language=getattr(info, "language", None),
            language_probability=getattr(info, "language_probability", None),
            duration=duration,
            duration_after_vad=getattr(info, "duration_after_vad", None),
            audio_format=audio_format,
        )


def _package_version(name: str) -> str | None:
    try:
        from importlib.metadata import version

        return version(name)
    except Exception:
        return None


def _sha256(path: str) -> str | None:
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


class ASREngine:
    """Transcribe audio with a lazily-loaded, reused model.

    A model-load failure is cached: later calls return ``MODEL_LOAD_FAILED``
    without retrying. The engine is not thread-safe; callers serialise calls.
    """

    def __init__(self, config: ASRConfig | None = None, backend: ASRBackend | None = None) -> None:
        self.config = config or ASRConfig()
        self._backend: ASRBackend = backend if backend is not None else _FasterWhisperBackend()
        self._loaded = False
        self._load_error: str | None = None

    # -- internal ---------------------------------------------------------
    def _ensure_loaded(self) -> str | None:
        """Return ``None`` on success, or a cached error string."""
        if self._load_error is not None:
            return self._load_error
        if self._loaded:
            return None
        try:
            self._backend.load(self.config)
        except ASRError as exc:
            self._load_error = type(exc).__name__
            return self._load_error
        except Exception as exc:
            self._load_error = type(exc).__name__
            return self._load_error
        self._loaded = True
        return None

    def _run_metadata(
        self,
        audio_sha256: str | None,
        audio_bytes: int | None,
        audio_format: str | None,
        started_at: str,
        wall_seconds: float,
        duration: float | None,
        backend_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        prompt_hash = None
        if self.config.initial_prompt:
            prompt_hash = hashlib.sha256(self.config.initial_prompt.encode("utf-8")).hexdigest()
        metadata = {
            "audio_sha256": audio_sha256,
            "audio_bytes": audio_bytes,
            "audio_format": audio_format,
            "model_size": self.config.model_size,
            "model_snapshot": None,
            "faster_whisper_version": _package_version("faster-whisper"),
            "ctranslate2_version": _package_version("ctranslate2"),
            "av_version": _package_version("av"),
            "python_version": platform.python_version(),
            "config_fingerprint": hashlib.sha256(
                self.config.model_dump_json().encode("utf-8")
            ).hexdigest(),
            "initial_prompt_sha256": prompt_hash,
            "started_at": started_at,
            "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "wall_seconds": round(wall_seconds, 3),
            "rtf": round(wall_seconds / duration, 3) if duration and duration > 0 else None,
        }
        if backend_metadata:
            if backend_metadata.get("backend"):
                # The generic faster-whisper names are misleading for a
                # Transformers backend; the backend-specific keys below are
                # authoritative.
                metadata.pop("faster_whisper_version", None)
                metadata.pop("ctranslate2_version", None)
                metadata.pop("model_snapshot", None)
            metadata.update(backend_metadata)
        return metadata

    def _failed(
        self,
        error_code: str,
        error: str,
        started_at: str,
        started_perf: float,
        audio_sha256: str | None,
        audio_bytes: int | None,
        *,
        warnings: list[str] | None = None,
        duration: float | None = None,
        audio_format: str | None = None,
        language: str | None = None,
        language_probability: float | None = None,
    ) -> ASRResult:
        wall = time.perf_counter() - started_perf
        probability = _finite_or_none(language_probability)
        if probability is not None and not 0.0 <= probability <= 1.0:
            probability = None
        return ASRResult(
            status="failed",
            error_code=error_code,
            error=error,
            warnings=warnings or [],
            segments=[],
            language=language if isinstance(language, str) else None,
            language_probability=probability,
            duration=_finite_or_none(duration),
            duration_after_vad=None,
            model=self.config.model_size,
            config=self.config,
            elapsed_seconds=max(wall, 0.0),
            run_metadata=self._run_metadata(
                audio_sha256, audio_bytes, audio_format, started_at, wall, duration
            ),
        )

    # -- public -----------------------------------------------------------
    def transcribe(self, audio_path: str) -> ASRResult:
        started_at = time.strftime("%Y-%m-%d %H:%M:%S")
        started_perf = time.perf_counter()

        if not os.path.isfile(audio_path):
            return self._failed(
                "AUDIO_NOT_FOUND", "audio file not found",
                started_at, started_perf, None, None,
            )
        try:
            audio_bytes = os.path.getsize(audio_path)
        except OSError:
            return self._failed(
                "AUDIO_NOT_FOUND", "audio file is not readable",
                started_at, started_perf, None, None,
            )
        if audio_bytes == 0:
            return self._failed(
                "EMPTY_AUDIO", "audio file is empty", started_at, started_perf,
                _sha256(audio_path), audio_bytes,
            )

        audio_sha256 = _sha256(audio_path)
        load_error = self._ensure_loaded()
        if load_error is not None:
            return self._failed(
                "MODEL_LOAD_FAILED", _redact(load_error, audio_path),
                started_at, started_perf, audio_sha256, audio_bytes,
            )

        try:
            raw = self._backend.transcribe(audio_path, self.config)
        except ASRError as exc:
            return self._failed(
                exc.code, _redact(_error_detail(exc), audio_path),
                started_at, started_perf, audio_sha256, audio_bytes,
            )
        except Exception as exc:
            return self._failed(
                "INFERENCE_ERROR", _redact(_error_detail(exc), audio_path),
                started_at, started_perf, audio_sha256, audio_bytes,
            )

        return self._build_result(raw, started_at, started_perf, audio_sha256, audio_bytes)

    def _build_result(
        self,
        raw: RawTranscription,
        started_at: str,
        started_perf: float,
        audio_sha256: str | None,
        audio_bytes: int | None,
    ) -> ASRResult:
        wall = time.perf_counter() - started_perf
        warnings: list[str] = []
        duration = _finite_or_none(raw.duration, "duration", warnings)
        duration_after_vad = _finite_or_none(raw.duration_after_vad, "duration_after_vad", warnings)
        language_probability = _finite_or_none(
            raw.language_probability, "language_probability", warnings
        )
        if language_probability is not None and not 0.0 <= language_probability <= 1.0:
            language_probability = None
            warnings.append("dropped out-of-range language_probability")
        language = raw.language if isinstance(raw.language, str) else None

        raw_segments = raw.segments
        if not isinstance(raw_segments, list):
            return self._failed(
                "INVALID_BACKEND_OUTPUT", "backend segments is not a list",
                started_at, started_perf, audio_sha256, audio_bytes,
                duration=duration,
                audio_format=raw.audio_format,
                language=raw.language,
                language_probability=raw.language_probability,
            )

        valid: list[tuple[float, float, str]] = []
        dropped = 0
        for index, item in enumerate(raw_segments):
            try:
                if not isinstance(item, dict):
                    raise ValueError("segment is not a dict")
                start = float(item["start"])
                end = float(item["end"])
                text = item["text"]
                if not isinstance(text, str):
                    raise ValueError("text is not a string")
                if not (math.isfinite(start) and math.isfinite(end)):
                    raise ValueError("timestamp is not finite")
                if start < 0:
                    raise ValueError("start < 0")
                if end < start:
                    raise ValueError("end < start")
            except (KeyError, TypeError, ValueError) as exc:
                dropped += 1
                warnings.append(
                    f"dropped raw segment {index}: {_segment_failure_label(exc)}"
                )
                continue
            valid.append((start, end, text))

        if raw_segments and not valid:
            return self._failed(
                "INVALID_BACKEND_OUTPUT", "every backend segment had invalid timestamps",
                started_at, started_perf, audio_sha256, audio_bytes,
                warnings=warnings, duration=duration,
                audio_format=raw.audio_format,
                language=raw.language,
                language_probability=raw.language_probability,
            )

        segments: list[ASRSegment] = []
        for index, (start, end, text) in enumerate(valid):
            try:
                segments.append(
                    ASRSegment(
                        segment_id=f"seg-{index + 1:03d}",
                        start=start,
                        end=end,
                        text=text,
                    )
                )
            except Exception as exc:  # defensive: one bad segment must not sink the batch
                dropped += 1
                warnings.append(
                    f"dropped segment {index}: {type(exc).__name__}"
                )

        if raw_segments and not segments:
            return self._failed(
                "INVALID_BACKEND_OUTPUT", "no usable segment after validation",
                started_at, started_perf, audio_sha256, audio_bytes,
                warnings=warnings, duration=duration,
                audio_format=raw.audio_format,
                language=raw.language,
                language_probability=raw.language_probability,
            )

        if not segments or all(not segment.text.strip() for segment in segments):
            status, error_code = "partial", "NO_SPEECH"
        elif dropped:
            status, error_code = "partial", "PARTIAL_TRANSCRIPT"
        else:
            status, error_code = "success", None

        return ASRResult(
            status=status,
            error_code=error_code,
            error=None,
            warnings=warnings,
            segments=segments,
            language=language,
            language_probability=language_probability,
            duration=duration,
            duration_after_vad=duration_after_vad,
            model=raw.metadata.get("model_id") or self.config.model_size,
            config=self.config,
            elapsed_seconds=max(time.perf_counter() - started_perf, 0.0),
            run_metadata=self._run_metadata(
                audio_sha256, audio_bytes, raw.audio_format, started_at, wall, duration,
                backend_metadata=raw.metadata,
            ),
        )


__all__ = [
    "SCHEMA_VERSION",
    "ASRConfig",
    "ASRSegment",
    "ASRResult",
    "ASREngine",
    "ASRBackend",
    "RawTranscription",
    "ASRError",
    "AudioNotFoundError",
    "EmptyAudioError",
    "UnsupportedFormatError",
    "DecodeError",
    "ModelLoadError",
    "InferenceError",
    "InvalidBackendOutputError",
]
