"""Stable A-group entry points consumed by the backend.

Two public functions only:

* :func:`extract_clinical_info_result` — full ``AGroupResult`` (ASR adapter →
  cleanup → Pass A → Pass B), or Pass A/B only when already-cleaned segments
  are supplied;
* :func:`extract_clinical_info` — backward-compatible wrapper returning the
  backend's :class:`ColoStructExtraction`.

The Pass A → Pass B chain is the existing one; this module only wires ASR,
diagnostics and override logs around it.
"""
from __future__ import annotations

import logging
import time
from typing import Callable

from .client import OllamaClient, LLMError
from .preprocessing import run_pass_a
from .extraction import run_pass_b
from .result import (
    AGroupResult,
    Diagnostics,
    PassAResult,
    PassASegment,
    StageDiagnostic,
)
from ..asr import ASREngine
from ..asr_adapter import AdaptedASR, adapt_asr_result
from ..pathology_schema import ColoStructExtraction, Evidence, OverrideLog

logger = logging.getLogger(__name__)

Cleaner = Callable[[list[dict]], list[dict]]


class AGroupPipelineError(RuntimeError):
    """Pass B failed; no fake extraction is built.

    The object contains only stable diagnostic fields. It deliberately holds
    no reference to the original exception, including via private attributes.
    """

    def __init__(
        self,
        stage: str,
        diagnostics: Diagnostics,
        *,
        cause_type: str | None = None,
    ) -> None:
        super().__init__(f"A-group pipeline failed at stage {stage!r}")
        self.stage = stage
        self.diagnostics = diagnostics
        self.cause_type = cause_type


def _default_cleaner() -> Cleaner:
    """Return the backend cleaner, imported lazily so the dev copy can inject one."""
    try:
        from ..cleanup import clean_transcript
    except ImportError as exc:  # pragma: no cover - exercised after migration
        raise RuntimeError(
            "core.cleanup is unavailable; pass a cleaner callable or run inside "
            "the Colostruct repository."
        ) from exc
    return clean_transcript


def _copy_as_original(clean_segments: list[dict]) -> list[dict]:
    """Build Pass B corrected context when Pass A did not produce corrections."""
    return [
        {"segment_id": str(segment["segment_id"]).strip(), "corrected_text": segment["text"]}
        for segment in clean_segments
    ]


def _build_pass_a_result(
    clean_segments: list[dict],
    corrected_segments: list[dict],
    status: str,
    skip_reason: str | None = None,
) -> PassAResult:
    corrected_by_id = {
        str(segment["segment_id"]).strip(): segment["corrected_text"]
        for segment in corrected_segments
    }
    segments = [
        PassASegment(
            segment_id=str(segment["segment_id"]).strip(),
            original_text=segment["text"],
            corrected_text=corrected_by_id.get(
                str(segment["segment_id"]).strip(), segment["text"]
            ),
            candidates=[],
        )
        for segment in clean_segments
    ]
    return PassAResult(segments=segments, status=status, skip_reason=skip_reason)


def _to_backend_override_logs(logs: list[dict]) -> list[OverrideLog]:
    """Convert Pass A's checked logs into the backend ``OverrideLog`` contract.

    ``doctor_self_correction`` candidates are never converted here; only the
    verified temporal-override records produced by Pass A are accepted.
    """
    converted: list[OverrideLog] = []
    for log in logs:
        old = log["old_evidence"]
        new = log["new_evidence"]
        converted.append(
            OverrideLog(
                field_name=log["field_name"],
                old_evidence=Evidence(
                    segment_id=str(old["segment_id"]),
                    quote=old["quote"],
                ),
                new_evidence=Evidence(
                    segment_id=str(new["segment_id"]),
                    quote=new["quote"],
                ),
            )
        )
    return converted


def _elapsed_ms(started: float) -> int:
    return max(0, int(round((time.perf_counter() - started) * 1000)))


