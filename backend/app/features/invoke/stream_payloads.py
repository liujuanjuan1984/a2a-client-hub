from __future__ import annotations

import json
from typing import Any

from app.features.invoke.interrupt_metadata import (
    normalize_elicitation_interrupt_details,
    normalize_permission_interrupt_details,
    normalize_permissions_interrupt_details,
    normalize_question_interrupt_details,
)
from app.features.invoke.shared_metadata import (
    extract_preferred_interrupt_metadata,
    merge_shared_metadata_sections,
)
from app.features.invoke.tool_call_view import build_tool_call_view
from app.integrations.a2a_extensions.shared_contract import SHARED_STREAM_KEY
from app.integrations.a2a_runtime_status_contract import (
    is_interactive_runtime_state,
)
from app.utils.payload_extract import as_dict

PRIMARY_TEXT_SNAPSHOT_SOURCES = frozenset({"final_snapshot", "finalize_snapshot"})
BLOCK_OPERATION_TYPES = frozenset({"append", "replace", "finalize"})


def _normalized_stream_event_kind(payload: dict[str, Any]) -> str | None:
    raw_kind = payload.get("kind")
    if not isinstance(raw_kind, str) or not raw_kind.strip():
        return None
    return raw_kind.strip().lower()


def _pick_non_empty_str(
    payload: dict[str, Any],
    keys: tuple[str, ...],
) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _pick_int(payload: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str) and value.strip().lstrip("-").isdigit():
            return int(value.strip())
    return None


def extract_stream_text_from_parts(parts: Any) -> str:
    if not isinstance(parts, list):
        return ""
    collected: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        raw_kind = part.get("kind") or part.get("type")
        normalized_kind = (
            raw_kind.strip().lower() if isinstance(raw_kind, str) else None
        )
        if normalized_kind not in {None, "", "text"}:
            continue
        text = part.get("text")
        if isinstance(text, str):
            collected.append(text)
            continue
        content = part.get("content")
        if isinstance(content, str):
            collected.append(content)
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
        raw_kind = part.get("kind") or part.get("type")
        normalized_kind = (
            raw_kind.strip().lower() if isinstance(raw_kind, str) else None
        )
        if normalized_kind != "data" and "data" not in part:
            continue
        serialized = serialize_stream_data_value(part.get("data"))
        if serialized:
            collected.append(serialized)
    return "\n".join(collected)


def _resolve_stream_artifact(payload: dict[str, Any]) -> dict[str, Any]:
    artifact = as_dict(payload.get("artifact"))
    if artifact:
        return artifact
    if _normalized_stream_event_kind(payload) != "message":
        return {}
    parts = payload.get("parts")
    if not isinstance(parts, list):
        return {}
    synthetic_artifact: dict[str, Any] = {"parts": list(parts)}
    metadata = as_dict(payload.get("metadata"))
    if metadata:
        synthetic_artifact["metadata"] = dict(metadata)
    return synthetic_artifact


def coerce_message_event_to_artifact_update(payload: dict[str, Any]) -> None:
    if _normalized_stream_event_kind(payload) != "message":
        return
    artifact = as_dict(payload.get("artifact"))
    if not artifact:
        parts = payload.get("parts")
        if not isinstance(parts, list) or not parts:
            return
        artifact = {"parts": list(parts)}
        metadata = as_dict(payload.get("metadata"))
        if metadata:
            artifact["metadata"] = dict(metadata)
        payload["artifact"] = artifact
    if "append" not in payload:
        payload["append"] = False
    payload["kind"] = "artifact-update"


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
        (payload, artifact),
        section=SHARED_STREAM_KEY,
    )


def extract_artifact_type(
    payload: dict[str, Any], artifact: dict[str, Any]
) -> str | None:
    metadata = artifact.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    root_metadata = payload.get("metadata")
    if not isinstance(root_metadata, dict):
        root_metadata = {}
    shared_stream = extract_shared_stream_metadata(payload, artifact)

    raw = shared_stream.get("block_type")
    if not isinstance(raw, str) or not raw.strip():
        raw = metadata.get("block_type")
    if not isinstance(raw, str) or not raw.strip():
        raw = root_metadata.get("block_type")

    if not isinstance(raw, str) or not raw.strip():
        if extract_stream_text_from_parts(artifact.get("parts")):
            return "text"
        return None

    normalized = raw.strip().lower()
    if normalized in {"text", "reasoning", "tool_call"}:
        return normalized
    return None


