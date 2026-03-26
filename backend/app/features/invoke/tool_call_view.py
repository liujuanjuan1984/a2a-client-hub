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


def _iter_json_values(raw_content: str | None) -> list[Any]:
    if not raw_content:
        return []
    decoder = json.JSONDecoder()
    values: list[Any] = []
    index = 0
    length = len(raw_content)
    while index < length:
        while index < length and raw_content[index].isspace():
            index += 1
        if index >= length:
            break
        try:
            value, next_index = decoder.raw_decode(raw_content, index)
        except json.JSONDecodeError:
            return []
        values.append(value)
        index = next_index
    return values


def _as_json_records(raw_content: str | None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for value in _iter_json_values(raw_content):
        if isinstance(value, dict):
            records.append(value)
            continue
        if isinstance(value, list):
            records.extend(item for item in value if isinstance(item, dict))
    return records


def _normalize_status(
    raw_status: str | None,
    *,
    is_finished: bool,
    message_status: str | None,
) -> ToolCallStatus:
    normalized_status = normalize_non_empty_text(raw_status)
    if normalized_status:
        if normalized_status in _RUNNING_STATES:
            if not is_finished:
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


def _pick_result(payload: dict[str, Any]) -> Any | None:
    if payload.get("output") is not None:
        return payload.get("output")
    return payload.get("result")


def _pick_title(payload: dict[str, Any]) -> str | None:
    title = _pick_text(payload, ("title", "description", "summary"))
    if title is not None:
        return title
    arguments = _pick_arguments(payload)
    if isinstance(arguments, dict):
        return _pick_text(arguments, ("title", "description", "summary"))
    return None


def _build_timeline_entry(payload: dict[str, Any]) -> dict[str, Any] | None:
    status = _pick_text(payload, ("status", "state"))
    title = _pick_title(payload)
    arguments = _pick_arguments(payload)
    output = _pick_result(payload)
    error = payload.get("error")
    if (
        status is None
        and title is None
        and arguments is None
        and output is None
        and error is None
    ):
        return None
    entry: dict[str, Any] = {
        "status": status or "unknown",
    }
    if title is not None:
        entry["title"] = title
    if arguments is not None:
        entry["input"] = arguments
    if output is not None:
        entry["output"] = output
    if error is not None:
        entry["error"] = error
    return entry


def build_tool_call_view(
    raw_content: str | None,
    *,
    is_finished: bool,
    message_status: str | None = None,
) -> dict[str, Any] | None:
    payloads = _as_json_records(raw_content)
    if not payloads:
        return None
    payload = payloads[-1]
    name = None
    call_id = None
    arguments = None
    result = None
    error = None
    raw_status = None
    for item in payloads:
        candidate_name = _pick_text(
            item,
            ("tool", "tool_name", "name", "function_name"),
        )
        if candidate_name is not None:
            name = candidate_name
        candidate_call_id = _pick_text(item, ("call_id", "callId", "id"))
        if candidate_call_id is not None:
            call_id = candidate_call_id
        candidate_arguments = _pick_arguments(item)
        if candidate_arguments is not None:
            arguments = candidate_arguments
        candidate_result = _pick_result(item)
        if candidate_result is not None:
            result = candidate_result
        candidate_error = item.get("error")
        if candidate_error is not None:
            error = candidate_error
        candidate_status = _pick_text(item, ("status", "state"))
        if candidate_status is not None:
            raw_status = candidate_status
    if name is None and call_id is None and not payload:
        return None

    return {
        "name": name,
        "status": _normalize_status(
            raw_status,
            is_finished=is_finished,
            message_status=message_status,
        ),
        "callId": call_id,
        "arguments": arguments,
        "result": result,
        "error": error,
    }


def build_tool_call_detail(
    raw_content: str | None,
    *,
    is_finished: bool,
    message_status: str | None = None,
) -> dict[str, Any] | None:
    payloads = _as_json_records(raw_content)
    if not payloads:
        return None
    summary = build_tool_call_view(
        raw_content,
        is_finished=is_finished,
        message_status=message_status,
    )
    if summary is None:
        return None
    timeline = [
        entry
        for entry in (_build_timeline_entry(payload) for payload in payloads)
        if entry is not None
    ]
    detail = {
        **summary,
        "title": None,
        "timeline": timeline,
        "raw": raw_content or None,
    }
    for payload in payloads:
        candidate_title = _pick_title(payload)
        if candidate_title is not None:
            detail["title"] = candidate_title
    return detail


__all__ = ["build_tool_call_detail", "build_tool_call_view"]
