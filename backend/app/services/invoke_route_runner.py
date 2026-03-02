"""Shared invoke flow runner for personal/hub A2A route handlers."""

from __future__ import annotations

import asyncio
import inspect
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal
from uuid import UUID

from fastapi import HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.error_codes import status_code_for_invoke_error_code
from app.db.locking import (
    is_postgres_lock_not_available_error,
    is_postgres_statement_timeout_error,
)
from app.db.session import AsyncSessionLocal
from app.db.transaction import commit_safely
from app.schemas.a2a_invoke import A2AAgentInvokeRequest, A2AAgentInvokeResponse
from app.schemas.ws_ticket import WsTicketResponse
from app.services.a2a_invoke_service import StreamOutcome, a2a_invoke_service
from app.services.invoke_session_binding import (
    is_recoverable_invoke_session_error,
    merge_invoke_binding_state,
    normalize_invoke_binding_state,
    status_code_for_invoke_session_error,
    ws_error_code_for_invoke_session_error,
    ws_error_code_for_recovery_failed,
)
from app.services.session_hub import session_hub_service
from app.services.ws_ticket_service import ws_ticket_service
from app.utils.idempotency_key import normalize_idempotency_key
from app.utils.payload_extract import (
    as_dict,
    extract_context_id,
    extract_provider_and_external_session_id,
)
from app.utils.session_identity import normalize_non_empty_text

AgentSource = Literal["personal", "shared"]

_invoke_inflight_guard = asyncio.Lock()
_invoke_inflight_keys: dict[str, int] = {}

_SESSION_NOT_FOUND_RETRY_LIMIT = 1
_SESSION_NOT_FOUND_RECOVERY_EXHAUSTED_MESSAGE = (
    "Failed to recover conversation session. Please retry."
)
_STREAM_METADATA_SCHEMA_VERSION = 1


@dataclass
class _InvokeState:
    local_session_id: UUID | None
    local_source: Literal["manual", "scheduled"] | None
    context_id: str | None
    metadata: dict[str, Any]
    stream_identity: dict[str, Any]
    stream_usage: dict[str, Any]
    user_message_id: str | None = None
    agent_message_id: str | None = None
    message_refs: dict[str, UUID] | None = None
    persisted_response_content: str | None = None
    persisted_success: bool | None = None
    persisted_error_code: str | None = None
    persisted_finish_reason: str | None = None
    idempotency_key: str | None = None
    inflight_token: str | None = None
    upstream_task_id: str | None = None
    next_event_seq: int = 1
    persisted_block_count: int = 0


@dataclass(frozen=True)
class _PersistedStreamError:
    message: str
    error_code: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"message": self.message}
        if self.error_code:
            payload["error_code"] = self.error_code
        return payload


@dataclass(frozen=True)
class _PersistedStreamEnvelope:
    finish_reason: str
    error: _PersistedStreamError | None = None
    schema_version: int = _STREAM_METADATA_SCHEMA_VERSION

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "finish_reason": self.finish_reason,
        }
        if self.error is not None:
            payload["error"] = self.error.as_dict()
        return payload


def _normalize_query_for_invoke_guard(query: str) -> str:
    return " ".join(query.split())


def _is_interrupt_requested(payload: A2AAgentInvokeRequest) -> bool:
    metadata = payload.metadata if isinstance(payload.metadata, dict) else {}
    extensions = metadata.get("extensions")
    if not isinstance(extensions, dict):
        return False
    return extensions.get("interrupt") is True


def _build_invoke_guard_key(
    *,
    user_id: UUID,
    agent_id: UUID,
    agent_source: AgentSource,
    payload: A2AAgentInvokeRequest,
) -> str | None:
    conversation_id = (
        payload.conversation_id.strip()
        if isinstance(payload.conversation_id, str)
        else ""
    )
    context_id = (
        payload.context_id.strip() if isinstance(payload.context_id, str) else ""
    )
    if not conversation_id and not context_id:
        return None
    normalized_query = _normalize_query_for_invoke_guard(payload.query)
    return (
        f"{user_id}:{agent_source}:{agent_id}:{conversation_id}:{context_id}:"
        f"{normalized_query}"
    )


@asynccontextmanager
async def _guard_inflight_invoke(
    guard_key: str | None,
):
    if not guard_key:
        yield
        return

    acquired = await _try_acquire_invoke_guard(guard_key)
    if not acquired:
        raise ValueError("invoke_inflight")

    try:
        yield
    finally:
        await _release_invoke_guard(guard_key)


async def _try_acquire_invoke_guard(guard_key: str) -> bool:
    async with _invoke_inflight_guard:
        active_count = _invoke_inflight_keys.get(guard_key, 0)
        if active_count > 0:
            return False
        _invoke_inflight_keys[guard_key] = 1
        return True


async def _release_invoke_guard(guard_key: str) -> None:
    async with _invoke_inflight_guard:
        remaining = _invoke_inflight_keys.get(guard_key, 0) - 1
        if remaining <= 0:
            _invoke_inflight_keys.pop(guard_key, None)
        else:
            _invoke_inflight_keys[guard_key] = remaining


