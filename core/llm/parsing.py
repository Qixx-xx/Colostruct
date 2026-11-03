"""Strict helpers for validating model-produced intermediate JSON."""
from __future__ import annotations

from typing import Any
from .client import LLMError


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LLMError(f"{label} must be a JSON object.")
    return value


def validate_segment_list(value: Any, known_ids: set[str], label: str) -> list[dict]:
    if not isinstance(value, list):
        raise LLMError(f"{label} must be a list.")
    output = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise LLMError(f"{label}[{index}] must be an object.")
        segment_id = str(item.get("segment_id", "")).strip()
        if segment_id not in known_ids:
            raise LLMError(f"{label}[{index}] references unknown segment_id {segment_id!r}.")
        corrected = item.get("corrected_text")
        if not isinstance(corrected, str):
            raise LLMError(f"{label}[{index}].corrected_text must be a string.")
        output.append({"segment_id": segment_id, "corrected_text": corrected})
    return output
