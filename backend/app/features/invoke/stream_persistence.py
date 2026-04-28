"""Persistence helpers for invoke stream chunks and outcomes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from uuid import UUID

from app.db.models.agent_message import AgentMessage
from app.features.invoke.service_types import StreamOutcome
from app.features.invoke.session_binding import resolve_invoke_session_control_intent
from app.features.invoke.stream_payloads import (
    extract_interrupt_lifecycle_from_serialized_event,
    extract_stream_chunk_from_serialized_event,
)
from app.schemas.a2a_invoke import A2AAgentInvokeRequest
from app.utils.idempotency_key import normalize_idempotency_key
from app.utils.session_identity import normalize_non_empty_text

_STREAM_METADATA_SCHEMA_VERSION = 1
STREAM_BLOCK_FLUSH_CHUNK_LIMIT = 20
InvokeTransport = Literal["http_json", "http_sse", "scheduled", "ws"]


class InvokePersistenceState(Protocol):
    local_session_id: UUID | None
    local_source: Literal["manual", "scheduled"] | None
    context_id: str | None
    metadata: dict[str, Any]
    stream_identity: dict[str, Any]
    stream_usage: dict[str, Any]
    user_message_id: str | None
    agent_message_id: str | None
    message_refs: dict[str, UUID] | None
    persisted_response_content: str | None
    persisted_success: bool | None
    persisted_error_code: str | None
    persisted_finish_reason: str | None
    idempotency_key: str | None
    next_event_seq: int
    persisted_block_count: int
    chunk_buffer: list[dict[str, Any]]
    current_block_type: str | None


@dataclass(frozen=True)
class InvokePersistenceRequest:
    user_id: UUID
    agent_id: UUID
    agent_source: Literal["personal", "shared"]
    query: str
    transport: InvokeTransport
    stream_enabled: bool
    user_sender: Literal["user", "automation"] = "user"
    extra_persisted_metadata: dict[str, Any] = field(default_factory=dict)

    def build_extra_metadata(self) -> dict[str, Any]:
        return {
            "transport": self.transport,
            "stream": self.stream_enabled,
            **dict(self.extra_persisted_metadata),
        }


@dataclass(frozen=True)
class PersistedStreamError:
    message: str
    error_code: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"message": self.message}
        if self.error_code:
            payload["error_code"] = self.error_code
        return payload


@dataclass(frozen=True)
class PersistedStreamEnvelope:
    finish_reason: str
    error: PersistedStreamError | None = None
    schema_version: int = _STREAM_METADATA_SCHEMA_VERSION

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "finish_reason": self.finish_reason,
        }
        if self.error is not None:
            payload["error"] = self.error.as_dict()
        return payload


def build_stream_metadata_from_outcome(
    *,
    state: InvokePersistenceState,
    outcome: StreamOutcome,
    response_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    final_metadata = dict(response_metadata or {})
    if state.stream_identity:
        final_metadata.update(state.stream_identity)
    if state.stream_usage:
        final_metadata["usage"] = dict(state.stream_usage)
    normalized_error_message = normalize_non_empty_text(outcome.error_message)
    stream_error = None
    if not outcome.success and (normalized_error_message or outcome.error_code):
        stream_error = PersistedStreamError(
            message=normalized_error_message or str(outcome.error_code or ""),
            error_code=outcome.error_code,
        )
    stream_envelope = PersistedStreamEnvelope(
        finish_reason=outcome.finish_reason.value,
        error=stream_error,
    )
    final_metadata["stream"] = stream_envelope.as_dict()
    return final_metadata


def resolve_invoke_idempotency_key(
    *,
    state: InvokePersistenceState,
    transport: InvokeTransport,
) -> str | None:
    metadata_run_id = None
    if isinstance(state.metadata, dict):
        raw_run_id = state.metadata.get("run_id")
        if isinstance(raw_run_id, str):
            metadata_run_id = normalize_non_empty_text(raw_run_id)
    if metadata_run_id:
        return normalize_idempotency_key(f"run:{metadata_run_id}:{transport}")

    normalized_user_message_id = normalize_non_empty_text(state.user_message_id)
    if normalized_user_message_id:
        return normalize_idempotency_key(
            f"user:{normalized_user_message_id}:{transport}"
        )
    return None


def coerce_uuid(value: Any) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value.strip())
        except (ValueError, TypeError):
            return None
    return None


def resolve_agent_message_id(state: InvokePersistenceState) -> UUID | None:
    if state.agent_message_id:
        return coerce_uuid(state.agent_message_id)
    if isinstance(state.message_refs, dict):
        return coerce_uuid(state.message_refs.get("agent_message_id"))
    return None


def resolve_agent_status_from_outcome(outcome: StreamOutcome) -> str:
    if outcome.success:
        return "done"
    if outcome.finish_reason.value in {
        "client_disconnect",
        "timeout_total",
        "timeout_idle",
    }:
        return "interrupted"
    return "error"


def rewrite_stream_event_contract(
    event_payload: dict[str, Any],
    *,
    local_message_id: str,
    event_id: str,
    seq: int | None,
    stream_block: dict[str, Any] | None = None,
) -> None:
    shared_stream = _ensure_shared_stream_metadata(event_payload)
    if shared_stream is None:
        return
    shared_stream["messageId"] = local_message_id
    if event_id:
        shared_stream["eventId"] = event_id
    if isinstance(seq, int) and seq > 0:
        shared_stream["seq"] = seq
    if isinstance(stream_block, dict):
        field_map = {
            "block_id": "blockId",
            "lane_id": "laneId",
            "op": "op",
            "base_seq": "baseSeq",
        }
        for source_name, target_name in field_map.items():
            value = stream_block.get(source_name)
            if value is not None:
                shared_stream[target_name] = value


def resolve_stream_event_id(
    *,
    stream_block: dict[str, Any],
    local_message_id: str,
    seq: int,
) -> str:
    raw_event_id = stream_block.get("event_id")
    normalized_event_id = normalize_non_empty_text(
        raw_event_id if isinstance(raw_event_id, str) else None
    )
    if normalized_event_id:
        return normalized_event_id
    return f"{local_message_id}:{seq}"


async def ensure_local_message_headers(
    *,
    state: InvokePersistenceState,
    request: InvokePersistenceRequest,
    session_factory: Any,
    commit_fn: Any,
    session_hub: Any,
) -> None:
    if state.local_session_id is None or state.local_source is None:
        return
    existing_agent_id = (
        coerce_uuid(state.message_refs.get("agent_message_id"))
        if isinstance(state.message_refs, dict)
        else None
    )
    existing_user_id = (
        coerce_uuid(state.message_refs.get("user_message_id"))
        if isinstance(state.message_refs, dict)
        else None
    )
    if existing_agent_id is not None and existing_user_id is not None:
        return

    idempotency_key = state.idempotency_key or resolve_invoke_idempotency_key(
        state=state,
        transport=request.transport,
    )
    state.idempotency_key = idempotency_key
    async with session_factory() as persist_db:
        if not hasattr(persist_db, "scalar"):
            return
        refs = (
            await session_hub.ensure_local_invoke_message_headers_by_local_session_id(
                persist_db,
                local_session_id=state.local_session_id,
                source=state.local_source,
                user_id=request.user_id,
                agent_id=request.agent_id,
                agent_source=request.agent_source,
                query=request.query,
                context_id=state.context_id,
                invoke_metadata=state.metadata,
                extra_metadata=request.build_extra_metadata(),
                idempotency_key=idempotency_key,
                user_message_id=coerce_uuid(state.user_message_id),
                agent_message_id=coerce_uuid(state.agent_message_id),
                user_sender=request.user_sender,
            )
        )
        await commit_fn(persist_db)
    if refs:
        state.message_refs = refs
        if state.user_message_id is None:
            resolved_user_message_id = coerce_uuid(refs.get("user_message_id"))
            if resolved_user_message_id is not None:
                state.user_message_id = str(resolved_user_message_id)
        if state.agent_message_id is None:
            resolved_agent_message_id = coerce_uuid(refs.get("agent_message_id"))
            if resolved_agent_message_id is not None:
                state.agent_message_id = str(resolved_agent_message_id)


async def persist_stream_block_update(
    *,
    state: InvokePersistenceState,
    event_payload: dict[str, Any],
    request: InvokePersistenceRequest,
    session_factory: Any,
    commit_fn: Any,
    session_hub: Any,
    ensure_headers_fn: Any = ensure_local_message_headers,
    flush_buffer_fn: Any = None,
) -> None:
    stream_block = extract_stream_chunk_from_serialized_event(event_payload)
    if stream_block is None:
        return
    await ensure_headers_fn(
        state=state,
        request=request,
    )
    if flush_buffer_fn is None:
        flush_buffer_fn = flush_stream_buffer
    agent_message_id = resolve_agent_message_id(state)
    if agent_message_id is None:
        return
    local_message_id = str(agent_message_id)
    persist_seq = state.next_event_seq if state.next_event_seq > 0 else 1
    state.next_event_seq = persist_seq + 1
    resolved_event_id = resolve_stream_event_id(
        stream_block=stream_block,
        local_message_id=local_message_id,
        seq=persist_seq,
    )
    rewrite_stream_event_contract(
        event_payload,
        local_message_id=local_message_id,
        event_id=resolved_event_id,
        seq=persist_seq,
        stream_block=stream_block,
    )

    block_type = str(stream_block.get("block_type") or "text")
    is_finished = bool(stream_block.get("is_finished", False))

    if state.current_block_type is not None and state.current_block_type != block_type:
        await flush_buffer_fn(
            state=state,
            user_id=request.user_id,
            session_factory=session_factory,
            commit_fn=commit_fn,
            session_hub=session_hub,
        )

    state.current_block_type = block_type
    state.chunk_buffer.append(
        {
            "seq": persist_seq,
            "block_type": block_type,
            "content": str(stream_block.get("content") or ""),
            "append": bool(stream_block.get("append", True)),
            "is_finished": is_finished,
            "block_id": stream_block.get("block_id"),
            "lane_id": stream_block.get("lane_id"),
            "op": stream_block.get("op"),
            "base_seq": stream_block.get("base_seq"),
            "event_id": resolved_event_id,
            "source": (
                str(stream_block.get("source"))
                if isinstance(stream_block.get("source"), str)
                else None
            ),
        }
    )

    if is_finished or len(state.chunk_buffer) >= STREAM_BLOCK_FLUSH_CHUNK_LIMIT:
        await flush_buffer_fn(
            state=state,
            user_id=request.user_id,
            session_factory=session_factory,
            commit_fn=commit_fn,
            session_hub=session_hub,
        )


def _ensure_shared_stream_metadata(
    event_payload: dict[str, Any],
) -> dict[str, Any] | None:
    event_body = None
    for field_name in ("artifactUpdate", "message", "statusUpdate", "task"):
        candidate = event_payload.get(field_name)
        if isinstance(candidate, dict):
            event_body = candidate
            break
    if event_body is None:
        return None

    metadata = event_body.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
        event_body["metadata"] = metadata

    shared = metadata.get("shared")
    if not isinstance(shared, dict):
        shared = {}
        metadata["shared"] = shared

    shared_stream = shared.get("stream")
    if not isinstance(shared_stream, dict):
        shared_stream = {}
        shared["stream"] = shared_stream

    return shared_stream


async def persist_interrupt_lifecycle_event(
    *,
    state: InvokePersistenceState,
    event_payload: dict[str, Any],
    request: InvokePersistenceRequest,
    build_interrupt_message_content: Any,
    session_factory: Any,
    commit_fn: Any,
    session_hub: Any,
    ensure_headers_fn: Any = ensure_local_message_headers,
    flush_buffer_fn: Any = None,
) -> None:
    if state.local_session_id is None:
        return
    interrupt_event = extract_interrupt_lifecycle_from_serialized_event(event_payload)
    if interrupt_event is None:
        return
    await ensure_headers_fn(
        state=state,
        request=request,
    )
    if flush_buffer_fn is None:
        flush_buffer_fn = flush_stream_buffer
    agent_message_id = resolve_agent_message_id(state)
    if agent_message_id is None:
        return
    await flush_buffer_fn(
        state=state,
        user_id=request.user_id,
        session_factory=session_factory,
        commit_fn=commit_fn,
        session_hub=session_hub,
    )
    persist_seq = state.next_event_seq if state.next_event_seq > 0 else 1
    interrupt_event_id = (
        f"interrupt:{agent_message_id}:"
        f"{interrupt_event['request_id']}:{interrupt_event['phase']}"
    )
    async with session_factory() as persist_db:
        if not hasattr(persist_db, "scalar"):
            return
        persisted_block = await session_hub.append_agent_message_block_update(
            persist_db,
            user_id=request.user_id,
            agent_message_id=agent_message_id,
            seq=persist_seq,
            block_type="interrupt_event",
            content=build_interrupt_message_content(interrupt_event),
            append=False,
            is_finished=True,
            block_id=f"{agent_message_id}:interrupt:{interrupt_event['request_id']}",
            lane_id="interrupt_event",
            operation="replace",
            base_seq=persist_seq,
            event_id=interrupt_event_id,
            source="interrupt_lifecycle",
        )
        if persisted_block is None:
            return
        await commit_fn(persist_db)
    state.next_event_seq = persist_seq + 1
    state.persisted_block_count += 1


async def flush_stream_buffer(
    *,
    state: InvokePersistenceState,
    user_id: UUID,
    session_factory: Any,
    commit_fn: Any,
    session_hub: Any,
) -> None:
    if not state.chunk_buffer:
        return

    agent_message_id = resolve_agent_message_id(state)
    if agent_message_id is None:
        return

    async with session_factory() as persist_db:
        if not hasattr(persist_db, "scalar"):
            return

        from sqlalchemy import and_, select

        agent_message = await persist_db.scalar(
            select(AgentMessage).where(
                and_(
                    AgentMessage.id == agent_message_id,
                    AgentMessage.user_id == user_id,
                    AgentMessage.sender == "agent",
                )
            )
        )
        if agent_message is None:
            return

        persisted_blocks = await session_hub.append_agent_message_block_updates(
            persist_db,
            user_id=user_id,
            agent_message_id=agent_message_id,
            updates=state.chunk_buffer,
            agent_message=agent_message,
        )
        if not persisted_blocks:
            return
        await commit_fn(persist_db)
        state.persisted_block_count += len(persisted_blocks)
        state.chunk_buffer = []


async def persist_local_outcome(
    *,
    state: InvokePersistenceState,
    outcome: StreamOutcome,
    request: InvokePersistenceRequest,
    response_metadata: dict[str, Any] | None = None,
    session_factory: Any,
    commit_fn: Any,
    session_hub: Any,
    ensure_headers_fn: Any = ensure_local_message_headers,
    persist_final_block_fn: Any = None,
) -> None:
    if state.local_session_id is None or state.local_source is None:
        return
    await ensure_headers_fn(
        state=state,
        request=request,
    )
    if persist_final_block_fn is None:
        persist_final_block_fn = persist_synthetic_final_block_if_needed
    await persist_final_block_fn(
        state=state,
        outcome=outcome,
        user_id=request.user_id,
        session_factory=session_factory,
        commit_fn=commit_fn,
        session_hub=session_hub,
    )
    persisted_content = outcome.final_text or str(outcome.error_message or "")
    metadata_payload = build_stream_metadata_from_outcome(
        state=state,
        outcome=outcome,
        response_metadata=response_metadata,
    )
    idempotency_key = state.idempotency_key or resolve_invoke_idempotency_key(
        state=state,
        transport=request.transport,
    )
    state.idempotency_key = idempotency_key
    async with session_factory() as persist_db:
        message_refs = (
            await session_hub.record_local_invoke_messages_by_local_session_id(
                persist_db,
                local_session_id=state.local_session_id,
                source=state.local_source,
                user_id=request.user_id,
                agent_id=request.agent_id,
                agent_source=request.agent_source,
                query=request.query,
                response_content=persisted_content,
                success=outcome.success,
                context_id=state.context_id,
                invoke_metadata=state.metadata,
                extra_metadata=request.build_extra_metadata(),
                response_metadata=metadata_payload,
                idempotency_key=idempotency_key,
                agent_status=resolve_agent_status_from_outcome(outcome),
                finish_reason=outcome.finish_reason.value,
                error_code=outcome.error_code,
                user_message_id=coerce_uuid(state.user_message_id),
                agent_message_id=coerce_uuid(state.agent_message_id),
                user_sender=request.user_sender,
            )
        )
        raw_task_id = (
            state.stream_identity.get("upstream_task_id")
            if isinstance(state.stream_identity, dict)
            else None
        )
        normalized_task_id = normalize_non_empty_text(
            raw_task_id if isinstance(raw_task_id, str) else None
        )
        if normalized_task_id:
            binding_conversation_id = coerce_uuid(message_refs.get("conversation_id"))
            binding_agent_message_id = coerce_uuid(message_refs.get("agent_message_id"))
            await session_hub.record_upstream_task_binding(
                persist_db,
                user_id=request.user_id,
                conversation_id=binding_conversation_id or state.local_session_id,
                task_id=normalized_task_id,
                agent_id=request.agent_id,
                agent_source=request.agent_source,
                message_id=binding_agent_message_id,
                source="final_metadata",
                status_hint=resolve_agent_status_from_outcome(outcome),
            )
        await commit_fn(persist_db)
    state.message_refs = message_refs
    state.persisted_success = outcome.success
    state.persisted_response_content = persisted_content
    state.persisted_error_code = outcome.error_code
    state.persisted_finish_reason = outcome.finish_reason.value


async def persist_synthetic_final_block_if_needed(
    *,
    state: InvokePersistenceState,
    outcome: StreamOutcome,
    user_id: UUID,
    session_factory: Any,
    commit_fn: Any,
    session_hub: Any,
) -> None:
    if not isinstance(outcome.final_text, str) or not outcome.final_text:
        return
    if state.local_session_id is None or state.local_source is None:
        return
    agent_message_id = resolve_agent_message_id(state)
    if agent_message_id is None:
        return
    async with session_factory() as persist_db:
        if not hasattr(persist_db, "scalar"):
            return
        has_blocks = await session_hub.has_agent_message_blocks(
            persist_db,
            user_id=user_id,
            agent_message_id=agent_message_id,
        )
        if has_blocks:
            return
        resolved_seq = state.next_event_seq if state.next_event_seq > 0 else 1
        persisted_block = await session_hub.append_agent_message_block_update(
            persist_db,
            user_id=user_id,
            agent_message_id=agent_message_id,
            seq=resolved_seq,
            block_type="text",
            content=outcome.final_text,
            append=False,
            is_finished=True,
            block_id=f"{agent_message_id}:primary_text:final",
            lane_id="primary_text",
            operation="replace",
            base_seq=resolved_seq,
            event_id=None,
            source="finalize_snapshot",
        )
        if persisted_block is None:
            return
        await commit_fn(persist_db)
        state.next_event_seq = max(state.next_event_seq, resolved_seq + 1)
        state.persisted_block_count += 1


def is_interrupt_requested(payload: A2AAgentInvokeRequest) -> bool:
    return resolve_invoke_session_control_intent(payload) == "preempt"
