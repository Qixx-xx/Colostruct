"""Pydantic v2 data contracts for the ColoStruct pathology extraction pipeline.

This module is the single source of truth for the JSON contract exchanged
between the LLM extraction pass, the deterministic back-end rule engine, and
the Streamlit review UI.  It deliberately separates *what the model observed*
from *what the system concluded*:

* The **LLM** supplies ``value``, ``evidence.segment_id``, ``evidence.quote``,
  and the ``override_logs`` entries.
* The **back-end rule engine** maps each ``segment_id`` to the segment offset
  table produced by :mod:`core.audio_merge`, fills ``evidence.start`` and
  ``evidence.end``, assigns the final ``status``, writes ``validation_msg``,
  and decides ``has_block``.

The LLM must not emit absolute audio timestamps.  It is also not required to
emit ``status``; ``StatusEnum.ABSENT`` is the fail-safe default until the rule
engine has audited the field.

Contract invariants
-------------------
* ``ColoStructExtraction.fields`` always contains all
  :data:`PATHOLOGY_FIELD_KEYS`, even when the LLM omits a field or returns a
  truncated object.
* ``Evidence.segment_id`` and ``Evidence.quote`` are required.  Malformed
  evidence entries are dropped rather than aborting the whole extraction.
* ``Evidence.start`` / ``Evidence.end`` are optional and remain ``None`` until
  the back-end enrichment step.
* Unknown status strings become ``StatusEnum.FLAGGED`` (except known
  ``not_mentioned`` aliases, which become ``StatusEnum.ABSENT``) so that a
  bad model value is reviewed instead of silently trusted.
* Unknown top-level keys and unknown field keys are ignored.  That keeps a
  slightly noisy LLM response parseable; schema conformance is audited later
  by :mod:`core.validate`.

This module supersedes the inline-timestamp examples in the PRD and the
v0.3 technical design; the current team contract is ``segment_id`` + ``quote``
in, timestamps out.

Example
-------
>>> extraction = ColoStructExtraction.model_validate(
...     {
...         "fields": {
...             "tumour_site": {
...                 "value": "mid rectum",
...                 "evidence": [
...                     {"segment_id": "seg-003", "quote": "mid rectum"}
...                 ],
...             }
...         }
...     }
... )
>>> len(extraction.fields)
15
>>> extraction.fields["tumour_site"].status
<StatusEnum.ABSENT: 'absent'>
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Final

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

__all__ = [
    "PATHOLOGY_FIELD_KEYS",
    "ColoStructExtraction",
    "Evidence",
    "FieldModel",
    "OverrideLog",
    "StatusEnum",
]


#: Canonical field keys, in the clinical review order defined by the client's
#: colorectal cancer reporting checklist.
#:
#: The order is intentionally stable: the review UI groups fields 1-6 as
#: tumour & specimen, 7-11 as histology, 12-13 as nodes & deposits, and 14-15
#: as margins.  Do not reorder this tuple without updating the UI.
PATHOLOGY_FIELD_KEYS: Final[tuple[str, ...]] = (
    # Tumour and specimen (1-6)
    "tumour_site",
    "operative_procedure",
    "tumour_dimension",
    "tumour_perforation",
    "relation_to_anterior_peritoneal_reflection",
    "plane_of_mesorectal_excision",
    # Histology (7-11)
    "histological_tumour_type",
    "histological_tumour_grade",
    "extent_of_invasion",
    "lymphatic_and_venous_invasion",
    "perineural_invasion",
    # Nodes and deposits (12-13)
    "lymph_node_status",
    "tumour_deposits",
    # Margins (14-15)
    "proximal_and_distal_margins",
    "circumferential_margin",
)


def _as_float(value: Any) -> float | None:
    """Convert a JSON scalar to ``float`` when possible.

    Args:
        value: A candidate timestamp value.

    Returns:
        The numeric value as ``float``, or ``None`` when the value is missing,
        boolean, or not parseable as a number.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _is_valid_segment_id(value: Any) -> bool:
    """Return whether ``value`` is a usable segment identifier.

    Segment ids are strings in the canonical contract, but numeric ids from a
    sloppy model response are accepted because they can be mapped to the
    segment offset table just as reliably.
    """
    if isinstance(value, str):
        return bool(value.strip())
    return isinstance(value, (int, float)) and not isinstance(value, bool)


