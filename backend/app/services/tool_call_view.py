"""Helpers for normalizing persisted tool-call block content into a stable view."""

from __future__ import annotations

import json
from typing import Any

from app.utils.session_identity import normalize_non_empty_text

ToolCallStatus = str

_RUNNING_STATES = {"running", "pending", "in_progress", "working"}
_SUCCESS_STATES = {"success", "succeeded", "completed", "done", "ok"}
_FAILED_STATES = {"error", "failed", "failure"}
_INTERRUPTED_STATES = {"interrupted", "cancelled", "canceled", "aborted"}


def _normalize_status(
    raw_status: str | None,
    *,
    is_finished: bool,
    message_status: str | None,
) -> ToolCallStatus:
    normalized_status = normalize_non_empty_text(raw_status)
    if normalized_status:
        if normalized_status in _RUNNING_STATES:
            return "running"
        if normalized_status in _SUCCESS_STATES:
            return "success"
        if normalized_status in _FAILED_STATES:
            return "failed"
        if normalized_status in _INTERRUPTED_STATES:
            return "interrupted"

    normalized_message_status = normalize_non_empty_text(message_status)
    if normalized_message_status == "error":
        return "failed"
    if normalized_message_status == "interrupted":
        return "interrupted"
    if normalized_message_status == "streaming" or not is_finished:
        return "running"
    return "success"


def _as_json_record(raw_content: str | None) -> dict[str, Any] | None:
    if not raw_content:
        return None
    try:
        parsed = json.loads(raw_content)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def _pick_text(payload: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str):
            normalized = normalize_non_empty_text(value)
            if normalized:
                return normalized
    return None


def _pick_arguments(payload: dict[str, Any]) -> Any | None:
    for key in ("input", "arguments", "args", "parameters"):
        if key in payload:
            return payload[key]
    return None


def build_tool_call_view(
    raw_content: str | None,
    *,
    is_finished: bool,
    message_status: str | None = None,
) -> dict[str, Any] | None:
    payload = _as_json_record(raw_content)
    if payload is None:
        return None

    name = _pick_text(payload, ("tool", "tool_name", "name", "function_name"))
    call_id = _pick_text(payload, ("call_id", "callId", "id"))
    if name is None and call_id is None and not payload:
        return None

    arguments = _pick_arguments(payload)
    result = payload.get("output")
    if result is None:
        result = payload.get("result")
    error = payload.get("error")

    return {
        "name": name,
        "status": _normalize_status(
            _pick_text(payload, ("status", "state")),
            is_finished=is_finished,
            message_status=message_status,
        ),
        "callId": call_id,
        "arguments": arguments,
        "result": result,
        "error": error,
    }


__all__ = ["build_tool_call_view"]
