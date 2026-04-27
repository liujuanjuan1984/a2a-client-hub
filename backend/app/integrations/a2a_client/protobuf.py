"""Helpers for normalizing A2A protobuf payloads into JSON-like structures."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from typing import Any, cast

from a2a.types import AgentCard, StreamResponse
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.message import Message as ProtoMessage

from app.integrations.a2a_runtime_status_contract import terminal_runtime_state_values

_TERMINAL_TASK_STATES = terminal_runtime_state_values()


def is_proto_message(value: Any) -> bool:
    """Return whether the value is a protobuf message instance."""

    return isinstance(value, ProtoMessage)


def parse_agent_card(
    data: Mapping[str, Any], *, ignore_unknown_fields: bool = True
) -> AgentCard:
    """Parse a JSON-like AgentCard payload into the protobuf message."""

    return cast(
        AgentCard,
        ParseDict(
            dict(data),
            AgentCard(),
            ignore_unknown_fields=ignore_unknown_fields,
        ),
    )


def protobuf_to_dict(value: ProtoMessage) -> dict[str, Any]:
    """Convert a protobuf message into the hub's snake_case JSON shape."""

    dumped = _message_to_dict(value, preserving_proto_field_name=True)
    normalized = _normalize_json_like(dumped)
    return dict(normalized) if isinstance(normalized, Mapping) else {}


def protobuf_to_protojson_dict(value: ProtoMessage) -> dict[str, Any]:
    """Convert a protobuf message into canonical ProtoJSON field names."""

    dumped = _message_to_dict(value, preserving_proto_field_name=False)
    return dict(dumped) if isinstance(dumped, Mapping) else {}


def to_json_like(value: Any) -> Any:
    """Recursively convert protobuf or model objects into the hub JSON shape."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if is_proto_message(value):
        return _normalize_json_like(
            _message_to_dict(value, preserving_proto_field_name=True)
        )

    if _is_dataclass_instance(value):
        return to_json_like(asdict(value))

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

    return value


def to_protojson_like(value: Any) -> Any:
    """Recursively convert protobuf or model objects into canonical ProtoJSON."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if is_proto_message(value):
        return _message_to_dict(value, preserving_proto_field_name=False)

    if _is_dataclass_instance(value):
        return to_protojson_like(asdict(value))

    if isinstance(value, Mapping):
        return {
            str(key): to_protojson_like(item)
            for key, item in value.items()
            if item is not None
        }

    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return [to_protojson_like(item) for item in value]

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump(mode="json", by_alias=True, exclude_none=True)
        except TypeError:
            dumped = model_dump()
        return to_protojson_like(dumped)

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
        return value

    if isinstance(value, Mapping):
        return {
            str(key): _normalize_json_like(item)
            for key, item in value.items()
            if item is not None
        }

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_normalize_json_like(item) for item in value]

    return value


def _is_dataclass_instance(value: Any) -> bool:
    return is_dataclass(value) and not isinstance(value, type)


def _message_to_dict(
    value: ProtoMessage, *, preserving_proto_field_name: bool
) -> dict[str, Any]:
    dumped = MessageToDict(
        value,
        preserving_proto_field_name=preserving_proto_field_name,
        always_print_fields_with_no_presence=True,
    )
    return dict(dumped) if isinstance(dumped, Mapping) else {}
