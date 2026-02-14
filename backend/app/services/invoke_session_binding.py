"""Shared invoke session binding helpers for API routers."""

from __future__ import annotations

from typing import Any


def status_code_for_invoke_session_error(detail: str) -> int:
    if detail == "session_not_found":
        return 404
    return 400


def ws_error_code_for_invoke_session_error(detail: str) -> str:
    if detail == "session_not_found":
        return "session_not_found"
    return "invalid_session_id"


def normalize_invoke_binding_state(
    *,
    context_id: str | None,
    metadata: dict[str, Any] | None,
) -> tuple[str | None, dict[str, Any]]:
    resolved_context_id = context_id.strip() if isinstance(context_id, str) else None
    if not resolved_context_id:
        resolved_context_id = None
    resolved_metadata = dict(metadata) if isinstance(metadata, dict) else {}
    return resolved_context_id, resolved_metadata


def merge_invoke_binding_state(
    *,
    current_context_id: str | None,
    current_metadata: dict[str, Any],
    next_context_id: str | None,
    next_metadata: dict[str, Any],
) -> tuple[str | None, dict[str, Any]]:
    merged_context_id = current_context_id
    if isinstance(next_context_id, str):
        trimmed_context = next_context_id.strip()
        if trimmed_context:
            merged_context_id = trimmed_context
    merged_metadata = dict(current_metadata)
    if isinstance(next_metadata, dict) and next_metadata:
        merged_metadata.update(next_metadata)
    return merged_context_id, merged_metadata


__all__ = [
    "merge_invoke_binding_state",
    "normalize_invoke_binding_state",
    "status_code_for_invoke_session_error",
    "ws_error_code_for_invoke_session_error",
]