def extract_artifact_source(
    payload: dict[str, Any], artifact: dict[str, Any]
) -> str | None:
    metadata = artifact.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    root_metadata = payload.get("metadata")
    if not isinstance(root_metadata, dict):
        root_metadata = {}
    shared_stream = extract_shared_stream_metadata(payload, artifact)
    source = shared_stream.get("source")
    if not isinstance(source, str) or not source.strip():
        source = metadata.get("source")
    if not isinstance(source, str) or not source.strip():
        source = root_metadata.get("source")
    if isinstance(source, str) and source.strip():
        return source.strip().lower()
    return None


def extract_artifact_id(
    payload: dict[str, Any], artifact: dict[str, Any]
) -> str | None:
    artifact_metadata = as_dict(artifact.get("metadata"))
    root_metadata = as_dict(payload.get("metadata"))
    shared_stream = extract_shared_stream_metadata(payload, artifact)

    for candidate in (
        payload,
        artifact,
        artifact_metadata,
        root_metadata,
        shared_stream,
    ):
        artifact_id = _pick_non_empty_str(
            candidate, ("artifact_id", "artifactId", "id")
        )
        if artifact_id is not None:
            return artifact_id
    return None


def _default_lane_id(block_type: str) -> str:
    return "primary_text" if block_type == "text" else block_type


def extract_block_operation(
    payload: dict[str, Any], artifact: dict[str, Any]
) -> str | None:
    artifact_metadata = as_dict(artifact.get("metadata"))
    root_metadata = as_dict(payload.get("metadata"))
    shared_stream = extract_shared_stream_metadata(payload, artifact)

    for candidate in (
        shared_stream,
        artifact_metadata,
        root_metadata,
        artifact,
        payload,
    ):
        raw = _pick_non_empty_str(candidate, ("op", "operation"))
        if raw is None:
            continue
        normalized = raw.lower()
        if normalized in BLOCK_OPERATION_TYPES:
            return normalized

    source = extract_artifact_source(payload, artifact)
    append = payload.get("append")
    if source in PRIMARY_TEXT_SNAPSHOT_SOURCES:
        return "replace"
    if isinstance(append, bool):
        return "append" if append else "replace"
    if _normalized_stream_event_kind(payload) == "message":
        return "replace"
    return "append"


def extract_block_id(
    payload: dict[str, Any], artifact: dict[str, Any], *, block_type: str
) -> str:
    artifact_metadata = as_dict(artifact.get("metadata"))
    root_metadata = as_dict(payload.get("metadata"))
    shared_stream = extract_shared_stream_metadata(payload, artifact)

    for candidate in (
        shared_stream,
        artifact_metadata,
        root_metadata,
        artifact,
        payload,
    ):
        block_id = _pick_non_empty_str(candidate, ("block_id", "blockId"))
        if block_id is not None:
            return block_id

    lane_id = extract_lane_id(payload, artifact, block_type=block_type)
    message_id = None
    for candidate in (
        payload,
        artifact,
        artifact_metadata,
        root_metadata,
        shared_stream,
    ):
        if message_id is None:
            message_id = _pick_non_empty_str(candidate, ("message_id", "messageId"))
    if message_id is not None:
        return f"{message_id}:{lane_id}"

    artifact_id = extract_artifact_id(payload, artifact) or "stream"
    return f"{artifact_id}:{lane_id}"


def extract_lane_id(
    payload: dict[str, Any], artifact: dict[str, Any], *, block_type: str
) -> str:
    artifact_metadata = as_dict(artifact.get("metadata"))
    root_metadata = as_dict(payload.get("metadata"))
    shared_stream = extract_shared_stream_metadata(payload, artifact)

    for candidate in (
        shared_stream,
        artifact_metadata,
        root_metadata,
        artifact,
        payload,
    ):
        lane_id = _pick_non_empty_str(candidate, ("lane_id", "laneId"))
        if lane_id is not None:
            return lane_id

    return _default_lane_id(block_type)


