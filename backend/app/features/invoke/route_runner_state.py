"""Shared invoke route-runner state and inflight helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal, cast
from uuid import UUID

from sqlalchemy import and_, select

from app.db.models.agent_message import AgentMessage
from app.db.session import AsyncSessionLocal
from app.db.transaction import commit_safely
from app.features.invoke.session_binding import (
    normalize_invoke_binding_state,
)
from app.features.invoke.stream_persistence import coerce_uuid, is_interrupt_requested
from app.features.sessions.service import session_hub_service
from app.schemas.a2a_invoke import A2AAgentInvokeRequest
from app.utils.session_identity import normalize_non_empty_text

AgentSource = Literal["personal", "shared"]


@dataclass
class InvokeState:
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
    chunk_buffer: list[dict[str, Any]] = field(default_factory=list)
    current_block_type: str | None = None
    stream_hints_meta: dict[str, Any] = field(default_factory=dict)
    stream_hints_warned: set[str] = field(default_factory=set)


def normalize_optional_message_id(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    resolved = coerce_uuid(trimmed)
    if resolved is None:
        raise ValueError("invalid_message_id")
    return str(resolved)


async def prepare_state(
    *,
    user_id: UUID,
    agent_id: UUID,
    agent_source: AgentSource,
    payload: A2AAgentInvokeRequest,
) -> InvokeState:
    local_session_id: UUID | None = None
    local_source: Literal["manual", "scheduled"] | None = None
    persisted_context_id: str | None = None
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
        if local_session is not None:
            local_session_id = cast(UUID, local_session.id)
            persisted_context_id = normalize_non_empty_text(
                cast(str | None, local_session.context_id)
            )
        await commit_safely(prepare_db)

    resolved_context_id, resolved_invoke_metadata = normalize_invoke_binding_state(
        context_id=persisted_context_id,
        metadata=payload.metadata,
    )
    normalized_user_message_id = normalize_optional_message_id(payload.user_message_id)
    normalized_agent_message_id = normalize_optional_message_id(
        payload.agent_message_id
    )
    return InvokeState(
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
        stream_hints_meta={},
        stream_hints_warned=set(),
    )


async def register_inflight_invoke(
    *,
    state: InvokeState,
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


async def find_latest_agent_message_id(
    *,
    user_id: UUID,
    conversation_id: UUID,
) -> str | None:
    async with AsyncSessionLocal() as db:
        latest_message_id = await db.scalar(
            select(AgentMessage.id)
            .where(
                and_(
                    AgentMessage.user_id == user_id,
                    AgentMessage.conversation_id == conversation_id,
                    AgentMessage.sender == "agent",
                )
            )
            .order_by(AgentMessage.created_at.desc(), AgentMessage.id.desc())
            .limit(1)
        )
    return str(latest_message_id) if isinstance(latest_message_id, UUID) else None


async def record_preempt_history_event(
    *,
    state: InvokeState,
    user_id: UUID,
    event: dict[str, Any],
    session_factory: Callable[[], Any] = AsyncSessionLocal,
    commit_fn: Callable[[Any], Awaitable[None]] = commit_safely,
    session_hub: Any = session_hub_service,
) -> None:
    if state.local_session_id is None:
        return
    async with session_factory() as db:
        await session_hub.record_preempt_event_by_local_session_id(
            db,
            local_session_id=state.local_session_id,
            user_id=user_id,
            event=event,
        )
        await commit_fn(db)


async def preempt_previous_invoke_if_requested(
    *,
    state: InvokeState,
    payload: A2AAgentInvokeRequest,
    user_id: UUID,
    find_latest_agent_message_id_fn: Callable[..., Awaitable[str | None]] = (
        find_latest_agent_message_id
    ),
    is_interrupt_requested_fn: Callable[[A2AAgentInvokeRequest], bool] = (
        is_interrupt_requested
    ),
    record_preempt_history_event_fn: Callable[..., Awaitable[None]] = (
        record_preempt_history_event
    ),
) -> None:
    if state.local_session_id is None:
        return
    if not is_interrupt_requested_fn(payload):
        return
    target_message_id = await find_latest_agent_message_id_fn(
        user_id=user_id,
        conversation_id=state.local_session_id,
    )
    pending_event = {
        "reason": "invoke_interrupt",
        "source": "user",
        "target_message_id": target_message_id,
        "replacement_user_message_id": state.user_message_id,
        "replacement_agent_message_id": state.agent_message_id,
    }
    report = await session_hub_service.preempt_inflight_invoke_report(
        user_id=user_id,
        conversation_id=state.local_session_id,
        reason="invoke_interrupt",
        pending_event=pending_event,
    )
    if not report.attempted:
        return

    event = {
        **pending_event,
        "status": report.status,
        "target_task_ids": report.target_task_ids,
        "failed_error_codes": report.failed_error_codes,
    }
    await record_preempt_history_event_fn(
        state=state,
        user_id=user_id,
        event=event,
    )
    if report.status == "failed":
        raise ValueError("invoke_interrupt_failed")


async def bind_inflight_task_if_needed(
    *,
    state: InvokeState,
    user_id: UUID,
    record_preempt_history_event_fn: Callable[..., Awaitable[None]] = (
        record_preempt_history_event
    ),
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
    bind_report = await session_hub_service.bind_inflight_task_id_report(
        user_id=user_id,
        conversation_id=state.local_session_id,
        token=state.inflight_token,
        task_id=normalized_task_id,
    )
    if bind_report.bound:
        state.upstream_task_id = normalized_task_id
    if bind_report.preempt_event is not None:
        await record_preempt_history_event_fn(
            state=state,
            user_id=user_id,
            event=bind_report.preempt_event,
        )


async def unregister_inflight_invoke(
    *,
    state: InvokeState,
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
