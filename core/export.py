"""Export audited ColoStruct extractions as Markdown or JSON.

The Markdown artifact is intentionally human-facing: it starts with the
mandatory AI-assisted draft watermark, renders the 15-field checklist as a
table, and lists temporal-override records underneath.  JSON export is the
machine-facing form and preserves the complete Pydantic payload.
"""

from __future__ import annotations

from typing import Final

if __package__:
    from .pathology_schema import (
        PATHOLOGY_FIELD_KEYS,
        ColoStructExtraction,
        Evidence,
        FieldModel,
        OverrideLog,
        StatusEnum,
    )
else:  # pragma: no cover - exercised when running ``python core/export.py``
    from pathology_schema import (
        PATHOLOGY_FIELD_KEYS,
        ColoStructExtraction,
        Evidence,
        FieldModel,
        OverrideLog,
        StatusEnum,
    )

__all__ = ["AI_WATERMARK", "export_report"]

#: Mandatory first line of every exported Markdown report.
AI_WATERMARK: Final[str] = (
    "> ⚠️ AI-assisted draft — 本文档由 AI 辅助生成，必须经医生审核后方可使用。"
)


def _md_cell(value: str) -> str:
    """Escape a value for a Markdown table cell.

    Pipes would split a cell and raw newlines would break the table row, so
    both are converted to Markdown-safe forms.
    """
    return (
        value.replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("|", "\\|")
        .replace("\n", "<br>")
    )


def _status_value(status: StatusEnum) -> str:
    """Return the enum's wire value (``populated``/``absent``/``flagged``)."""
    return status.value if isinstance(status, StatusEnum) else str(status)


def _format_evidence(evidence: Evidence) -> str:
    """Render one evidence item for an override-log table cell."""
    timestamp = ""
    if evidence.start is not None and evidence.end is not None:
        timestamp = f" ({evidence.start:.2f}s–{evidence.end:.2f}s)"
    return f"`{evidence.segment_id}`{timestamp}: “{evidence.quote}”"


def _render_markdown(llm_result: ColoStructExtraction) -> str:
    """Build the human-readable Markdown export."""
    lines = [
        AI_WATERMARK,
        "",
        "| Field | Value | Status | Validation |",
        "| --- | --- | --- | --- |",
    ]

    for field_key in PATHOLOGY_FIELD_KEYS:
        field = llm_result.fields.get(field_key)
        if field is None:
            continue
        lines.append(
            "| `{field}` | {value} | {status} | {validation} |".format(
                field=field_key,
                value=_md_cell(field.value or "[not mentioned]"),
                status=_status_value(field.status),
                validation=_md_cell(field.validation_msg or ""),
            )
        )

    if llm_result.override_logs:
        lines.extend(
            [
                "",
                "## Override Logs / 改口记录",
                "",
                "| Field | Old Evidence | New Evidence |",
                "| --- | --- | --- |",
            ]
        )
        for log in llm_result.override_logs:
            field_cell = _md_cell(log.field_name)
            old_cell = _md_cell(_format_evidence(log.old_evidence))
            new_cell = _md_cell(_format_evidence(log.new_evidence))
            lines.append(f"| `{field_cell}` | {old_cell} | {new_cell} |")

    return "\n".join(lines)


def export_report(
    llm_result: ColoStructExtraction,
    format_type: str = "markdown",
) -> str:
    """Export an audited extraction as Markdown or JSON.

    Args:
        llm_result: Audited extraction, normally the object returned by
            :func:`core.validate.audit_extraction`.
        format_type: ``"markdown"``/``"md"`` for the human-readable report, or
            ``"json"`` for ``model_dump_json(indent=2)``.

    Returns:
        The exported document as a string.

    Raises:
        ValueError: If ``format_type`` is not a supported format.
    """
    normalized = format_type.strip().lower()

    if normalized in {"markdown", "md"}:
        return _render_markdown(llm_result)
    if normalized == "json":
        return llm_result.model_dump_json(indent=2)

    raise ValueError(
        f"Unsupported export format: {format_type!r}; expected 'markdown' or 'json'"
    )


if __name__ == "__main__":
    sample = ColoStructExtraction(
        fields={
            "tumour_dimension": FieldModel(
                value="3 cm",
                evidence=[
                    Evidence(
                        segment_id="seg-001",
                        quote="大概 3 cm",
                        start=0.0,
                        end=2.5,
                    )
                ],
                status=StatusEnum.POPULATED,
            ),
            "lymph_node_status": FieldModel(
                value="2/14",
                evidence=[
                    Evidence(
                        segment_id="seg-003",
                        quote="淋巴結 2/14 有轉移",
                        start=5.0,
                        end=7.0,
                    )
                ],
                status=StatusEnum.FLAGGED,
                validation_msg="证据匹配失败：原文片段中未找到该引用",
            ),
            "proximal_and_distal_margins": FieldModel(
                value="5 cm",
                evidence=[
                    Evidence(
                        segment_id="seg-002",
                        quote="遠端切緣 5 cm",
                        start=2.5,
                        end=5.0,
                    )
                ],
                status=StatusEnum.FLAGGED,
                validation_msg="时序异常：覆盖动作的时间顺序错误",
            ),
        },
        override_logs=[
            OverrideLog(
                field_name="proximal_and_distal_margins",
                old_evidence=Evidence(
                    segment_id="seg-003",
                    quote="遠端切緣 1 cm",
                    start=5.0,
                    end=7.0,
                ),
                new_evidence=Evidence(
                    segment_id="seg-002",
                    quote="遠端切緣 5 cm",
                    start=2.5,
                    end=5.0,
                ),
            )
        ],
        has_block=True,
    )

    markdown = export_report(sample, "markdown")
    json_text = export_report(sample, "json")

    assert markdown.startswith(AI_WATERMARK)
    assert "| Field | Value | Status | Validation |" in markdown
    assert "## Override Logs / 改口记录" in markdown
    assert '"fields"' in json_text

    # Keep the console smoke test ASCII-only so it also runs on legacy Windows
    # code pages; callers can print the returned strings with UTF-8 themselves.
    print(f"Markdown export: {len(markdown)} characters")
    print(f"JSON export: {len(json_text)} characters")
    print("All export assertions passed.")