class StatusEnum(str, Enum):
    """Final review status of one pathology field.

    The status is owned by the deterministic rule engine.  The LLM may omit
    it entirely; in that case :attr:`ABSENT` is used as a safe placeholder
    until the rule engine audits the field.

    Attributes:
        POPULATED: The field has a value and at least one evidence span that
            resolves to the transcript.
        ABSENT: The field was not mentioned in the dictation.  ``value``
            should be ``None``; the UI renders ``[not mentioned]``.
        FLAGGED: The field needs human review because the evidence is missing,
            contradictory, low-confidence, or conflicts with another
            statement.  A flagged field is not silently trusted.
    """

    POPULATED = "populated"
    ABSENT = "absent"
    FLAGGED = "flagged"


class _ColoStructModel(BaseModel):
    """Shared Pydantic configuration for every ColoStruct contract model.

    The configuration favours tolerant parsing of imperfect LLM JSON while
    keeping assignment validation on: the back-end enriches evidence objects
    after construction, so invalid mutations should fail immediately.

    Attributes:
        model_config: ``extra="ignore"`` drops unknown LLM keys;
            ``str_strip_whitespace`` normalises quotes and values;
            ``validate_assignment`` protects later back-end mutations;
            ``populate_by_name`` allows both field names and aliases.
    """

    model_config = ConfigDict(
        extra="ignore",
        str_strip_whitespace=True,
        validate_assignment=True,
        populate_by_name=True,
        use_enum_values=False,
    )


class Evidence(_ColoStructModel):
    """A transcript fragment that supports one pathology field.

    The LLM provides only ``segment_id`` and ``quote``.  The back-end resolves
    the segment against the stitched-audio offset table and then fills
    ``start`` and ``end`` with global seconds in the stitched timeline.

    Attributes:
        segment_id: Identifier of the ASR/upload segment, for example
            ``"seg-003"``.  Required and non-empty.
        quote: Verbatim transcript text that supports the field.  Required and
            non-empty.  The audit layer later checks that this quote really
            occurs in the referenced segment.
        start: Global start time in seconds, filled by the back-end.  ``None``
            until enrichment; the LLM must not generate it.
        end: Global end time in seconds, filled by the back-end.  ``None``
            until enrichment; the LLM must not generate it.

    Examples:
        >>> Evidence(segment_id="seg-003", quote="mid rectum")
        Evidence(segment_id='seg-003', quote='mid rectum', start=None, end=None)
    """

    segment_id: str = Field(
        ...,
        min_length=1,
        description=(
            "Transcript segment identifier supplied by the LLM; the back-end "
            "maps it to a global audio offset."
        ),
    )
    quote: str = Field(
        ...,
        min_length=1,
        description=(
            "Verbatim transcript quote supporting the field; checked against "
            "the referenced segment by the evidence audit."
        ),
    )
    start: float | None = Field(
        default=None,
        description=(
            "Global start time in the stitched audio, in seconds. Filled by "
            "the back-end rule engine; the LLM must not emit it."
        ),
    )
    end: float | None = Field(
        default=None,
        description=(
            "Global end time in the stitched audio, in seconds. Filled by the "
            "back-end rule engine; the LLM must not emit it."
        ),
    )

    @field_validator("segment_id", mode="before")
    @classmethod
    def _coerce_segment_id(cls, value: Any) -> Any:
        """Accept a numeric segment id from a sloppy model response.

        Segment ids are strings in the contract, but a model occasionally
        emits ``0`` or ``3``.  Converting numbers (but not booleans) keeps the
        response parseable without weakening the required/non-empty rule.
        """
        if isinstance(value, bool):
            return value
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        if isinstance(value, (int, float)):
            return str(value)
        return value

    @model_validator(mode="before")
    @classmethod
    def _order_span(cls, data: Any) -> Any:
        """Swap reversed ``start``/``end`` values supplied together.

        A reversed span is almost always an offset-arithmetic bug.  Swapping
        when both values arrive in the same payload preserves the covered
        interval so the enriched evidence remains usable; the audit layer
        should still compare the span against the segment boundaries.
        """
        if not isinstance(data, dict):
            return data

        start = _as_float(data.get("start"))
        end = _as_float(data.get("end"))
        if start is not None and end is not None and end < start:
            return {**data, "start": end, "end": start}
        return data


