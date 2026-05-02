from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.features.invoke.interrupt_metadata import (
    normalize_elicitation_interrupt_details,
    normalize_permission_interrupt_details,
    normalize_permissions_interrupt_details,
    normalize_question_interrupt_details,
)
from app.features.invoke.payload_helpers import dict_field as _dict_field
from app.features.invoke.payload_helpers import (
    pick_first_int,
    pick_first_non_empty_str,
)
from app.features.invoke.payload_helpers import (
    pick_non_empty_str as _pick_non_empty_str,
)
from app.features.invoke.shared_metadata import (
    extract_preferred_interrupt_metadata,
    merge_shared_metadata_sections,
)
from app.features.invoke.stream_field_aliases import (
    BASE_SEQ_KEYS,
    BLOCK_ID_KEYS,
    BLOCK_TYPE_KEYS,
    EVENT_ID_KEYS,
    LANE_ID_KEYS,
    MESSAGE_ID_KEYS,
    SEQ_KEYS,
    TASK_ID_KEYS,
)
from app.features.invoke.tool_call_view import build_tool_call_view
from app.integrations.a2a_extensions.shared_contract import SHARED_STREAM_KEY
from app.integrations.a2a_runtime_status_contract import (
    is_interactive_runtime_state,
)

BLOCK_OPERATION_TYPES = frozenset({"append", "replace", "finalize"})
_STREAM_RESPONSE_FIELD_TO_KIND = (
    ("artifactUpdate", "artifact-update"),
    ("statusUpdate", "status-update"),
    ("message", "message"),
    ("task", "task"),
)


@dataclass(frozen=True)
class ResolvedStreamContentEnvelope:
    event_kind: str | None
    event_body: dict[str, Any]
    event_metadata: dict[str, Any]
    status: dict[str, Any]
    status_message: dict[str, Any]
    content_source_kind: str | None
    artifact: dict[str, Any]
    artifact_metadata: dict[str, Any]
    parts: list[Any]
    shared_stream: dict[str, Any]


def _resolve_stream_response_body(
    payload: dict[str, Any],
) -> tuple[str | None, dict[str, Any]]:
    for field_name, kind in _STREAM_RESPONSE_FIELD_TO_KIND:
        candidate = payload.get(field_name)
        if isinstance(candidate, dict):
            return kind, candidate
    return None, {}


def _event_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    _, body = _resolve_stream_response_body(payload)
    return _dict_field(body, "metadata")


def _build_synthetic_artifact_from_message(message: dict[str, Any]) -> dict[str, Any]:
    parts = message.get("parts")
    if not isinstance(parts, list):
        return {}
    synthetic_artifact: dict[str, Any] = {"parts": list(parts)}
    metadata = _dict_field(message, "metadata")
    if metadata:
        synthetic_artifact["metadata"] = dict(metadata)
    for field_name in ("messageId", "taskId", "role", "eventId", "toolCall"):
        value = message.get(field_name)
        if value is not None:
            synthetic_artifact[field_name] = value
    return synthetic_artifact


def resolve_stream_content_envelope(
    payload: dict[str, Any],
) -> ResolvedStreamContentEnvelope:
    kind, body = _resolve_stream_response_body(payload)
    event_metadata = _dict_field(body, "metadata")
    status = _dict_field(body, "status") if kind == "status-update" else {}
    status_message = _dict_field(status, "message")

    content_source_kind: str | None = None
    artifact: dict[str, Any] = {}
    if kind == "artifact-update":
        candidate = body.get("artifact")
        artifact = candidate if isinstance(candidate, dict) else {}
        if artifact:
            content_source_kind = "artifact"
    elif kind == "message":
        artifact = _build_synthetic_artifact_from_message(body)
        if artifact:
            content_source_kind = "message"
    elif kind == "status-update":
        artifact = _build_synthetic_artifact_from_message(status_message)
        if artifact:
            content_source_kind = "status_message"

    artifact_metadata = _dict_field(artifact, "metadata")
    parts = artifact.get("parts")
    shared_stream = merge_shared_metadata_sections(
        tuple(
            candidate
            for candidate in (event_metadata, artifact)
            if isinstance(candidate, dict)
        ),
        section=SHARED_STREAM_KEY,
    )
    return ResolvedStreamContentEnvelope(
        event_kind=kind,
        event_body=body,
        event_metadata=event_metadata,
        status=status,
        status_message=status_message,
        content_source_kind=content_source_kind,
        artifact=artifact,
        artifact_metadata=artifact_metadata,
        parts=list(parts) if isinstance(parts, list) else [],
        shared_stream=shared_stream,
    )


