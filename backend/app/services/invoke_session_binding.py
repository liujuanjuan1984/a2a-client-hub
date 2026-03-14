"""Shared invoke session binding helpers for API routers."""

from __future__ import annotations

from typing import Any

from app.schemas.a2a_invoke import A2AAgentInvokeSessionBinding
from app.utils.payload_extract import extract_provider_and_external_session_id
from app.utils.session_identity import normalize_non_empty_text, normalize_provider


def status_code_for_invoke_session_error(detail: str) -> int:
    normalized = normalize_error_code(detail)
    if normalized == "session_not_found":
        return 404
    if normalized in {
        "invoke_inflight",
        "invoke_interrupt_failed",
        "idempotency_conflict",
        "message_id_conflict",
    }:
        return 409
    return 400


def is_recoverable_invoke_session_error(detail: str | None) -> bool:
    return normalize_error_code(detail) == "session_not_found"


def ws_error_code_for_recovery_failed(detail: str) -> str:
    normalized = normalize_error_code(detail)
    if normalized == "session_not_found":
        return "session_not_found_recovery_exhausted"
    return normalized


def ws_error_code_for_invoke_session_error(detail: str) -> str:
    normalized = normalize_error_code(detail)
    if normalized == "session_not_found":
        return "session_not_found"
    if normalized == "invoke_inflight":
        return "invoke_inflight"
    if normalized == "invoke_interrupt_failed":
        return "invoke_interrupt_failed"
    if normalized == "idempotency_conflict":
        return "idempotency_conflict"
    if normalized == "message_id_conflict":
        return "message_id_conflict"
    if normalized == "invalid_message_id":
        return "invalid_message_id"
    return "invalid_conversation_id"


def normalize_error_code(detail: str | None) -> str:
    if not isinstance(detail, str):
        return ""
    return detail.strip().lower().replace("-", "_")


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


def resolve_invoke_session_binding_hint(
    *,
    session_binding: A2AAgentInvokeSessionBinding | None,
    metadata: dict[str, Any] | None,
) -> tuple[str | None, str | None]:
    legacy_provider, legacy_external_session_id = (
        extract_provider_and_external_session_id({"metadata": metadata or {}})
    )
    if session_binding is None:
        return legacy_provider, legacy_external_session_id

    provider = normalize_provider(session_binding.provider) or legacy_provider
    external_session_id = (
        normalize_non_empty_text(session_binding.external_session_id)
        or legacy_external_session_id
    )
    return provider, external_session_id


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
    "is_recoverable_invoke_session_error",
    "ws_error_code_for_recovery_failed",
    "ws_error_code_for_invoke_session_error",
    "resolve_invoke_session_binding_hint",
]
