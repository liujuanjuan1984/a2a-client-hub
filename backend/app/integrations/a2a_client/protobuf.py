"""Helpers for normalizing A2A protobuf payloads into JSON-like structures."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.message import Message as ProtoMessage

from a2a.types import AgentCard, StreamResponse

_ROLE_MAP = {
    "ROLE_USER": "user",
    "ROLE_AGENT": "agent",
    "ROLE_UNSPECIFIED": "unspecified",
}

_TASK_STATE_MAP = {
    "TASK_STATE_UNSPECIFIED": "unspecified",
    "TASK_STATE_SUBMITTED": "submitted",
    "TASK_STATE_WORKING": "working",
    "TASK_STATE_COMPLETED": "completed",
    "TASK_STATE_FAILED": "failed",
    "TASK_STATE_CANCELED": "canceled",
    "TASK_STATE_INPUT_REQUIRED": "input_required",
    "TASK_STATE_AUTH_REQUIRED": "auth_required",
    "TASK_STATE_REJECTED": "rejected",
}

_TERMINAL_TASK_STATES = frozenset(
    {
        "completed",
        "failed",
        "canceled",
        "input_required",
        "auth_required",
        "rejected",
    }
)


def is_proto_message(value: Any) -> bool:
    """Return whether the value is a protobuf message instance."""

    return isinstance(value, ProtoMessage)


def parse_agent_card(data: Mapping[str, Any]) -> AgentCard:
    """Parse a JSON-like AgentCard payload into the protobuf message."""

    return cast(
        AgentCard,
        ParseDict(dict(data), AgentCard(), ignore_unknown_fields=True),
    )


def protobuf_to_dict(value: ProtoMessage) -> dict[str, Any]:
    """Convert a protobuf message into a snake_case JSON-like dictionary."""

    dumped = MessageToDict(
        value,
        preserving_proto_field_name=True,
        always_print_fields_with_no_presence=True,
    )
    normalized = _normalize_json_like(dumped)
    return dict(normalized) if isinstance(normalized, Mapping) else {}


def to_json_like(value: Any) -> Any:
    """Recursively convert protobuf or model objects into JSON-like values."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return _normalize_scalar(value)

    if is_proto_message(value):
        return _normalize_json_like(
            MessageToDict(
                value,
                preserving_proto_field_name=True,
                always_print_fields_with_no_presence=True,
            )
        )

    if isinstance(value, Mapping):
        return {
            str(key): to_json_like(item)
            for key, item in value.items()
            if item is not None
        }

    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return [to_json_like(item) for item in value]

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump(mode="json", by_alias=True, exclude_none=True)
        except TypeError:
            dumped = model_dump()
        return to_json_like(dumped)

    legacy_dict = getattr(value, "dict", None)
    if callable(legacy_dict):
        try:
            dumped = legacy_dict(by_alias=True, exclude_none=True)
        except TypeError:
            dumped = legacy_dict()
        return to_json_like(dumped)

    raw_dict = getattr(value, "__dict__", None)
    if isinstance(raw_dict, Mapping):
        return {
            str(key): to_json_like(item)
            for key, item in raw_dict.items()
            if item is not None and not str(key).startswith("_")
        }

    return value


def stream_response_to_payload(response: StreamResponse) -> dict[str, Any]:
    """Normalize a StreamResponse into the hub's serialized event shape."""

    if response.HasField("artifact_update"):
        payload = protobuf_to_dict(response.artifact_update)
        payload["kind"] = "artifact-update"
        return payload

    if response.HasField("status_update"):
        payload = protobuf_to_dict(response.status_update)
        payload["kind"] = "status-update"
        payload["final"] = is_terminal_task_state(
            ((payload.get("status") or {}) if isinstance(payload, Mapping) else {}).get(
                "state"
            )
        )
        return payload

    if response.HasField("message"):
        payload = protobuf_to_dict(response.message)
        payload["kind"] = "message"
        return payload

    if response.HasField("task"):
        payload = protobuf_to_dict(response.task)
        payload["kind"] = "task"
        return payload

    return protobuf_to_dict(response)


def is_terminal_task_state(value: Any) -> bool:
    """Return whether the normalized task state should end the stream."""

    return isinstance(value, str) and value in _TERMINAL_TASK_STATES


def _normalize_json_like(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return _normalize_scalar(value)

    if isinstance(value, Mapping):
        normalized = {
            str(key): _normalize_json_like(item)
            for key, item in value.items()
            if item is not None
        }
        role = normalized.get("role")
        if role is not None:
            normalized["role"] = _normalize_scalar(role)
        state = normalized.get("state")
        if state is not None:
            normalized["state"] = _normalize_scalar(state)
        return normalized

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_normalize_json_like(item) for item in value]

    return value


def _normalize_scalar(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    if value in _ROLE_MAP:
        return _ROLE_MAP[value]
    if value in _TASK_STATE_MAP:
        return _TASK_STATE_MAP[value]
    return value