class FieldModel(_ColoStructModel):
    """The value, evidence, and review state of one pathology field.

    A field is intentionally tolerant at parse time:

    * an empty value, ``None``, or the display sentinel ``[not mentioned]``
      becomes ``None``;
    * malformed evidence entries (missing ``segment_id`` or ``quote``) are
      dropped, because one bad fragment should not discard the whole report;
    * an unknown status string becomes ``FLAGGED`` so a human reviews it;
    * ``validation_msg`` is written by the back-end audit, not by the LLM.

    Attributes:
        value: Extracted value, or ``None`` when the field was not mentioned.
            Numeric values are coerced to strings so JSON numbers do not break
            parsing.
        evidence: Supporting transcript fragments.  May be empty for an
            ``ABSENT`` field, but a ``POPULATED`` field should have at least
            one entry after the rule-engine audit.
        status: Final review status.  Defaults to ``ABSENT`` because an
            unverified field must never be presented as populated.
        validation_msg: Human-readable back-end audit message, for example
            ``"evidence quote not found in segment"`` or
            ``"conflicting later statement"``.  ``None`` when no issue exists.
    """

    value: str | None = Field(
        default=None,
        description=(
            "Extracted clinical value, or None when the field was not "
            "mentioned. The display sentinel '[not mentioned]' is normalised "
            "to None."
        ),
    )
    evidence: list[Evidence] = Field(
        default_factory=list,
        description=(
            "Transcript fragments supporting the value. The LLM supplies "
            "segment_id and quote; the back-end supplies start and end."
        ),
    )
    status: StatusEnum = Field(
        default=StatusEnum.ABSENT,
        description=(
            "Final review status owned by the back-end rule engine. The LLM "
            "may omit it; ABSENT is the fail-safe default."
        ),
    )
    validation_msg: str | None = Field(
        default=None,
        description=(
            "Back-end validation message, such as an evidence mismatch or a "
            "temporal-order error. None when the field passed the audit."
        ),
    )

    @field_validator("value", mode="before")
    @classmethod
    def _normalise_value(cls, value: Any) -> str | None:
        """Normalise an LLM-provided value without inventing clinical content.

        ``None``, whitespace, and the UI sentinel ``[not mentioned]`` become
        ``None`` (the canonical representation of an absent field).  Numeric
        JSON scalars are converted to strings; containers are rejected as
        unsupported rather than stringified into meaningless text.
        """
        if value is None:
            return None

        if isinstance(value, bool):
            return "true" if value else "false"

        if isinstance(value, (int, float)):
            return str(value)

        if not isinstance(value, str):
            return None

        cleaned = value.strip()
        if not cleaned:
            return None
        if cleaned.casefold() in {"[not mentioned]", "not mentioned"}:
            return None
        return cleaned

    @field_validator("evidence", mode="before")
    @classmethod
    def _normalise_evidence(cls, value: Any) -> list[Any]:
        """Drop malformed evidence entries instead of failing the extraction.

        Accepts a single evidence object as well as a list.  Entries that are
        not ``Evidence`` instances or dicts containing both ``segment_id`` and
        ``quote`` are discarded; the audit layer will flag the resulting field
        if it claims to be populated without usable evidence.
        """
        if value is None:
            return []
        if isinstance(value, (Evidence, dict)):
            value = [value]
        if not isinstance(value, (list, tuple)):
            return []

        normalised: list[Any] = []
        for item in value:
            if isinstance(item, Evidence):
                normalised.append(item)
            elif isinstance(item, dict):
                segment_id = item.get("segment_id")
                quote = item.get("quote")
                if (
                    _is_valid_segment_id(segment_id)
                    and isinstance(quote, str)
                    and quote.strip()
                ):
                    normalised.append(item)
        return normalised

    @field_validator("status", mode="before")
    @classmethod
    def _coerce_status(cls, value: Any) -> Any:
        """Map unknown statuses to ``FLAGGED`` and known aliases to ``ABSENT``.

        The rule engine normally supplies the status.  This validator only
        protects the parser from a noisy or outdated model response.
        """
        if value is None or value == "":
            return StatusEnum.ABSENT
        if isinstance(value, StatusEnum):
            return value
        if isinstance(value, str):
            normalised = value.strip().lower().replace(" ", "_").replace("-", "_")
            if normalised in {"not_mentioned", "not_mentioned_field"}:
                return StatusEnum.ABSENT
            try:
                return StatusEnum(normalised)
            except ValueError:
                return StatusEnum.FLAGGED
        return StatusEnum.FLAGGED

    @field_validator("validation_msg", mode="before")
    @classmethod
    def _normalise_validation_msg(cls, value: Any) -> str | None:
        """Turn an empty audit message into ``None``."""
        if value is None:
            return None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
        if not isinstance(value, str):
            return None
        cleaned = value.strip()
        return cleaned or None


