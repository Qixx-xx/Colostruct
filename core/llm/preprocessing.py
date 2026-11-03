"""Pass A: candidate transcript correction and explicit temporal overrides."""
from __future__ import annotations

from typing import Any

from .client import OllamaClient, LLMError
from .parsing import require_object, validate_segment_list
from .prompts import PASS_A_SYSTEM, pass_a_user
from ..pathology_schema import PATHOLOGY_FIELD_KEYS


def run_pass_a(
    clean_segments: list[dict],
    client: OllamaClient,
) -> dict[str, Any]:
    if not clean_segments:
        raise ValueError("clean_segments must not be empty")

    ids = [str(s.get("segment_id", "")).strip() for s in clean_segments]
    if any(not item for item in ids) or len(set(ids)) != len(ids):
        raise ValueError("Every input segment must have a unique non-empty segment_id.")
    for segment in clean_segments:
        if not isinstance(segment.get("text"), str):
            raise ValueError("Every segment must contain text as a string.")

    raw = require_object(
        client.generate_json(system=PASS_A_SYSTEM, user=pass_a_user(clean_segments)),
        "Pass A response",
    )
    corrected = validate_segment_list(raw.get("corrected_segments"), set(ids), "corrected_segments")
    if [x["segment_id"] for x in corrected] != ids:
        raise LLMError("Pass A must return every input segment exactly once and in original order.")

    logs = raw.get("override_logs", [])
    if not isinstance(logs, list):
        raise LLMError("Pass A override_logs must be a list.")

    positions = {segment_id: i for i, segment_id in enumerate(ids)}
    allowed_fields = set(PATHOLOGY_FIELD_KEYS)
    checked_logs = []
    source_by_id = {str(s["segment_id"]): s["text"] for s in clean_segments}
    for i, item in enumerate(logs):
        if not isinstance(item, dict):
            raise LLMError(f"override_logs[{i}] must be an object.")
        field_name = item.get("field_name")
        old = item.get("old_evidence")
        new = item.get("new_evidence")
        if field_name not in allowed_fields or not isinstance(old, dict) or not isinstance(new, dict):
            raise LLMError(f"override_logs[{i}] has an invalid field or evidence object.")
        old_id, new_id = str(old.get("segment_id", "")), str(new.get("segment_id", ""))
        old_quote, new_quote = old.get("quote"), new.get("quote")
        if old_id not in positions or new_id not in positions:
            raise LLMError(f"override_logs[{i}] references an unknown segment.")
        if positions[new_id] <= positions[old_id]:
            raise LLMError(f"override_logs[{i}] must point to a later segment.")
        if not isinstance(old_quote, str) or old_quote not in source_by_id[old_id]:
            raise LLMError(f"override_logs[{i}] old quote is not verbatim source text.")
        if not isinstance(new_quote, str) or new_quote not in source_by_id[new_id]:
            raise LLMError(f"override_logs[{i}] new quote is not verbatim source text.")
        checked_logs.append({
            "field_name": field_name,
            "old_evidence": {"segment_id": old_id, "quote": old_quote},
            "new_evidence": {"segment_id": new_id, "quote": new_quote},
        })

    return {"corrected_segments": corrected, "override_logs": checked_logs}