def extract_stream_text_from_parts(parts: Any) -> str:
    if not isinstance(parts, list):
        return ""
    collected: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if isinstance(text, str):
            collected.append(text)
    return "".join(collected)


def serialize_stream_data_value(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except TypeError:
        return json.dumps(repr(value), ensure_ascii=False)


def extract_stream_data_from_parts(parts: Any) -> str:
    if not isinstance(parts, list):
        return ""
    collected: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        if "data" not in part:
            continue
        serialized = serialize_stream_data_value(part.get("data"))
        if serialized:
            collected.append(serialized)
    return "\n".join(collected)


def _infer_canonical_block_type(parts: Any) -> str | None:
    if extract_stream_data_from_parts(parts):
        return "tool_call"
    if extract_stream_text_from_parts(parts):
        return "text"
    return None


def extract_stream_content_from_parts(parts: Any, *, block_type: str) -> str:
    if block_type == "tool_call":
        return extract_stream_data_from_parts(parts) or extract_stream_text_from_parts(
            parts
        )
    return extract_stream_text_from_parts(parts)


def extract_shared_stream_metadata(
    payload: dict[str, Any], artifact: dict[str, Any]
) -> dict[str, Any]:
    return merge_shared_metadata_sections(
        tuple(
            candidate
            for candidate in (_event_metadata(payload), artifact)
            if isinstance(candidate, dict)
        ),
        section=SHARED_STREAM_KEY,
    )


def extract_artifact_type(
    payload: dict[str, Any], artifact: dict[str, Any]
) -> str | None:
    kind, body = _resolve_stream_response_body(payload)
    metadata = artifact.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    event_metadata = _event_metadata(payload)
    shared_stream = extract_shared_stream_metadata(payload, artifact)

    raw = pick_first_non_empty_str(
        (shared_stream, metadata, event_metadata),
        BLOCK_TYPE_KEYS,
    )

    if raw is None:
        if kind in {"artifact-update", "message", "status-update"}:
            return _infer_canonical_block_type(artifact.get("parts"))
        return None

    normalized = raw.lower()
    if normalized in {"text", "reasoning", "tool_call"}:
        return normalized
    return None


def extract_artifact_source(
    payload: dict[str, Any], artifact: dict[str, Any]
) -> str | None:
    metadata = artifact.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    event_metadata = _event_metadata(payload)
    shared_stream = extract_shared_stream_metadata(payload, artifact)
    source = shared_stream.get("source")
    if not isinstance(source, str) or not source.strip():
        source = metadata.get("source")
    if not isinstance(source, str) or not source.strip():
        source = event_metadata.get("source")
    if isinstance(source, str) and source.strip():
        return source.strip().lower()
    return None


def extract_artifact_id(
    payload: dict[str, Any], artifact: dict[str, Any]
) -> str | None:
    artifact_metadata = _dict_field(artifact, "metadata")
    event_metadata = _event_metadata(payload)
    shared_stream = extract_shared_stream_metadata(payload, artifact)

    for candidate in (
        artifact,
        artifact_metadata,
        event_metadata,
        shared_stream,
    ):
        artifact_id = _pick_non_empty_str(candidate, ("artifactId", "artifact_id"))
        if artifact_id is not None:
            return artifact_id
    return None


def _infer_task_id_from_artifact_id(artifact_id: str | None) -> str | None:
    if not isinstance(artifact_id, str):
        return None
    normalized = artifact_id.strip()
    if not normalized:
        return None
    task_id, _, _ = normalized.partition(":")
    task_id = task_id.strip()
    return task_id or None


def extract_message_id(
    payload: dict[str, Any], artifact: dict[str, Any], *, artifact_id: str | None = None
) -> str | None:
    artifact_metadata = _dict_field(artifact, "metadata")
    event_metadata = _event_metadata(payload)
    shared_stream = extract_shared_stream_metadata(payload, artifact)
    kind, body = _resolve_stream_response_body(payload)

    message_id = pick_first_non_empty_str(
        (
            artifact,
            artifact_metadata,
            event_metadata,
            shared_stream,
            body,
        ),
        MESSAGE_ID_KEYS,
    )
    if message_id is not None:
        return message_id
    if kind != "artifact-update":
        return None

    task_id = pick_first_non_empty_str(
        (
            body,
            artifact,
            artifact_metadata,
            event_metadata,
            shared_stream,
        ),
        TASK_ID_KEYS,
    ) or _infer_task_id_from_artifact_id(
        artifact_id
        if artifact_id is not None
        else extract_artifact_id(payload, artifact)
    )
    if task_id is None:
        return None
    return f"task:{task_id}"


def _default_lane_id(block_type: str) -> str:
    return "primary_text" if block_type == "text" else block_type


def extract_block_operation(
    payload: dict[str, Any], artifact: dict[str, Any]
) -> str | None:
    kind, body = _resolve_stream_response_body(payload)
    artifact_metadata = _dict_field(artifact, "metadata")
    event_metadata = _event_metadata(payload)
    shared_stream = extract_shared_stream_metadata(payload, artifact)

    raw = pick_first_non_empty_str(
        (
            body,
            shared_stream,
            artifact_metadata,
            event_metadata,
            artifact,
        ),
        ("op",),
    )
    if raw is not None:
        normalized = raw.lower()
        if normalized in BLOCK_OPERATION_TYPES:
            return normalized
    if (
        kind in {"message", "status-update"}
        and _infer_canonical_block_type(artifact.get("parts")) is not None
    ):
        return "replace"
    if (
        kind == "artifact-update"
        and _infer_canonical_block_type(artifact.get("parts")) is not None
    ):
        return "append" if body.get("append") is True else "replace"
    return None


def extract_block_id(
    payload: dict[str, Any], artifact: dict[str, Any], *, block_type: str
) -> str:
    artifact_metadata = _dict_field(artifact, "metadata")
    event_metadata = _event_metadata(payload)
    shared_stream = extract_shared_stream_metadata(payload, artifact)
    _, body = _resolve_stream_response_body(payload)

    block_id = pick_first_non_empty_str(
        (
            shared_stream,
            artifact_metadata,
            event_metadata,
            artifact,
        ),
        BLOCK_ID_KEYS,
    )
    if block_id is not None:
        return block_id

    lane_id = extract_lane_id(payload, artifact, block_type=block_type)
    artifact_id = extract_artifact_id(payload, artifact)
    message_id = extract_message_id(payload, artifact, artifact_id=artifact_id)
    if message_id is not None:
        return f"{message_id}:{lane_id}"

    return f"{artifact_id or 'stream'}:{lane_id}"


def extract_lane_id(
    payload: dict[str, Any], artifact: dict[str, Any], *, block_type: str
) -> str:
    artifact_metadata = _dict_field(artifact, "metadata")
    event_metadata = _event_metadata(payload)
    shared_stream = extract_shared_stream_metadata(payload, artifact)

    lane_id = pick_first_non_empty_str(
        (
            shared_stream,
            artifact_metadata,
            event_metadata,
            artifact,
        ),
        LANE_ID_KEYS,
    )
    if lane_id is not None:
        return lane_id

    return _default_lane_id(block_type)


def extract_block_base_seq(
    payload: dict[str, Any], artifact: dict[str, Any]
) -> int | None:
    artifact_metadata = _dict_field(artifact, "metadata")
    event_metadata = _event_metadata(payload)
    shared_stream = extract_shared_stream_metadata(payload, artifact)

    return pick_first_int(
        (
            shared_stream,
            artifact_metadata,
            event_metadata,
            artifact,
        ),
        BASE_SEQ_KEYS,
    )


def extract_stream_chunk_from_serialized_event(
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    envelope = resolve_stream_content_envelope(payload)
    normalized_kind = envelope.event_kind
    if normalized_kind not in ("artifact-update", "message", "status-update"):
        return None

    body = envelope.event_body
    artifact = envelope.artifact
    if not artifact:
        return None
    artifact_metadata = envelope.artifact_metadata
    event_metadata = envelope.event_metadata
    shared_stream = envelope.shared_stream

    block_type = extract_artifact_type(payload, artifact)
    if block_type is None:
        return None
    operation = extract_block_operation(payload, artifact)
    if operation is None:
        return None

    event_id = pick_first_non_empty_str(
        (
            artifact,
            artifact_metadata,
            event_metadata,
            shared_stream,
            body,
        ),
        EVENT_ID_KEYS,
    )
    delta = extract_stream_content_from_parts(
        artifact.get("parts"), block_type=block_type
    )
    if not delta and operation != "finalize":
        return None

    resolved_append = operation == "append"
    resolved_is_finished = operation == "finalize" or body.get("lastChunk") is True

    seq = pick_first_int(
        (
            body,
            artifact,
            artifact_metadata,
            event_metadata,
            shared_stream,
        ),
        SEQ_KEYS,
    )
    source = extract_artifact_source(payload, artifact)
    artifact_id = extract_artifact_id(payload, artifact)
    message_id = extract_message_id(payload, artifact, artifact_id=artifact_id)
    if artifact_id is None and message_id is not None:
        artifact_id = f"{message_id}:{block_type}"
    stream_chunk: dict[str, Any] = {
        "event_id": event_id,
        "seq": seq,
        "message_id": message_id,
        "artifact_id": artifact_id,
        "block_id": extract_block_id(payload, artifact, block_type=block_type),
        "lane_id": extract_lane_id(payload, artifact, block_type=block_type),
        "block_type": block_type,
        "op": operation,
        "content": delta,
        "base_seq": extract_block_base_seq(payload, artifact),
        "append": resolved_append,
        "is_finished": resolved_is_finished,
        "source": source,
    }
    if block_type == "tool_call":
        tool_call = build_tool_call_view(
            delta,
            is_finished=resolved_is_finished,
        )
        if tool_call is not None:
            stream_chunk["tool_call"] = tool_call
    return stream_chunk


def analyze_stream_chunk_contract(
    payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    envelope = resolve_stream_content_envelope(payload)
    normalized_kind = envelope.event_kind
    if normalized_kind not in ("artifact-update", "message", "status-update"):
        return None, None
    if normalized_kind == "status-update" and envelope.content_source_kind is None:
        return None, None
    stream_block = extract_stream_chunk_from_serialized_event(payload)
    if stream_block is not None:
        return stream_block, None

    artifact = envelope.artifact
    if not artifact:
        return None, "missing_artifact"

    block_type = extract_artifact_type(payload, artifact)
    if block_type is None:
        return None, "missing_or_invalid_block_type"
    operation = extract_block_operation(payload, artifact)
    if operation is None:
        return None, "missing_or_invalid_block_operation"
    if (
        extract_stream_content_from_parts(artifact.get("parts"), block_type=block_type)
        == ""
        and operation != "finalize"
    ):
        return None, "missing_text_parts"
    return None, "invalid_artifact_update_shape"


def extract_interrupt_lifecycle_from_serialized_event(
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    normalized_kind, body = _resolve_stream_response_body(payload)
    if normalized_kind != "status-update":
        return None

    status = _dict_field(body, "status")
    raw_state = _pick_non_empty_str(status, ("state",))
    interrupt = extract_preferred_interrupt_metadata(body)
    if not interrupt:
        return None

    request_id = _pick_non_empty_str(interrupt, ("requestId",))
    interrupt_type = _pick_non_empty_str(interrupt, ("type",))
    if not request_id or interrupt_type not in {
        "permission",
        "question",
        "permissions",
        "elicitation",
    }:
        return None

    phase = _pick_non_empty_str(interrupt, ("phase",))
    if phase is None:
        phase = "asked" if is_interactive_runtime_state(raw_state) else None
    if phase not in {"asked", "resolved"}:
        return None

    payload_event: dict[str, Any] = {
        "request_id": request_id,
        "type": interrupt_type,
        "phase": phase,
    }
    if phase == "resolved":
        resolution = _pick_non_empty_str(interrupt, ("resolution",))
        if resolution not in {"replied", "rejected", "expired"}:
            return None
        payload_event["resolution"] = resolution
        return payload_event

    details = _dict_field(interrupt, "details")
    if interrupt_type == "permission":
        payload_event["details"] = normalize_permission_interrupt_details(details)
        return payload_event
    if interrupt_type == "permissions":
        payload_event["details"] = normalize_permissions_interrupt_details(details)
        return payload_event
    if interrupt_type == "elicitation":
        payload_event["details"] = normalize_elicitation_interrupt_details(details)
        return payload_event

    payload_event["details"] = normalize_question_interrupt_details(details)
    return payload_event