def _run_pipeline(
    audio_path: str | None = None,
    *,
    clean_segments: list[dict] | None = None,
    asr_engine: ASREngine | None = None,
    cleaner: Cleaner | None = None,
    client: OllamaClient | None = None,
    skip_pass_a: bool = False,
    pass_a_fallback: bool = True,
    raw_pass_b_errors: bool = False,
) -> AGroupResult:
    """Run the A-group pipeline and return the full ``AGroupResult``.

    Exactly one of ``audio_path`` / ``clean_segments`` must be supplied:

    * ``audio_path``: ASR → adapter → backend cleanup → Pass A → Pass B;
    * ``clean_segments``: segments are already cleaned; ASR is skipped (this is
      the compatibility path used by :func:`extract_clinical_info`).

    ASR failures raise :class:`~core.asr_adapter.ASRIntegrationError`; ASR with
    no usable speech raises :class:`~core.asr_adapter.NoSpeechError`. In both
    cases no ``AGroupResult`` is fabricated.

    Pass A failure is recorded in ``diagnostics`` and Pass B still receives the
    full original ``clean_segments`` (P2 D13). Pass B failure raises
    :class:`AGroupPipelineError` carrying the diagnostics.
    """
    if (audio_path is None) == (clean_segments is None):
        raise ValueError("supply exactly one of audio_path or clean_segments")

    total_started = time.perf_counter()
    adapted: AdaptedASR | None = None

    if audio_path is not None:
        engine = asr_engine or ASREngine()
        asr_result = engine.transcribe(audio_path)
        adapted = adapt_asr_result(asr_result)
        logger.info("ASR status=%s warnings=%d", adapted.status, len(adapted.warnings))
        clean_fn = cleaner or _default_cleaner()
        clean_segments = clean_fn(adapted.segments)

    if not clean_segments:
        raise ValueError("clean_segments must not be empty")

    model_client = client or OllamaClient()
    stages: list[StageDiagnostic] = []

    if skip_pass_a:
        corrected_segments = _copy_as_original(clean_segments)
        pass_a_status = "skipped"
        skip_reason = "Pass A skipped by caller"
        pass_a_warnings = [skip_reason]
        override_logs: list[dict] = []
        pass_a_started = time.perf_counter()
    else:
        pass_a_started = time.perf_counter()
        pass_a_warnings = []
        try:
            pass_a = run_pass_a(clean_segments, model_client)
            corrected_segments = pass_a["corrected_segments"]
            override_logs = list(pass_a.get("override_logs") or [])
            pass_a_status = "success"
            skip_reason = None
        except LLMError as exc:  # expected LLM failure; input/typing errors propagate
            if not pass_a_fallback:
                raise
            logger.warning(
                "Pass A failed (%s); continuing with original text",
                type(exc).__name__,
            )
            corrected_segments = _copy_as_original(clean_segments)
            override_logs = []
            pass_a_status = "failed"
            skip_reason = None
            pass_a_warnings = [type(exc).__name__]

    stages.append(
        StageDiagnostic(
            stage="pass_a",
            status=pass_a_status,
            elapsed_ms=_elapsed_ms(pass_a_started),
            warnings=pass_a_warnings,
            error_code="PASS_A_FAILED" if pass_a_status == "failed" else None,
        )
    )
    pass_a_result = _build_pass_a_result(
        clean_segments,
        corrected_segments,
        pass_a_status,
        skip_reason=skip_reason,
    )

    pass_b_started = time.perf_counter()
    pass_b_cause_type: str | None = None
    diagnostics: Diagnostics | None = None
    try:
        extraction = run_pass_b(
            original_clean_segments=clean_segments,
            corrected_segments=corrected_segments,
            client=model_client,
        )
    except Exception as exc:
        if raw_pass_b_errors:
            # Historical API: propagate the original exception object locally.
            raise
        pass_b_cause_type = type(exc).__name__
        stages.append(
            StageDiagnostic(
                stage="pass_b",
                status="failed",
                elapsed_ms=_elapsed_ms(pass_b_started),
                warnings=[pass_b_cause_type],
                error_code="PASS_B_FAILED",
            )
        )
        diagnostics = Diagnostics(
            stages=stages,
            total_elapsed_ms=_elapsed_ms(total_started),
        )

    if pass_b_cause_type is not None:
        # Raised outside the except block so Python does not attach the raw
        # exception as __context__; only the type name is retained.
        raise AGroupPipelineError(
            "pass_b",
            diagnostics,
            cause_type=pass_b_cause_type,
        ) from None

    stages.append(
        StageDiagnostic(
            stage="pass_b",
            status="success",
            elapsed_ms=_elapsed_ms(pass_b_started),
        )
    )

    extraction.override_logs = _to_backend_override_logs(override_logs)
    diagnostics = Diagnostics(
        stages=stages,
        total_elapsed_ms=_elapsed_ms(total_started),
    )

    return AGroupResult(
        extraction=extraction,
        pass_a_result=pass_a_result,
        field_uncertainties={},
        diagnostics=diagnostics,
    )


def extract_clinical_info_result(
    audio_path: str | None = None,
    *,
    clean_segments: list[dict] | None = None,
    asr_engine: ASREngine | None = None,
    cleaner: Cleaner | None = None,
    client: OllamaClient | None = None,
    skip_pass_a: bool = False,
) -> AGroupResult:
    """Run the A-group pipeline and return the full ``AGroupResult``.

    Exactly one of ``audio_path`` / ``clean_segments`` must be supplied.

    Pass A ``LLMError`` is recoverable: it is recorded in ``diagnostics`` and
    Pass B continues with the full original ``clean_segments`` (P2 D13).
    Input/validation errors (``ValueError``) and unexpected exceptions are not
    recoverable and propagate unchanged. Pass B failure raises
    :class:`AGroupPipelineError` carrying the diagnostics.
    """
    return _run_pipeline(
        audio_path,
        clean_segments=clean_segments,
        asr_engine=asr_engine,
        cleaner=cleaner,
        client=client,
        skip_pass_a=skip_pass_a,
    )


def extract_clinical_info(
    clean_segments: list[dict],
    client: OllamaClient | None = None,
) -> ColoStructExtraction:
    """Historical entry point, preserving the original exception behaviour.

    The pre-P4-2 implementation had no try/except: Pass A and Pass B exceptions
    propagated unchanged. This wrapper disables the new Pass A fallback and
    re-raises Pass B's original exception, so existing callers keep their
    exception contract while override logs are still preserved.
    """
    result = _run_pipeline(
        clean_segments=clean_segments,
        client=client,
        pass_a_fallback=False,
        raw_pass_b_errors=True,
    )
    return result.extraction


__all__ = [
    "AGroupPipelineError",
    "extract_clinical_info",
    "extract_clinical_info_result",
]
