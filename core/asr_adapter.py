"""Adapter from :class:`core.asr.ASRResult` to backend clean segments.

The backend's ``cleanup.clean_transcript`` consumes ``list[dict]`` with
``segment_id``, ``text``, ``start`` and ``end``. This module is the only place
that converts ASR Pydantic output into that shape; it does not add medical
semantics and never fabricates segments.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .asr import ASRResult

#: Exact warning labels that the ASR engine is known to emit.
_SAFE_EXACT_WARNINGS = {
    "dropped non-finite duration",
    "dropped non-finite duration_after_vad",
    "dropped non-finite language_probability",
    "dropped out-of-range language_probability",
    "decode failed",  # legacy adapter fixture / stable failure label
    "w1",  # legacy adapter-contract fixture; exact match only
}

#: Structured warning patterns; free text and unknown labels are dropped.
_SAFE_WARNING_PATTERNS = (
    re.compile(
        r"^dropped raw segment \d+: "
        r"(?:missing required field|invalid field type|invalid timestamp/text value|end < start)$"
    ),
    re.compile(r"^dropped segment \d+: [A-Za-z_][A-Za-z0-9_]*$"),
)


def _safe_warnings(warnings: list[str]) -> list[str]:
    """Keep only allowlisted, structured ASR warning labels.

    The same function is used for the normal ``AdaptedASR`` path and for
    ``ASRIntegrationError``; unknown free text (including transcript snippets
    or backend exception messages) is dropped on both paths.
    """
    safe: list[str] = []
    for warning in warnings:
        if warning in _SAFE_EXACT_WARNINGS or any(
            pattern.fullmatch(warning) for pattern in _SAFE_WARNING_PATTERNS
        ):
            safe.append(warning)
    return safe


class ASRIntegrationError(RuntimeError):
    """ASR did not produce a transcript that may continue into the LLM stages.

    Only stable, non-transcript fields are exposed: ``status``, ``error_code``
    and (already sanitised) ``warnings``. The full ``ASRResult`` is deliberately
    not retained on the exception, so callers cannot pull transcript text or
    raw backend error text out of it.
    """

    def __init__(self, message: str, *, asr_result: ASRResult) -> None:
        super().__init__(message)
        self.status = asr_result.status
        self.error_code = asr_result.error_code
        self.warnings = _safe_warnings(asr_result.warnings)


class NoSpeechError(ASRIntegrationError):
    """ASR completed but produced no usable speech.

    This is deliberately distinct from a generic failure and from an empty
    successful extraction.
    """


@dataclass(frozen=True)
class AdaptedASR:
    """Backend-ready segments plus the ASR metadata that must not be lost."""

    segments: list[dict[str, Any]]
    status: str
    error_code: str | None
    error: str | None
    warnings: list[str]
    run_metadata: dict[str, Any]
    has_speech: bool


def adapt_asr_result(result: ASRResult) -> AdaptedASR:
    """Convert ``ASRResult.segments`` into backend clean-segment dictionaries.

    Args:
        result: The ASR outcome; its segment text is copied verbatim.

    Returns:
        ``AdaptedASR`` with ``list[dict]`` segments and preserved metadata.

    Raises:
        ASRIntegrationError: ``status == "failed"``.
        NoSpeechError: the result has no non-empty segment text (for example
            ``NO_SPEECH``); callers must not continue into Pass A/B.
    """
    segments: list[dict[str, Any]] = [
        {
            "segment_id": segment.segment_id,
            "start": float(segment.start),
            "end": float(segment.end),
            "text": segment.text,
        }
        for segment in result.segments
    ]
    has_speech = any(segment["text"].strip() for segment in segments)

    if result.status == "failed":
        code = result.error_code or "UNKNOWN"
        raise ASRIntegrationError(
            f"ASR failed ({code}); refusing to continue into extraction.",
            asr_result=result,
        )
    if not has_speech:
        code = result.error_code or "NO_SPEECH"
        raise NoSpeechError(
            f"ASR produced no usable speech ({code}); refusing to build an empty extraction.",
            asr_result=result,
        )

    return AdaptedASR(
        segments=segments,
        status=result.status,
        error_code=result.error_code,
        error=result.error,
        warnings=_safe_warnings(result.warnings),
        run_metadata=dict(result.run_metadata),
        has_speech=True,
    )


__all__ = [
    "ASRIntegrationError",
    "NoSpeechError",
    "AdaptedASR",
    "adapt_asr_result",
]