async def _prepare_state(
    *,
    user_id: UUID,
    agent_id: UUID,
    agent_source: AgentSource,
    payload: A2AAgentInvokeRequest,
) -> _InvokeState:
    local_session_id: UUID | None = None
    local_source: Literal["manual", "scheduled"] | None = None
    async with AsyncSessionLocal() as prepare_db:
        (
            local_session,
            local_source,
        ) = await session_hub_service.ensure_local_session_for_invoke(
            prepare_db,
            user_id=user_id,
            agent_id=agent_id,
            agent_source=agent_source,
            conversation_id=payload.conversation_id,
        )
        if local_session is not None and isinstance(local_session.id, UUID):
            local_session_id = local_session.id
        await commit_safely(prepare_db)

    resolved_context_id, resolved_invoke_metadata = normalize_invoke_binding_state(
        context_id=payload.context_id,
        metadata=payload.metadata,
    )
    normalized_user_message_id = _normalize_optional_message_id(payload.user_message_id)
    normalized_agent_message_id = _normalize_optional_message_id(
        payload.agent_message_id
    )
    return _InvokeState(
        local_session_id=local_session_id,
        local_source=local_source,
        context_id=resolved_context_id,
        metadata=resolved_invoke_metadata,
        stream_identity={},
        stream_usage={},
        user_message_id=normalized_user_message_id,
        agent_message_id=normalized_agent_message_id,
        message_refs=None,
        persisted_response_content=None,
        persisted_success=None,
        persisted_error_code=None,
    )


async def _register_inflight_invoke(
    *,
    state: _InvokeState,
    user_id: UUID,
    gateway: Any,
    resolved: Any,
) -> None:
    if state.local_session_id is None:
        return
    state.inflight_token = await session_hub_service.register_inflight_invoke(
        user_id=user_id,
        conversation_id=state.local_session_id,
        gateway=gateway,
        resolved=resolved,
    )


async def _preempt_previous_invoke_if_requested(
    *,
    state: _InvokeState,
    payload: A2AAgentInvokeRequest,
    user_id: UUID,
) -> None:
    if state.local_session_id is None:
        return
    if not _is_interrupt_requested(payload):
        return
    await session_hub_service.preempt_inflight_invoke(
        user_id=user_id,
        conversation_id=state.local_session_id,
        reason="invoke_interrupt",
    )


async def _bind_inflight_task_if_needed(
    *,
    state: _InvokeState,
    user_id: UUID,
) -> None:
    if state.local_session_id is None or state.inflight_token is None:
        return
    raw_task_id = (
        state.stream_identity.get("upstream_task_id")
        if isinstance(state.stream_identity, dict)
        else None
    )
    normalized_task_id = normalize_non_empty_text(
        raw_task_id if isinstance(raw_task_id, str) else None
    )
    if not normalized_task_id or normalized_task_id == state.upstream_task_id:
        return
    bound = await session_hub_service.bind_inflight_task_id(
        user_id=user_id,
        conversation_id=state.local_session_id,
        token=state.inflight_token,
        task_id=normalized_task_id,
    )
    if bound:
        state.upstream_task_id = normalized_task_id


async def _unregister_inflight_invoke(
    *,
    state: _InvokeState,
    user_id: UUID,
) -> None:
    if state.local_session_id is None or state.inflight_token is None:
        return
    await session_hub_service.unregister_inflight_invoke(
        user_id=user_id,
        conversation_id=state.local_session_id,
        token=state.inflight_token,
    )
    state.inflight_token = None


async def _close_open_transaction(db: AsyncSession) -> None:
    in_transaction = getattr(db, "in_transaction", None)
    commit = getattr(db, "commit", None)
    if not callable(in_transaction) or not callable(commit):
        return
    if not in_transaction():
        return
    # Never auto-commit when there are pending ORM writes in the session.
    # Route-level closing here is only for read-only transactions.
    for attribute_name in ("new", "dirty", "deleted"):
        collection = getattr(db, attribute_name, None)
        if collection is None:
            continue
        try:
            if len(collection) > 0:
                return
        except Exception:
            try:
                if bool(collection):
                    return
            except Exception:
                return
    commit_outcome = commit()
    if inspect.isawaitable(commit_outcome):
        await commit_outcome