class OverrideLog(_ColoStructModel):
    """One doctor's change-of-mind event for a single pathology field.

    Temporal override is the rule that the later statement wins.  The log
    preserves both sides so the audit layer can replay the decision and the
    doctor can see exactly what was replaced.

    Attributes:
        field_name: Canonical field key affected by the override, for example
            ``"circumferential_margin"``.
        old_evidence: The earlier statement that was superseded.
        new_evidence: The later statement that now wins.
    """

    field_name: str = Field(
        ...,
        min_length=1,
        description=(
            "Canonical pathology field key affected by the change of mind, "
            "for example 'circumferential_margin'."
        ),
    )
    old_evidence: Evidence = Field(
        ...,
        description="The earlier statement that was replaced.",
    )
    new_evidence: Evidence = Field(
        ...,
        description="The later statement that supersedes the old one.",
    )


def _default_fields() -> dict[str, FieldModel]:
    """Return a fresh mapping containing all 15 fields in ``ABSENT`` state.

    A new mapping and new :class:`FieldModel` instances are created on every
    call so callers cannot accidentally share mutable state.  This is used as
    the default for :attr:`ColoStructExtraction.fields` and as the base that
    the tolerant ``fields`` validator merges partial LLM output into.
    """
    return {key: FieldModel() for key in PATHOLOGY_FIELD_KEYS}


def _has_evidence_payload(value: Any) -> bool:
    """Return whether ``value`` can produce a non-empty :class:`Evidence`.

    Args:
        value: A candidate evidence value from parsed JSON.

    Returns:
        ``True`` when the value is already an :class:`Evidence` instance or a
        dict carrying a usable segment id and a non-empty quote.
    """
    if isinstance(value, Evidence):
        return True
    if not isinstance(value, dict):
        return False
    segment_id = value.get("segment_id")
    quote = value.get("quote")
    return (
        _is_valid_segment_id(segment_id)
        and isinstance(quote, str)
        and bool(quote.strip())
    )


