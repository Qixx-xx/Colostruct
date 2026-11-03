"""Pass B: extraction of the fixed 15-field pathology structure."""
from __future__ import annotations

from typing import Any

from .client import OllamaClient, LLMError
from .parsing import require_object
from .prompts import PASS_B_SYSTEM, pass_b_user
from ..pathology_schema import (
    PATHOLOGY_FIELD_KEYS,
    ColoStructExtraction,
)


def run_pass_b(
    original_clean_segments: list[dict],
    corrected_segments: list[dict],
    client: OllamaClient,
) -> ColoStructExtraction:
    raw = require_object(
        client.generate_json(
            system=PASS_B_SYSTEM,
            user=pass_b_user(original_clean_segments, corrected_segments),
        ),
        "Pass B response",
    )
    fields = raw.get("fields")
    if not isinstance(fields, dict):
        raise LLMError("Pass B response must contain a 'fields' object.")

    # Ignore unknown keys, but fail if the model omits canonical keys. This
    # catches truncated model output before tolerant schema defaults hide it.
    missing = [key for key in PATHOLOGY_FIELD_KEYS if key not in fields]
    if missing:
        raise LLMError("Pass B omitted canonical fields: " + ", ".join(missing))

    clean_fields: dict[str, Any] = {}
    for key in PATHOLOGY_FIELD_KEYS:
        item = fields[key]
        if not isinstance(item, dict):
            raise LLMError(f"Pass B field {key!r} must be an object.")
        value = item.get("value")
        evidence = item.get("evidence", [])
        if value is not None and not isinstance(value, (str, int, float)):
            raise LLMError(f"Pass B field {key!r} value must be text, numeric, or null.")
        if not isinstance(evidence, list):
            raise LLMError(f"Pass B field {key!r} evidence must be a list.")
        for j, ev in enumerate(evidence):
            if not isinstance(ev, dict):
                raise LLMError(f"Pass B field {key!r} evidence[{j}] must be an object.")
            # Reject timestamps rather than silently letting the model own them.
            if "start" in ev or "end" in ev:
                raise LLMError(f"Pass B field {key!r} evidence must not contain timestamps.")
            if not isinstance(ev.get("segment_id"), (str, int)):
                raise LLMError(f"Pass B field {key!r} evidence[{j}] needs segment_id.")
            if not isinstance(ev.get("quote"), str) or not ev["quote"].strip():
                raise LLMError(f"Pass B field {key!r} evidence[{j}] needs a non-empty quote.")
        clean_fields[key] = {"value": value, "evidence": evidence}

    return ColoStructExtraction(fields=clean_fields)