async def _continue_session_with_short_transaction(
    *,
    user_id: UUID,
    conversation_id: str,
) -> dict[str, Any]:
    async with AsyncSessionLocal() as short_db:
        continue_binding, db_mutated = await session_hub_service.continue_session(
            short_db,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        if db_mutated:
            await commit_safely(short_db)
        else:
            await _close_open_transaction(short_db)
        return continue_binding


def _collect_stream_hints(
    *, state: _InvokeState, event_payload: dict[str, Any]
) -> None:
    (
        event_context_id,
        event_metadata,
    ) = a2a_invoke_service.extract_binding_hints_from_serialized_event(event_payload)
    state.context_id, state.metadata = merge_invoke_binding_state(
        current_context_id=state.context_id,
        current_metadata=state.metadata,
        next_context_id=event_context_id,
        next_metadata=event_metadata,
    )
    identity_hints = (
        a2a_invoke_service.extract_stream_identity_hints_from_serialized_event(
            event_payload
        )
    )
    if identity_hints:
        state.stream_identity.update(identity_hints)
    usage_hints = a2a_invoke_service.extract_usage_hints_from_serialized_event(
        event_payload
    )
    if usage_hints:
        state.stream_usage = usage_hints


def _build_stream_metadata_from_outcome(
    *,
    state: _InvokeState,
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
        stream_error = _PersistedStreamError(
            message=normalized_error_message or str(outcome.error_code or ""),
            error_code=outcome.error_code,
        )
    stream_envelope = _PersistedStreamEnvelope(
        finish_reason=outcome.finish_reason.value,
        error=stream_error,
    )
    final_metadata["stream"] = stream_envelope.as_dict()
    return final_metadata


def _resolve_invoke_idempotency_key(
    *,
    state: _InvokeState,
    transport: Literal["http_json", "http_sse", "scheduled", "ws"],
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


def _coerce_uuid(value: Any) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value.strip())
        except (ValueError, TypeError):
            return None
    return None


def _normalize_optional_message_id(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    resolved = _coerce_uuid(trimmed)
    if resolved is None:
        raise ValueError("invalid_message_id")
    return str(resolved)


def _resolve_agent_status_from_outcome(outcome: StreamOutcome) -> str:
    if outcome.success:
        return "done"
    if outcome.finish_reason.value in {
        "client_disconnect",
        "timeout_total",
        "timeout_idle",
    }:
        return "interrupted"
    return "error"


def _rewrite_stream_event_contract(
    event_payload: dict[str, Any],
    *,
    local_message_id: str,
    event_id: str | None = None,
    seq: int | None = None,
) -> None:
    if event_payload.get("kind") != "artifact-update":
        return
    event_payload.pop("messageId", None)
    event_payload.pop("eventId", None)
    event_payload.pop("eventSeq", None)
    event_payload.pop("sequence", None)
    event_payload["message_id"] = local_message_id
    if event_id:
        event_payload["event_id"] = event_id
    if isinstance(seq, int) and seq > 0:
        event_payload["seq"] = seq

    artifact = event_payload.get("artifact")
    if isinstance(artifact, dict):
        artifact.pop("messageId", None)
        artifact.pop("eventId", None)
        artifact.pop("eventSeq", None)
        artifact.pop("sequence", None)
        artifact["message_id"] = local_message_id
        if event_id:
            artifact["event_id"] = event_id
        if isinstance(seq, int) and seq > 0:
            artifact["seq"] = seq
        metadata = artifact.get("metadata")
        if isinstance(metadata, dict):
            opencode = metadata.get("opencode")
            if isinstance(opencode, dict):
                opencode.pop("messageId", None)
                opencode.pop("eventId", None)
                opencode.pop("eventSeq", None)
                opencode.pop("sequence", None)
                opencode["message_id"] = local_message_id
                if event_id:
                    opencode["event_id"] = event_id
                if isinstance(seq, int) and seq > 0:
                    opencode["seq"] = seq


async def _ensure_local_message_headers(
    *,
    state: _InvokeState,
    user_id: UUID,
    agent_id: UUID,
    agent_source: AgentSource,
    query: str,
    transport: Literal["http_json", "http_sse", "scheduled", "ws"],
    stream_enabled: bool,
) -> None:
    if state.local_session_id is None or state.local_source is None:
        return
    existing_agent_id = (
        _coerce_uuid(state.message_refs.get("agent_message_id"))
        if isinstance(state.message_refs, dict)
        else None
    )
    existing_user_id = (
        _coerce_uuid(state.message_refs.get("user_message_id"))
        if isinstance(state.message_refs, dict)
        else None
    )
    if existing_agent_id is not None and existing_user_id is not None:
        return

    idempotency_key = state.idempotency_key or _resolve_invoke_idempotency_key(
        state=state,
        transport=transport,
    )
    state.idempotency_key = idempotency_key
    async with AsyncSessionLocal() as persist_db:
        if not hasattr(persist_db, "scalar"):
            return
        refs = await session_hub_service.ensure_local_invoke_message_headers_by_local_session_id(
            persist_db,
            local_session_id=state.local_session_id,
            source=state.local_source,
            user_id=user_id,
            agent_id=agent_id,
            agent_source=agent_source,
            query=query,
            context_id=state.context_id,
            invoke_metadata=state.metadata,
            extra_metadata={"transport": transport, "stream": stream_enabled},
            idempotency_key=idempotency_key,
            user_message_id=_coerce_uuid(state.user_message_id),
            agent_message_id=_coerce_uuid(state.agent_message_id),
        )
        await commit_safely(persist_db)
    if refs:
        state.message_refs = refs
        if state.user_message_id is None:
            resolved_user_message_id = _coerce_uuid(refs.get("user_message_id"))
            if resolved_user_message_id is not None:
                state.user_message_id = str(resolved_user_message_id)
        if state.agent_message_id is None:
            resolved_agent_message_id = _coerce_uuid(refs.get("agent_message_id"))
            if resolved_agent_message_id is not None:
                state.agent_message_id = str(resolved_agent_message_id)


async def _persist_stream_block_update(
    *,
    state: _InvokeState,
    event_payload: dict[str, Any],
    user_id: UUID,
    agent_id: UUID,
    agent_source: AgentSource,
    query: str,
    transport: Literal["http_json", "http_sse", "scheduled", "ws"],
    stream_enabled: bool,
) -> None:
    stream_block = a2a_invoke_service.extract_stream_chunk_from_serialized_event(
        event_payload
    )
    if stream_block is None:
        return
    await _ensure_local_message_headers(
        state=state,
        user_id=user_id,
        agent_id=agent_id,
        agent_source=agent_source,
        query=query,
        transport=transport,
        stream_enabled=stream_enabled,
    )
    agent_message_id = (
        _coerce_uuid(state.message_refs.get("agent_message_id"))
        if isinstance(state.message_refs, dict)
        else None
    )
    if agent_message_id is None:
        return
    raw_seq = stream_block.get("seq")
    resolved_seq = raw_seq if isinstance(raw_seq, int) and raw_seq > 0 else None
    if resolved_seq is None:
        resolved_seq = state.next_event_seq
    state.next_event_seq = max(state.next_event_seq, resolved_seq + 1)
    _rewrite_stream_event_contract(
        event_payload,
        local_message_id=str(agent_message_id),
        event_id=(
            str(stream_block.get("event_id"))
            if isinstance(stream_block.get("event_id"), str)
            else None
        ),
        seq=resolved_seq,
    )

    async with AsyncSessionLocal() as persist_db:
        if not hasattr(persist_db, "scalar"):
            return
        persisted_block = await session_hub_service.append_agent_message_block_update(
            persist_db,
            user_id=user_id,
            agent_message_id=agent_message_id,
            seq=resolved_seq,
            block_type=str(stream_block.get("block_type") or "text"),
            content=str(stream_block.get("content") or ""),
            append=bool(stream_block.get("append", True)),
            is_finished=bool(stream_block.get("is_finished", False)),
            event_id=(
                str(stream_block.get("event_id"))
                if isinstance(stream_block.get("event_id"), str)
                else None
            ),
            source=(
                str(stream_block.get("source"))
                if isinstance(stream_block.get("source"), str)
                else None
            ),
        )
        if persisted_block is not None:
            await commit_safely(persist_db)
            state.persisted_block_count += 1


async def _persist_local_outcome(
    *,
    state: _InvokeState,
    outcome: StreamOutcome,
    user_id: UUID,
    agent_id: UUID,
    agent_source: AgentSource,
    query: str,
    transport: Literal["http_json", "http_sse", "scheduled", "ws"],
    stream_enabled: bool,
    response_metadata: dict[str, Any] | None = None,
) -> None:
    if state.local_session_id is None or state.local_source is None:
        return
    await _ensure_local_message_headers(
        state=state,
        user_id=user_id,
        agent_id=agent_id,
        agent_source=agent_source,
        query=query,
        transport=transport,
        stream_enabled=stream_enabled,
    )
    await _persist_synthetic_final_block_if_needed(
        state=state,
        outcome=outcome,
        user_id=user_id,
    )
    persisted_content = outcome.final_text or str(outcome.error_message or "")
    metadata_payload = _build_stream_metadata_from_outcome(
        state=state,
        outcome=outcome,
        response_metadata=response_metadata,
    )
    idempotency_key = state.idempotency_key or _resolve_invoke_idempotency_key(
        state=state,
        transport=transport,
    )
    state.idempotency_key = idempotency_key
    async with AsyncSessionLocal() as persist_db:
        message_refs = (
            await session_hub_service.record_local_invoke_messages_by_local_session_id(
                persist_db,
                local_session_id=state.local_session_id,
                source=state.local_source,
                user_id=user_id,
                agent_id=agent_id,
                agent_source=agent_source,
                query=query,
                response_content=persisted_content,
                success=outcome.success,
                context_id=state.context_id,
                invoke_metadata=state.metadata,
                extra_metadata={"transport": transport, "stream": stream_enabled},
                response_metadata=metadata_payload,
                idempotency_key=idempotency_key,
                agent_status=_resolve_agent_status_from_outcome(outcome),
                finish_reason=outcome.finish_reason.value,
                error_code=outcome.error_code,
                user_message_id=_coerce_uuid(state.user_message_id),
                agent_message_id=_coerce_uuid(state.agent_message_id),
            )
        )
        await commit_safely(persist_db)
    state.message_refs = message_refs
    state.persisted_success = outcome.success
    state.persisted_response_content = persisted_content
    state.persisted_error_code = outcome.error_code
    state.persisted_finish_reason = outcome.finish_reason.value


async def _persist_synthetic_final_block_if_needed(
    *,
    state: _InvokeState,
    outcome: StreamOutcome,
    user_id: UUID,
) -> None:
    if not isinstance(outcome.final_text, str) or not outcome.final_text:
        return
    if state.local_session_id is None or state.local_source is None:
        return
    agent_message_id = (
        _coerce_uuid(state.message_refs.get("agent_message_id"))
        if isinstance(state.message_refs, dict)
        else None
    )
    if agent_message_id is None:
        return
    async with AsyncSessionLocal() as persist_db:
        if not hasattr(persist_db, "scalar"):
            return
        has_blocks = await session_hub_service.has_agent_message_blocks(
            persist_db,
            user_id=user_id,
            agent_message_id=agent_message_id,
        )
        if has_blocks:
            return
        resolved_seq = state.next_event_seq if state.next_event_seq > 0 else 1
        persisted_block = await session_hub_service.append_agent_message_block_update(
            persist_db,
            user_id=user_id,
            agent_message_id=agent_message_id,
            seq=resolved_seq,
            block_type="text",
            content=outcome.final_text,
            append=False,
            is_finished=True,
            event_id=None,
            source="finalize_snapshot",
        )
        if persisted_block is None:
            return
        await commit_safely(persist_db)
        state.next_event_seq = max(state.next_event_seq, resolved_seq + 1)
        state.persisted_block_count += 1


def _build_consume_stream_callbacks(
    *,
    state: _InvokeState,
    user_id: UUID,
    agent_id: UUID,
    agent_source: AgentSource,
    query: str,
    transport: Literal["http_json", "http_sse", "scheduled", "ws"],
    stream_enabled: bool,
) -> tuple[
    Callable[[dict[str, Any]], Any],
    Callable[[StreamOutcome], Any],
]:
    async def on_event(event_payload: dict[str, Any]) -> None:
        _collect_stream_hints(state=state, event_payload=event_payload)
        await _bind_inflight_task_if_needed(state=state, user_id=user_id)
        await _persist_stream_block_update(
            state=state,
            event_payload=event_payload,
            user_id=user_id,
            agent_id=agent_id,
            agent_source=agent_source,
            query=query,
            transport=transport,
            stream_enabled=stream_enabled,
        )

    async def on_finalized(outcome: StreamOutcome) -> None:
        try:
            await _persist_local_outcome(
                state=state,
                outcome=outcome,
                user_id=user_id,
                agent_id=agent_id,
                agent_source=agent_source,
                query=query,
                transport=transport,
                stream_enabled=stream_enabled,
            )
        finally:
            await _unregister_inflight_invoke(state=state, user_id=user_id)

    return on_event, on_finalized


def _extract_rebound_continue_binding_fields(
    *,
    continue_payload: dict[str, Any],
) -> tuple[str | None, str | None, str | None]:
    """Resolve provider/context binding from the continue payload metadata."""
    continue_payload_dict = as_dict(continue_payload)
    continue_metadata = as_dict(continue_payload_dict.get("metadata"))

    provider, external_session_id = extract_provider_and_external_session_id(
        continue_metadata
    )
    context_id = extract_context_id(continue_metadata)

    return provider, external_session_id, context_id


def _build_rebound_invoke_payload(
    *,
    payload: A2AAgentInvokeRequest,
    continue_payload: dict[str, Any],
) -> A2AAgentInvokeRequest:
    (
        provider,
        external_session_id,
        context_id,
    ) = _extract_rebound_continue_binding_fields(continue_payload=continue_payload)
    conversation_id = continue_payload.get("conversationId")

    normalized_provider = provider.lower() if provider else ""
    normalized_external_session_id = external_session_id or ""
    next_metadata = dict(payload.metadata or {})
    if normalized_provider:
        next_metadata["provider"] = normalized_provider
    if normalized_external_session_id:
        next_metadata["externalSessionId"] = normalized_external_session_id
    next_context_id = normalize_non_empty_text(context_id) or payload.context_id
    next_conversation_id = (
        normalize_non_empty_text(conversation_id) or payload.conversation_id
    )

    return payload.model_copy(
        update={
            "conversation_id": next_conversation_id,
            "context_id": next_context_id,
            "metadata": next_metadata,
        },
    )


async def run_http_invoke_with_session_recovery(
    *,
    db: AsyncSession,
    gateway: Any,
    runtime: Any,
    user_id: UUID,
    agent_id: UUID,
    agent_source: AgentSource,
    payload: A2AAgentInvokeRequest,
    stream: bool,
    validate_message: Callable[[dict[str, Any]], list[Any]],
    logger: Any,
    log_extra: dict[str, Any],
    max_recovery_attempts: int = _SESSION_NOT_FOUND_RETRY_LIMIT,
) -> A2AAgentInvokeResponse | StreamingResponse:
    current_payload = payload
    remaining_retries = max_recovery_attempts

    while True:
        response = await run_http_invoke(
            db=db,
            gateway=gateway,
            runtime=runtime,
            user_id=user_id,
            agent_id=agent_id,
            agent_source=agent_source,
            payload=current_payload,
            stream=stream,
            validate_message=validate_message,
            logger=logger,
            log_extra=log_extra,
        )
        if stream or response.success:
            return response
        if not is_recoverable_invoke_session_error(response.error_code):
            return response
        if remaining_retries <= 0:
            return response
        if not isinstance(current_payload.conversation_id, str):
            return response

        remaining_retries -= 1
        try:
            continue_binding = await _continue_session_with_short_transaction(
                user_id=user_id,
                conversation_id=current_payload.conversation_id,
            )
        except ValueError:
            return response
        current_payload = _build_rebound_invoke_payload(
            payload=current_payload,
            continue_payload=continue_binding,
        )


async def run_http_invoke(
    *,
    db: AsyncSession,
    gateway: Any,
    runtime: Any,
    user_id: UUID,
    agent_id: UUID,
    agent_source: AgentSource,
    payload: A2AAgentInvokeRequest,
    stream: bool,
    validate_message: Callable[[dict[str, Any]], list[Any]],
    logger: Any,
    log_extra: dict[str, Any],
) -> A2AAgentInvokeResponse | StreamingResponse:
    state = await _prepare_state(
        user_id=user_id,
        agent_id=agent_id,
        agent_source=agent_source,
        payload=payload,
    )
    await _preempt_previous_invoke_if_requested(
        state=state,
        payload=payload,
        user_id=user_id,
    )
    await _register_inflight_invoke(
        state=state,
        user_id=user_id,
        gateway=gateway,
        resolved=runtime.resolved,
    )

    if stream:
        on_event, on_finalized = _build_consume_stream_callbacks(
            state=state,
            user_id=user_id,
            agent_id=agent_id,
            agent_source=agent_source,
            query=payload.query,
            transport="http_sse",
            stream_enabled=True,
        )
        try:
            return a2a_invoke_service.stream_sse(
                gateway=gateway,
                resolved=runtime.resolved,
                query=payload.query,
                context_id=payload.context_id,
                metadata=payload.metadata,
                validate_message=validate_message,
                logger=logger,
                log_extra=log_extra,
                on_event=on_event,
                on_finalized=on_finalized,
                resume_from_sequence=payload.resume_from_sequence,
                cache_key=state.user_message_id,
            )
        except Exception:
            await _unregister_inflight_invoke(state=state, user_id=user_id)
            raise

    on_event, on_finalized = _build_consume_stream_callbacks(
        state=state,
        user_id=user_id,
        agent_id=agent_id,
        agent_source=agent_source,
        query=payload.query,
        transport="http_json",
        stream_enabled=False,
    )
    try:
        outcome = await a2a_invoke_service.consume_stream(
            gateway=gateway,
            resolved=runtime.resolved,
            query=payload.query,
            context_id=payload.context_id,
            metadata=payload.metadata,
            validate_message=validate_message,
            logger=logger,
            log_extra=log_extra,
            on_event=on_event,
            on_finalized=on_finalized,
        )
    except Exception:
        await _unregister_inflight_invoke(state=state, user_id=user_id)
        raise
    success = bool(outcome.success)
    content = state.persisted_response_content
    if content is None:
        content = outcome.final_text
    error = None if success else (outcome.error_message or content)
    error_code = (
        state.persisted_error_code
        if not success and state.persisted_error_code
        else outcome.error_code
    )
    return A2AAgentInvokeResponse(
        success=success,
        content=content,
        error=error,
        error_code=error_code,
        agent_name=runtime.resolved.name,
        agent_url=runtime.resolved.url,
    )


async def run_background_invoke(
    *,
    db: AsyncSession,
    gateway: Any,
    runtime: Any,
    user_id: UUID,
    agent_id: UUID,
    agent_source: AgentSource,
    payload: A2AAgentInvokeRequest,
    validate_message: Callable[[dict[str, Any]], list[Any]],
    logger: Any,
    log_extra: dict[str, Any],
    total_timeout_seconds: float | None = None,
    idle_timeout_seconds: float | None = None,
) -> dict[str, Any]:
    state = await _prepare_state(
        user_id=user_id,
        agent_id=agent_id,
        agent_source=agent_source,
        payload=payload,
    )
    await _preempt_previous_invoke_if_requested(
        state=state,
        payload=payload,
        user_id=user_id,
    )
    await _register_inflight_invoke(
        state=state,
        user_id=user_id,
        gateway=gateway,
        resolved=runtime.resolved,
    )

    on_event, on_finalized = _build_consume_stream_callbacks(
        state=state,
        user_id=user_id,
        agent_id=agent_id,
        agent_source=agent_source,
        query=payload.query,
        transport="scheduled",
        stream_enabled=True,
    )
    try:
        outcome = await a2a_invoke_service.consume_stream(
            gateway=gateway,
            resolved=runtime.resolved,
            query=payload.query,
            context_id=payload.context_id,
            metadata=payload.metadata,
            validate_message=validate_message,
            logger=logger,
            log_extra=log_extra,
            on_event=on_event,
            on_finalized=on_finalized,
            total_timeout_seconds=total_timeout_seconds,
            idle_timeout_seconds=idle_timeout_seconds,
        )
    except Exception:
        await _unregister_inflight_invoke(state=state, user_id=user_id)
        raise
    success = bool(outcome.success)
    response_content = state.persisted_response_content
    if response_content is None:
        fallback_value = outcome.final_text or outcome.error_message
        response_content = str(fallback_value or "")
    return {
        "success": success,
        "response_content": response_content,
        "error": outcome.error_message,
        "error_code": state.persisted_error_code or outcome.error_code,
        "conversation_id": (
            state.message_refs.get("conversation_id") if state.message_refs else None
        ),
        "message_refs": dict(state.message_refs) if state.message_refs else {},
        "context_id": state.context_id,
    }


async def run_ws_invoke(
    *,
    websocket: WebSocket,
    db: AsyncSession,
    gateway: Any,
    runtime: Any,
    user_id: UUID,
    agent_id: UUID,
    agent_source: AgentSource,
    payload: A2AAgentInvokeRequest,
    validate_message: Callable[[dict[str, Any]], list[Any]],
    logger: Any,
    log_extra: dict[str, Any],
    on_error_metadata: Callable[[dict[str, Any]], Any] | None = None,
    send_stream_end: bool = True,
) -> None:
    state = await _prepare_state(
        user_id=user_id,
        agent_id=agent_id,
        agent_source=agent_source,
        payload=payload,
    )
    await _preempt_previous_invoke_if_requested(
        state=state,
        payload=payload,
        user_id=user_id,
    )
    await _register_inflight_invoke(
        state=state,
        user_id=user_id,
        gateway=gateway,
        resolved=runtime.resolved,
    )
    on_event, on_finalized = _build_consume_stream_callbacks(
        state=state,
        user_id=user_id,
        agent_id=agent_id,
        agent_source=agent_source,
        query=payload.query,
        transport="ws",
        stream_enabled=True,
    )
    try:
        await a2a_invoke_service.stream_ws(
            websocket=websocket,
            gateway=gateway,
            resolved=runtime.resolved,
            query=payload.query,
            context_id=payload.context_id,
            metadata=payload.metadata,
            validate_message=validate_message,
            logger=logger,
            log_extra=log_extra,
            on_event=on_event,
            on_error_metadata=on_error_metadata,
            on_finalized=on_finalized,
            send_stream_end=send_stream_end,
            resume_from_sequence=payload.resume_from_sequence,
            cache_key=state.user_message_id,
        )
    except Exception:
        await _unregister_inflight_invoke(state=state, user_id=user_id)
        raise


async def run_ws_invoke_with_session_recovery(
    *,
    websocket: WebSocket,
    db: AsyncSession,
    gateway: Any,
    runtime: Any,
    user_id: UUID,
    agent_id: UUID,
    agent_source: AgentSource,
    payload: A2AAgentInvokeRequest,
    validate_message: Callable[[dict[str, Any]], list[Any]],
    logger: Any,
    log_extra: dict[str, Any],
    max_recovery_attempts: int = _SESSION_NOT_FOUND_RETRY_LIMIT,
) -> None:
    current_payload = payload
    remaining_retries = max_recovery_attempts
    while True:
        stream_error_code: str | None = None
        stream_error_message: str | None = None

        def _remember_stream_error(error_event: dict[str, Any]) -> None:
            nonlocal stream_error_code
            nonlocal stream_error_message
            raw_code = error_event.get("error_code")
            if isinstance(raw_code, str):
                stream_error_code = raw_code.strip() or None
            raw_message = error_event.get("message")
            if isinstance(raw_message, str):
                stream_error_message = raw_message

        def _send_recovery_failed_error() -> None:
            return a2a_invoke_service.send_ws_error(
                websocket=websocket,
                message=stream_error_message
                or _SESSION_NOT_FOUND_RECOVERY_EXHAUSTED_MESSAGE,
                error_code=ws_error_code_for_recovery_failed(stream_error_code or ""),
            )

        await run_ws_invoke(
            websocket=websocket,
            db=db,
            gateway=gateway,
            runtime=runtime,
            user_id=user_id,
            agent_id=agent_id,
            agent_source=agent_source,
            payload=current_payload,
            validate_message=validate_message,
            logger=logger,
            log_extra=log_extra,
            on_error_metadata=_remember_stream_error,
            send_stream_end=False,
        )
        if stream_error_code is None:
            await a2a_invoke_service.send_ws_stream_end(websocket)
            return

        if not is_recoverable_invoke_session_error(stream_error_code):
            await a2a_invoke_service.send_ws_stream_end(websocket)
            return
        if remaining_retries <= 0:
            await _send_recovery_failed_error()
            await a2a_invoke_service.send_ws_stream_end(websocket)
            return
        if not isinstance(current_payload.conversation_id, str):
            await a2a_invoke_service.send_ws_stream_end(websocket)
            return

        remaining_retries -= 1
        try:
            continue_binding = await _continue_session_with_short_transaction(
                user_id=user_id,
                conversation_id=current_payload.conversation_id,
            )
        except ValueError:
            await a2a_invoke_service.send_ws_stream_end(websocket)
            return
        current_payload = _build_rebound_invoke_payload(
            payload=current_payload,
            continue_payload=continue_binding,
        )


async def run_ws_invoke_route(
    *,
    websocket: WebSocket,
    db: AsyncSession,
    user_id: UUID,
    agent_id: UUID,
    agent_source: AgentSource,
    gateway: Any,
    runtime_builder: Callable[[], Awaitable[Any]],
    runtime_not_found_errors: tuple[type[Exception], ...],
    runtime_not_found_message: str | Callable[[Exception], str],
    runtime_not_found_code: str,
    runtime_validation_errors: tuple[type[Exception], ...],
    validate_message: Callable[[dict[str, Any]], list[Any]],
    logger: Any,
    invoke_log_message: str,
    invoke_log_extra_builder: Callable[[A2AAgentInvokeRequest, Any], dict[str, Any]],
    unexpected_log_message: str,
) -> None:
    selected_subprotocol = getattr(websocket.state, "selected_subprotocol", None)
    await websocket.accept(subprotocol=selected_subprotocol)

    try:
        data = await websocket.receive_json()
        try:
            payload = A2AAgentInvokeRequest.model_validate(data)
        except ValidationError:
            await a2a_invoke_service.send_ws_error(
                websocket,
                message="Invalid request payload",
                error_code="invalid_request",
            )
            await websocket.close(code=status.WS_1003_UNSUPPORTED_DATA)
            return

        if not payload.query.strip():
            await a2a_invoke_service.send_ws_error(
                websocket,
                message="Query must be a non-empty string",
                error_code="invalid_query",
            )
            await websocket.close(code=status.WS_1003_UNSUPPORTED_DATA)
            return

        try:
            runtime = await runtime_builder()
        except runtime_not_found_errors as exc:
            message = (
                runtime_not_found_message(exc)
                if callable(runtime_not_found_message)
                else runtime_not_found_message
            )
            await a2a_invoke_service.send_ws_error(
                websocket,
                message=message,
                error_code=runtime_not_found_code,
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        except runtime_validation_errors as exc:
            await a2a_invoke_service.send_ws_error(
                websocket,
                message=str(exc),
                error_code="runtime_invalid",
            )
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
            return
        await _close_open_transaction(db)

        logger.info(
            invoke_log_message,
            extra=invoke_log_extra_builder(payload, runtime),
        )
        guard_key = _build_invoke_guard_key(
            user_id=user_id,
            agent_id=agent_id,
            agent_source=agent_source,
            payload=payload,
        )

        try:
            async with _guard_inflight_invoke(guard_key):
                await run_ws_invoke_with_session_recovery(
                    websocket=websocket,
                    db=db,
                    gateway=gateway,
                    runtime=runtime,
                    user_id=user_id,
                    agent_id=agent_id,
                    agent_source=agent_source,
                    payload=payload,
                    validate_message=validate_message,
                    logger=logger,
                    log_extra={
                        "user_id": str(user_id),
                        "agent_id": str(agent_id),
                    },
                    max_recovery_attempts=_SESSION_NOT_FOUND_RETRY_LIMIT,
                )
        except ValueError as exc:
            await a2a_invoke_service.send_ws_error(
                websocket,
                message=str(exc),
                error_code=ws_error_code_for_invoke_session_error(str(exc)),
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected", extra={"user_id": str(user_id)})
    except Exception:
        logger.error(unexpected_log_message, exc_info=True)
        try:
            await a2a_invoke_service.send_ws_error(
                websocket,
                message="Upstream streaming failed",
                error_code="upstream_stream_error",
            )
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


async def run_http_invoke_route(
    *,
    db: AsyncSession,
    user_id: UUID,
    agent_id: UUID,
    agent_source: AgentSource,
    payload: A2AAgentInvokeRequest,
    stream: bool,
    gateway: Any,
    runtime_builder: Callable[[], Awaitable[Any]],
    runtime_not_found_errors: tuple[type[Exception], ...],
    runtime_not_found_status_code: int,
    runtime_validation_errors: tuple[type[Exception], ...],
    runtime_validation_status_code: int,
    validate_message: Callable[[dict[str, Any]], list[Any]],
    logger: Any,
    invoke_log_message: str,
    invoke_log_extra_builder: Callable[[A2AAgentInvokeRequest, Any], dict[str, Any]],
) -> A2AAgentInvokeResponse | StreamingResponse | JSONResponse:
    if not payload.query.strip():
        raise HTTPException(status_code=400, detail="Query must be a non-empty string")

    try:
        runtime = await runtime_builder()
    except runtime_not_found_errors as exc:
        raise HTTPException(
            status_code=runtime_not_found_status_code,
            detail=str(exc),
        ) from exc
    except runtime_validation_errors as exc:
        raise HTTPException(
            status_code=runtime_validation_status_code,
            detail=str(exc),
        ) from exc
    await _close_open_transaction(db)

    logger.info(
        invoke_log_message,
        extra=invoke_log_extra_builder(payload, runtime),
    )
    guard_key = _build_invoke_guard_key(
        user_id=user_id,
        agent_id=agent_id,
        agent_source=agent_source,
        payload=payload,
    )

    if stream and guard_key:
        acquired = await _try_acquire_invoke_guard(guard_key)
        if not acquired:
            raise HTTPException(
                status_code=status_code_for_invoke_session_error("invoke_inflight"),
                detail="invoke_inflight",
            )
        try:
            response = await run_http_invoke_with_session_recovery(
                db=db,
                gateway=gateway,
                runtime=runtime,
                user_id=user_id,
                agent_id=agent_id,
                agent_source=agent_source,
                payload=payload,
                stream=stream,
                validate_message=validate_message,
                logger=logger,
                log_extra={
                    "user_id": str(user_id),
                    "agent_id": str(agent_id),
                },
                max_recovery_attempts=_SESSION_NOT_FOUND_RETRY_LIMIT,
            )
        except ValueError as exc:
            await _release_invoke_guard(guard_key)
            raise HTTPException(
                status_code=status_code_for_invoke_session_error(str(exc)),
                detail=str(exc),
            ) from exc
        except Exception:
            await _release_invoke_guard(guard_key)
            raise

        if isinstance(response, StreamingResponse):
            original_iterator = response.body_iterator

            async def guarded_iterator():
                try:
                    async for chunk in original_iterator:
                        yield chunk
                finally:
                    await _release_invoke_guard(guard_key)

            response.body_iterator = guarded_iterator()
            return response

        if not response.success:
            await _release_invoke_guard(guard_key)
            return JSONResponse(
                status_code=status_code_for_invoke_error_code(response.error_code),
                content=response.model_dump(),
            )
        await _release_invoke_guard(guard_key)
        return response

    try:
        async with _guard_inflight_invoke(guard_key):
            response = await run_http_invoke_with_session_recovery(
                db=db,
                gateway=gateway,
                runtime=runtime,
                user_id=user_id,
                agent_id=agent_id,
                agent_source=agent_source,
                payload=payload,
                stream=stream,
                validate_message=validate_message,
                logger=logger,
                log_extra={
                    "user_id": str(user_id),
                    "agent_id": str(agent_id),
                },
                max_recovery_attempts=_SESSION_NOT_FOUND_RETRY_LIMIT,
            )
            if response.success:
                return response
            return JSONResponse(
                status_code=status_code_for_invoke_error_code(response.error_code),
                content=response.model_dump(),
            )
    except ValueError as exc:
        raise HTTPException(
            status_code=status_code_for_invoke_session_error(str(exc)),
            detail=str(exc),
        ) from exc


async def run_issue_ws_ticket_route(
    *,
    db: AsyncSession,
    user_id: UUID,
    scope_type: str,
    scope_id: UUID,
    ensure_access: Callable[[], Awaitable[Any]],
    not_found_errors: tuple[type[Exception], ...],
    not_found_status_code: int,
    not_found_detail: str | Callable[[Exception], str],
) -> WsTicketResponse:
    try:
        await ensure_access()
    except not_found_errors as exc:
        detail = (
            not_found_detail(exc) if callable(not_found_detail) else not_found_detail
        )
        raise HTTPException(status_code=not_found_status_code, detail=detail) from exc

    try:
        issued = await ws_ticket_service.issue_ticket(
            db,
            user_id=user_id,
            scope_type=scope_type,
            scope_id=scope_id,
        )
    except DBAPIError as exc:
        if is_postgres_lock_not_available_error(
            exc
        ) or is_postgres_statement_timeout_error(exc):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="WS ticket issuance is currently locked by another operation; retry shortly.",
            ) from exc
        raise
    return WsTicketResponse(
        token=issued.token,
        expires_at=issued.expires_at,
        expires_in=issued.expires_in,
    )


__all__ = [
    "run_background_invoke",
    "run_http_invoke",
    "run_http_invoke_with_session_recovery",
    "run_http_invoke_route",
    "run_issue_ws_ticket_route",
    "run_ws_invoke",
    "run_ws_invoke_route",
]