class ColoStructExtraction(_ColoStructModel):
    """Top-level extraction result for one colorectal pathology case.

    The model is the boundary between the LLM and the rest of ColoStruct.  It
    is deliberately forgiving about missing pieces: a response that contains
    only three fields still yields a complete 15-key structure, with the other
    twelve fields in ``ABSENT`` state.  The back-end rule engine then audits
    and, where appropriate, reclassifies each field.

    Attributes:
        fields: Mapping from canonical field key to :class:`FieldModel`.
            Always contains all :data:`PATHOLOGY_FIELD_KEYS` after validation.
        override_logs: Change-of-mind records produced by the LLM
            preprocessing/extraction pass.  Malformed records are dropped.
        has_block: Initial back-end export decision.  The UI disables export
            while it is true; after a doctor completes manual review, the
            front-end may clear it without another back-end call.  The LLM
            should not set it; the default is ``False``.

    Examples:
        >>> extraction = ColoStructExtraction()
        >>> len(extraction.fields)
        15
        >>> extraction.fields["tumour_site"].status
        <StatusEnum.ABSENT: 'absent'>
    """

    fields: dict[str, FieldModel] = Field(
        default_factory=_default_fields,
        description=(
            "All 15 pathology fields keyed by canonical name. Missing keys are "
            "filled with ABSENT FieldModel instances during validation."
        ),
    )
    override_logs: list[OverrideLog] = Field(
        default_factory=list,
        validation_alias=AliasChoices("override_logs", "override_log"),
        description=(
            "Temporal-override records: which field changed, the old evidence, "
            "and the new evidence. The legacy key 'override_log' is accepted."
        ),
    )
    has_block: bool = Field(
        default=False,
        description=(
            "Initial back-end export decision: true disables export while a "
            "block-severity issue is open. After manual review the front-end "
            "may clear it without another back-end call. The LLM must not be "
            "trusted to set it."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _wrap_bare_fields(cls, data: Any) -> Any:
        """Accept a bare 15-field mapping as a convenience.

        Some model responses omit the ``{"fields": ...}`` wrapper.  When the
        top level already looks like a field mapping, wrap it so the caller
        does not have to pre-process the response.
        """
        if (
            isinstance(data, dict)
            and "fields" not in data
            and any(key in data for key in PATHOLOGY_FIELD_KEYS)
        ):
            logs = data.get("override_logs", data.get("override_log", []))
            return {
                "fields": data,
                "override_logs": logs,
                "has_block": data.get("has_block", False),
            }
        return data

    @field_validator("fields", mode="before")
    @classmethod
    def _normalise_fields(cls, value: Any) -> dict[str, Any]:
        """Merge partial LLM output into a complete 15-key field mapping.

        Unknown keys are dropped, missing keys receive a default
        :class:`FieldModel`, and shorthand string values become field models
        with that value.  This is the main defence against a truncated or
        slightly malformed extraction response.
        """
        if not isinstance(value, dict):
            return _default_fields()

        normalised: dict[str, Any] = _default_fields()
        for key in PATHOLOGY_FIELD_KEYS:
            if key not in value:
                continue

            raw = value[key]
            if raw is None:
                continue
            if isinstance(raw, FieldModel):
                normalised[key] = raw
            elif isinstance(raw, str):
                normalised[key] = FieldModel(value=raw)
            elif isinstance(raw, dict):
                normalised[key] = raw
            # Unsupported shapes (lists, numbers, booleans) keep the default
            # ABSENT field rather than aborting the whole report.
        return normalised

    @field_validator("override_logs", mode="before")
    @classmethod
    def _normalise_override_logs(cls, value: Any) -> list[Any]:
        """Drop incomplete override records instead of failing the report.

        An override is only useful when it names a field and carries both an
        old and a new evidence payload.  Records missing any of those pieces
        are discarded; the audit layer can still compare the final value with
        the transcript.
        """
        if value is None:
            return []
        if isinstance(value, dict):
            value = [value]
        if not isinstance(value, (list, tuple)):
            return []

        normalised: list[Any] = []
        for item in value:
            if isinstance(item, OverrideLog):
                normalised.append(item)
                continue
            if not isinstance(item, dict):
                continue

            field_name = item.get("field_name")
            if not isinstance(field_name, str) or not field_name.strip():
                continue
            if not _has_evidence_payload(item.get("old_evidence")):
                continue
            if not _has_evidence_payload(item.get("new_evidence")):
                continue
            normalised.append(item)
        return normalised


if __name__ == "__main__":
    # A deliberately partial mock: only three of the fifteen fields are
    # supplied, which exercises the tolerant merge into a complete structure.
    extraction = ColoStructExtraction(
        fields={
            "tumour_site": FieldModel(
                value="mid rectum",
                evidence=[
                    Evidence(
                        segment_id="seg-003",
                        quote="the tumour is in the mid rectum",
                    )
                ],
                status=StatusEnum.POPULATED,
            ),
            "lymph_node_status": FieldModel(
                value="2 of 14 nodes positive",
                evidence=[
                    Evidence(
                        segment_id="seg-007",
                        quote=(
                            "two out of fourteen lymph nodes show metastatic carcinoma"
                        ),
                    )
                ],
                status=StatusEnum.FLAGGED,
                validation_msg="evidence does not match the counted fraction",
            ),
            "circumferential_margin": FieldModel(
                value="1 mm",
                evidence=[
                    Evidence(
                        segment_id="seg-009",
                        quote="circumferential margin is 1 millimetre",
                    )
                ],
                status=StatusEnum.POPULATED,
            ),
        },
        override_logs=[
            OverrideLog(
                field_name="circumferential_margin",
                old_evidence=Evidence(
                    segment_id="seg-008",
                    quote="circumferential margin is 2 millimetres",
                ),
                new_evidence=Evidence(
                    segment_id="seg-009",
                    quote="sorry, circumferential margin is 1 millimetre",
                ),
            )
        ],
    )

    # Demonstrate the back-end enrichment step: the LLM supplied only
    # segment_id + quote, so start/end are filled from the segment offset
    # table here.
    first_site_evidence = extraction.fields["tumour_site"].evidence[0]
    first_site_evidence.start = 12.4
    first_site_evidence.end = 15.1

    print(
        f"fields={len(extraction.fields)} "
        f"override_logs={len(extraction.override_logs)} "
        f"has_block={extraction.has_block}"
    )
    print(extraction.model_dump_json(indent=2))
