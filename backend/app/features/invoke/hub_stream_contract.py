"""Stable backend-to-frontend stream contract for Hub clients."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.features.invoke.payload_analysis import analyze_payload
from app.features.invoke.payload_helpers import dict_field as _dict_field
from app.features.invoke.payload_helpers import (
    pick_first_int,
    pick_first_non_empty_str,
)
from app.features.invoke.stream_field_aliases import (
    EVENT_ID_KEYS,
    MESSAGE_ID_KEYS,
    SEQ_KEYS,
    TASK_ID_KEYS,
)
from app.features.invoke.stream_payloads import (
    extract_interrupt_lifecycle_from_serialized_event,
    extract_raw_stream_chunk_from_serialized_event,
    resolve_stream_content_envelope,
)
from app.integrations.a2a_runtime_status_contract import (
    TERMINAL_STREAM_RUNTIME_STATES,
    normalize_runtime_state,
)
from app.utils.payload_extract import extract_provider_and_external_session_id

_HUB_STREAM_VERSION = "v1"
_VALID_EVENT_KINDS = frozenset({"artifact-update", "message", "status-update", "task"})


def _coerce_string_list(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    normalized = [
        item.strip() for item in value if isinstance(item, str) and item.strip()
    ]
    return normalized or None


def _infer_task_id_from_artifact_id(artifact_id: str | None) -> str | None:
    if not isinstance(artifact_id, str):
        return None
    normalized = artifact_id.strip()
    if not normalized:
        return None
    task_id, _, _ = normalized.partition(":")
    task_id = task_id.strip()
    return task_id or None


def _infer_task_id_from_message_id(message_id: str | None) -> str | None:
    if not isinstance(message_id, str):
        return None
    normalized = message_id.strip()
    if not normalized.startswith("task:"):
        return None
    task_id = normalized[len("task:") :].strip()
    return task_id or None


def _build_fallback_event_id(
    *,
    message_id: str,
    artifact_id: str,
    seq: int | None,
) -> str:
    if seq is not None:
        return f"seq:{message_id}:{seq}"
    return f"chunk:{message_id}:{artifact_id}"


def _build_interrupt_details(
    interrupt_type: str,
    details: Mapping[str, Any] | None,
) -> dict[str, Any]:
    resolved = dict(details or {})
    display_message = resolved.get("display_message")
    if interrupt_type == "permission":
        return {
            "permission": resolved.get("permission"),
            "patterns": (
                resolved.get("patterns")
                if isinstance(resolved.get("patterns"), list)
                else []
            ),
            "displayMessage": display_message,
        }
    if interrupt_type == "permissions":
        permissions = resolved.get("permissions")
        return {
            "permissions": (
                dict(permissions) if isinstance(permissions, Mapping) else None
            ),
            "displayMessage": display_message,
        }
    if interrupt_type == "elicitation":
        meta = resolved.get("meta")
        return {
            "displayMessage": display_message,
            "serverName": resolved.get("server_name"),
            "mode": resolved.get("mode"),
            "requestedSchema": resolved.get("requested_schema"),
            "url": resolved.get("url"),
            "elicitationId": resolved.get("elicitation_id"),
            "meta": dict(meta) if isinstance(meta, Mapping) else None,
        }
    return {
        "displayMessage": display_message,
        "questions": (
            resolved.get("questions")
            if isinstance(resolved.get("questions"), list)
            else []
        ),
    }


def _build_runtime_interrupt(payload: dict[str, Any]) -> dict[str, Any] | None:
    raw_interrupt = extract_interrupt_lifecycle_from_serialized_event(payload)
    if not raw_interrupt:
        return None

    request_id = raw_interrupt.get("request_id")
    interrupt_type = raw_interrupt.get("type")
    phase = raw_interrupt.get("phase")
    if not isinstance(request_id, str) or not isinstance(interrupt_type, str):
        return None
    if phase == "resolved":
        resolution = raw_interrupt.get("resolution")
        if not isinstance(resolution, str):
            return None
        return {
            "requestId": request_id,
            "type": interrupt_type,
            "phase": "resolved",
            "resolution": resolution,
            "source": "stream",
        }
    if phase != "asked":
        return None
    details = raw_interrupt.get("details")
    return {
        "requestId": request_id,
        "type": interrupt_type,
        "phase": "asked",
        "source": "stream",
        "details": _build_interrupt_details(
            interrupt_type,
            details if isinstance(details, Mapping) else None,
        ),
    }


def _build_runtime_status(
    payload: dict[str, Any],
    *,
    local_event_sequence: int,
) -> dict[str, Any] | None:
    envelope = resolve_stream_content_envelope(payload)
    if envelope.event_kind != "status-update" or not envelope.status:
        return None

    raw_state = envelope.status.get("state")
    if not isinstance(raw_state, str) or not raw_state.strip():
        return None

    state = normalize_runtime_state(raw_state)
    if state is None:
        return None

    message_id = pick_first_non_empty_str(
        (
            envelope.shared_stream,
            envelope.event_metadata,
            envelope.status_message,
            envelope.status,
            envelope.event_body,
        ),
        MESSAGE_ID_KEYS,
    )
    seq = pick_first_int(
        (
            envelope.shared_stream,
            envelope.event_metadata,
            envelope.status_message,
            envelope.status,
            envelope.event_body,
        ),
        SEQ_KEYS,
    )
    resolved_seq = seq if isinstance(seq, int) else local_event_sequence
    raw_completion_phase = envelope.shared_stream.get("completionPhase")
    completion_phase = (
        "persisted"
        if isinstance(raw_completion_phase, str)
        and raw_completion_phase.strip().lower() == "persisted"
        else None
    )
    result = {
        "state": state,
        "isFinal": state in TERMINAL_STREAM_RUNTIME_STATES,
        "interrupt": _build_runtime_interrupt(payload),
        "seq": resolved_seq,
        "completionPhase": completion_phase,
        "messageId": message_id,
    }
    return result


def _normalize_role(value: Any) -> str:
    if not isinstance(value, str):
        return "agent"
    normalized = value.strip().lower()
    if normalized.startswith("role_"):
        normalized = normalized[len("role_") :]
    if normalized in {"user", "agent", "system"}:
        return normalized
    return "agent"


def _build_stream_block(
    payload: dict[str, Any],
    *,
    upstream_shared_stream: Mapping[str, Any] | None = None,
    local_stream_context: Mapping[str, Any] | None = None,
    local_event_sequence: int,
) -> dict[str, Any] | None:
    stream_chunk = extract_raw_stream_chunk_from_serialized_event(payload)
    if not stream_chunk:
        return None

    envelope = resolve_stream_content_envelope(payload)
    body = envelope.event_body
    artifact = envelope.artifact
    artifact_metadata = envelope.artifact_metadata
    event_metadata = envelope.event_metadata
    shared_stream = envelope.shared_stream
    local_context_candidates = (
        (local_stream_context,) if isinstance(local_stream_context, Mapping) else ()
    )
    source_shared_stream = (
        dict(upstream_shared_stream)
        if isinstance(upstream_shared_stream, Mapping)
        else shared_stream
    )

    block_type = stream_chunk.get("block_type")
    content = stream_chunk.get("content")
    operation = stream_chunk.get("op")
    if (
        not isinstance(block_type, str)
        or not isinstance(content, str)
        or not isinstance(operation, str)
    ):
        return None

    seq = stream_chunk.get("seq")
    resolved_seq = seq if isinstance(seq, int) else local_event_sequence
    local_seq = pick_first_int(local_context_candidates, ("seq",))
    if isinstance(local_seq, int):
        resolved_seq = local_seq

    artifact_id = stream_chunk.get("artifact_id")
    resolved_artifact_id = artifact_id if isinstance(artifact_id, str) else None
    task_id_hint = pick_first_non_empty_str(
        (body, artifact, event_metadata, source_shared_stream),
        TASK_ID_KEYS,
    ) or _infer_task_id_from_artifact_id(resolved_artifact_id)

    local_message_id = pick_first_non_empty_str(
        local_context_candidates, ("message_id",)
    )
    upstream_message_id = pick_first_non_empty_str(
        (
            source_shared_stream,
            body,
            artifact,
            artifact_metadata,
            event_metadata,
        ),
        MESSAGE_ID_KEYS,
    )
    message_id_source = (
        "local_persistence"
        if local_message_id is not None
        else (
            "upstream"
            if upstream_message_id is not None
            else "task_fallback" if task_id_hint else "artifact_fallback"
        )
    )
    resolved_message_id = (
        local_message_id
        or upstream_message_id
        or (f"task:{task_id_hint}" if task_id_hint else None)
    )
    if resolved_artifact_id is None:
        resolved_artifact_id = f"{resolved_message_id or 'stream'}:{block_type}"
    task_id = (
        task_id_hint
        or _infer_task_id_from_artifact_id(resolved_artifact_id)
        or _infer_task_id_from_message_id(resolved_message_id)
        or resolved_message_id
        or resolved_artifact_id
    )
    message_id = resolved_message_id or f"artifact:{resolved_artifact_id}"

    local_event_id = pick_first_non_empty_str(local_context_candidates, ("event_id",))
    upstream_event_id = pick_first_non_empty_str(
        (
            source_shared_stream,
            body,
            artifact,
            artifact_metadata,
            event_metadata,
        ),
        EVENT_ID_KEYS,
    )
    event_id = (
        local_event_id
        or upstream_event_id
        or _build_fallback_event_id(
            message_id=message_id,
            artifact_id=resolved_artifact_id,
            seq=resolved_seq,
        )
    )
    event_id_source = (
        "local_persistence"
        if local_event_id
        else (
            "upstream"
            if upstream_event_id
            else "fallback_seq" if resolved_seq is not None else "fallback_chunk"
        )
    )

    lane_id = stream_chunk.get("lane_id")
    block_id = stream_chunk.get("block_id")
    source = stream_chunk.get("source")
    base_seq = stream_chunk.get("base_seq")
    local_block_id = pick_first_non_empty_str(local_context_candidates, ("block_id",))
    local_lane_id = pick_first_non_empty_str(local_context_candidates, ("lane_id",))
    local_operation = pick_first_non_empty_str(local_context_candidates, ("op",))
    local_base_seq = pick_first_int(local_context_candidates, ("base_seq",))
    if local_block_id is not None:
        block_id = local_block_id
    if local_lane_id is not None:
        lane_id = local_lane_id
    if local_operation is not None:
        operation = local_operation
    if isinstance(local_base_seq, int):
        base_seq = local_base_seq

    payload_result: dict[str, Any] = {
        "eventId": event_id,
        "eventIdSource": event_id_source,
        "messageIdSource": message_id_source,
        "seq": resolved_seq,
        "taskId": task_id,
        "artifactId": resolved_artifact_id,
        "blockId": (
            block_id if isinstance(block_id, str) else f"{message_id}:{block_type}"
        ),
        "laneId": lane_id if isinstance(lane_id, str) else block_type,
        "blockType": block_type,
        "op": operation,
        "baseSeq": base_seq if isinstance(base_seq, int) else None,
        "source": source if isinstance(source, str) else None,
        "messageId": message_id,
        "role": _normalize_role(
            pick_first_non_empty_str(
                (
                    body,
                    artifact,
                    source_shared_stream,
                    artifact_metadata,
                    event_metadata,
                ),
                ("role",),
            )
        ),
        "delta": content,
        "append": bool(stream_chunk.get("append")),
        "done": bool(stream_chunk.get("is_finished")),
    }
    tool_call = stream_chunk.get("tool_call")
    if isinstance(tool_call, Mapping):
        payload_result["toolCall"] = dict(tool_call)
    return payload_result


def _build_session_meta(payload: dict[str, Any]) -> dict[str, Any] | None:
    envelope = resolve_stream_content_envelope(payload)
    body = envelope.event_body
    if not body:
        return None

    properties = _dict_field(body, "properties")
    analysis = analyze_payload(payload)
    provider, external_session_id = extract_provider_and_external_session_id(
        {"metadata": analysis.binding_metadata or {}}
    )

    stream_thread_id = pick_first_non_empty_str(
        (properties, envelope.shared_stream, body),
        ("threadId",),
    )
    stream_turn_id = pick_first_non_empty_str(
        (properties, envelope.shared_stream, body),
        ("turnId",),
    )

    transport = body.get("transport")
    input_modes = _coerce_string_list(body.get("inputModes")) or _coerce_string_list(
        payload.get("inputModes")
    )
    output_modes = _coerce_string_list(body.get("outputModes")) or _coerce_string_list(
        payload.get("outputModes")
    )

    session_meta = {
        "provider": provider,
        "externalSessionId": external_session_id,
        "streamThreadId": stream_thread_id,
        "streamTurnId": stream_turn_id,
        "transport": transport if isinstance(transport, str) else None,
        "inputModes": input_modes,
        "outputModes": output_modes,
    }
    if any(value is not None for value in session_meta.values()):
        return session_meta
    return None


def attach_hub_stream_contract(
    payload: dict[str, Any],
    *,
    upstream_shared_stream: Mapping[str, Any] | None = None,
    local_stream_context: Mapping[str, Any] | None = None,
    local_event_sequence: int,
) -> None:
    envelope = resolve_stream_content_envelope(payload)
    kind = envelope.event_kind
    if kind not in _VALID_EVENT_KINDS:
        return

    hub_payload: dict[str, Any] = {
        "version": _HUB_STREAM_VERSION,
        "eventKind": kind,
    }
    stream_block = _build_stream_block(
        payload,
        upstream_shared_stream=upstream_shared_stream,
        local_stream_context=local_stream_context,
        local_event_sequence=local_event_sequence,
    )
    if stream_block is not None:
        hub_payload["streamBlock"] = stream_block
    runtime_status = _build_runtime_status(
        payload,
        local_event_sequence=local_event_sequence,
    )
    if runtime_status is not None:
        hub_payload["runtimeStatus"] = runtime_status
    session_meta = _build_session_meta(payload)
    if session_meta is not None:
        hub_payload["sessionMeta"] = session_meta
    payload["hub"] = hub_payload