def extract_block_base_seq(
    payload: dict[str, Any], artifact: dict[str, Any]
) -> int | None:
    artifact_metadata = as_dict(artifact.get("metadata"))
    root_metadata = as_dict(payload.get("metadata"))
    shared_stream = extract_shared_stream_metadata(payload, artifact)

    for candidate in (
        shared_stream,
        artifact_metadata,
        root_metadata,
        artifact,
        payload,
    ):
        base_seq = _pick_int(candidate, ("base_seq", "baseSeq"))
        if base_seq is not None:
            return base_seq
    return None


def extract_stream_sequence_from_serialized_event(
    payload: dict[str, Any],
) -> int | None:
    root = as_dict(payload)
    sequence = _pick_int(root, ("seq",))
    if sequence is not None:
        return sequence
    artifact = as_dict(root.get("artifact"))
    shared_stream = extract_shared_stream_metadata(root, artifact)
    return _pick_int(shared_stream, ("sequence", "seq"))


def extract_stream_chunk_from_serialized_event(
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    normalized_kind = _normalized_stream_event_kind(payload)
    if normalized_kind not in (None, "artifact-update", "message"):
        return None

    artifact = _resolve_stream_artifact(payload)
    if not artifact:
        return None
    artifact_metadata = as_dict(artifact.get("metadata"))
    root_metadata = as_dict(payload.get("metadata"))
    shared_stream = extract_shared_stream_metadata(payload, artifact)

    block_type = extract_artifact_type(payload, artifact)
    if block_type is None:
        return None
    operation = extract_block_operation(payload, artifact)
    if operation is None:
        return None

    event_id = None
    message_id = None
    for candidate in (
        payload,
        artifact,
        artifact_metadata,
        root_metadata,
        shared_stream,
    ):
        if event_id is None:
            event_id = _pick_non_empty_str(candidate, ("event_id", "eventId"))
        if message_id is None:
            message_id = _pick_non_empty_str(candidate, ("message_id", "messageId"))

    delta = extract_stream_content_from_parts(
        artifact.get("parts"), block_type=block_type
    )
    if not delta and operation != "finalize":
        return None

    append = payload.get("append")
    resolved_append = (
        append
        if isinstance(append, bool)
        else False if normalized_kind == "message" else True
    )
    resolved_is_finished = (
        payload.get("lastChunk") is True
        or payload.get("last_chunk") is True
        or artifact.get("lastChunk") is True
        or artifact.get("last_chunk") is True
    )
    if operation == "finalize":
        resolved_is_finished = True

    seq = (
        _pick_int(payload, ("seq",))
        or _pick_int(artifact, ("seq",))
        or _pick_int(artifact_metadata, ("seq",))
        or _pick_int(root_metadata, ("seq",))
        or _pick_int(shared_stream, ("sequence", "seq"))
    )
    source = extract_artifact_source(payload, artifact)
    artifact_id = extract_artifact_id(payload, artifact)
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
    normalized_kind = _normalized_stream_event_kind(payload)
    if normalized_kind not in (None, "artifact-update", "message"):
        return None, None
    stream_block = extract_stream_chunk_from_serialized_event(payload)
    if stream_block is not None:
        return stream_block, None

    artifact = _resolve_stream_artifact(payload)
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
    if not isinstance(payload, dict) or payload.get("kind") != "status-update":
        return None

    status = as_dict(payload.get("status"))
    raw_state = _pick_non_empty_str(status, ("state",))
    interrupt = extract_preferred_interrupt_metadata(payload)
    if not interrupt:
        return None

    request_id = _pick_non_empty_str(interrupt, ("request_id", "requestId"))
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
        if resolution not in {"replied", "rejected"}:
            return None
        payload_event["resolution"] = resolution
        return payload_event

    details = as_dict(interrupt.get("details")) or {}
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
