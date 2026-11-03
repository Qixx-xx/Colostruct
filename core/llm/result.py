"""A-group result contracts (schema_version ``a_group_result/v1``).

This module is owned by A-group. It wraps the backend's
:class:`core.pathology_schema.ColoStructExtraction` and adds A-only artefacts:
per-segment Pass A analysis, field-level uncertainty, and stage diagnostics.

The backend keeps consuming ``AGroupResult.extraction`` only; the other four
parts are A-group internal and are not part of the backend schema.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..pathology_schema import PATHOLOGY_FIELD_KEYS, ColoStructExtraction

#: Status of one A-group stage.
StageStatus = Literal["success", "partial", "failed", "skipped"]

#: A-group stages recorded in ``Diagnostics``. ASR is intentionally excluded:
#: ASR is an independent interface and records its own status in ``ASRResult``.
StageName = Literal["pass_a", "pass_b"]

#: Field-level uncertainty level.
UncertaintyLevel = Literal["low", "medium", "high"]

#: Kind of AI-proposed correction. This is a candidate category, not a
#: confirmed clinical fact.
CandidateType = Literal["normalization", "suspected_asr_error", "doctor_self_correction"]

#: How risky it is to apply the candidate without human review.
RiskLevel = Literal["low", "medium", "high"]

__all__ = [
    "StageStatus",
    "StageName",
    "UncertaintyLevel",
    "CandidateType",
    "RiskLevel",
    "CorrectionCandidate",
    "PassASegment",
    "PassAResult",
    "FieldUncertainty",
    "StageDiagnostic",
    "Diagnostics",
    "AGroupResult",
]


class _AStageModel(BaseModel):
    """Shared configuration for A-group contract models.

    ``extra="forbid"`` is deliberate: these models are A-group owned and a
    misspelled field name should fail fast. It does not change the backend's
    ``ColoStructExtraction`` configuration.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class CorrectionCandidate(_AStageModel):
    """One AI-proposed ASR correction.

    ``candidate_type`` classifies the proposal; it does **not** assert a
    confirmed medical fact. In particular ``doctor_self_correction`` means the
    model believes the doctor corrected themselves in the audio; it must NOT be
    converted into ``core.pathology_schema.OverrideLog``. Only Pass A may emit
    real override logs, after its own verbatim and ordering checks.

    ``evidence_segment_ids`` must reference the original ``clean_segments``.
    This module only enforces the shape; the existence check across objects is
    deferred to the Pass A implementation.

    ``confidence`` is the model's self-reported number on a 0-1 scale. It is
    **not** a calibrated probability and must not be presented as one.
    """

    candidate_type: CandidateType
    risk_level: RiskLevel
    original_span: str = Field(min_length=1)
    suggested_span: str = Field(min_length=1)
    evidence_segment_ids: list[str]
    reason: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class PassASegment(_AStageModel):
    """Pass A analysis for exactly one input segment."""

    segment_id: str = Field(min_length=1)
    original_text: str
    corrected_text: str
    candidates: list[CorrectionCandidate] = Field(default_factory=list)


class PassAResult(_AStageModel):
    """Per-segment Pass A output.

    ``segments`` mirrors the input order one-to-one. A skipped Pass A still
    returns this object with ``segments=[]``, ``status="skipped"`` and a
    non-empty ``skip_reason``; it is never ``None``.
    """

    segments: list[PassASegment] = Field(default_factory=list)
    status: StageStatus = "success"
    skip_reason: str | None = None

    @model_validator(mode="after")
    def _skipped_requires_reason(self) -> "PassAResult":
        """Require a reason when Pass A did not run."""
        if self.status == "skipped" and not (self.skip_reason or "").strip():
            raise ValueError("skip_reason is required when status is 'skipped'")
        return self


class FieldUncertainty(_AStageModel):
    """A-group-only field-level uncertainty.

    Stored outside ``ColoStructExtraction`` so the backend schema is untouched.
    """

    level: UncertaintyLevel
    reason: str = Field(min_length=1)
    competing_values: list[str] = Field(default_factory=list)


class StageDiagnostic(_AStageModel):
    """Status of one A-group stage (``pass_a`` or ``pass_b``)."""

    stage: StageName
    status: StageStatus
    elapsed_ms: int = Field(default=0, ge=0)
    attempts: int = Field(default=1, ge=1)
    warnings: list[str] = Field(default_factory=list)
    error_code: str | None = None


class Diagnostics(_AStageModel):
    """Ordered diagnostics for the A-group stages of one run."""

    stages: list[StageDiagnostic] = Field(default_factory=list)
    total_elapsed_ms: int = Field(default=0, ge=0)


class AGroupResult(_AStageModel):
    """Top-level A-group output.

    ``extraction`` is the only part consumed by the backend and is always
    required: ASR/LLM failures are reported before this object is built, so a
    missing or fabricated extraction is never acceptable.
    """

    extraction: ColoStructExtraction
    pass_a_result: PassAResult
    field_uncertainties: dict[str, FieldUncertainty] = Field(default_factory=dict)
    diagnostics: Diagnostics
    schema_version: Literal["a_group_result/v1"] = "a_group_result/v1"

    @property
    def has_failed_stage(self) -> bool:
        """Auxiliary signal; not the sole basis for blocking the pipeline.

        Callers must also check which stage failed, whether ``extraction`` is
        usable, and the diagnostics as a whole.
        """
        return any(stage.status == "failed" for stage in self.diagnostics.stages)

    @field_validator("field_uncertainties")
    @classmethod
    def _only_known_fields(
        cls, value: dict[str, FieldUncertainty]
    ) -> dict[str, FieldUncertainty]:
        """Reject uncertainty keys that are not canonical pathology fields."""
        unknown = set(value) - set(PATHOLOGY_FIELD_KEYS)
        if unknown:
            raise ValueError("unknown field keys: " + ", ".join(sorted(unknown)))
        return value
