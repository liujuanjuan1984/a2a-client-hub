"""History write paths and block projection for the unified session domain."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_message import AgentMessage
from app.db.models.agent_message_block import AgentMessageBlock
from app.db.models.conversation_thread import ConversationThread
from app.features.sessions import block_store
from app.features.sessions import common as session_common
from app.features.sessions import message_store
from app.features.sessions.history_projection_blocks import (
    SessionHistoryBlockProjectionService,
)
from app.features.sessions.history_projection_events import SessionHistoryEventService
from app.features.sessions.history_projection_messages import (
    SessionHistoryMessageService,
)
from app.features.sessions.support import SessionHubSupport

_PATCH_TARGETS = (block_store, message_store)


class SessionHistoryProjectionService:
    """Session write paths, history persistence, and block cursor projection."""

    def __init__(self, *, support: SessionHubSupport) -> None:
        self._support = support
        self._messages = SessionHistoryMessageService(support=support)
        self._events = SessionHistoryEventService(support=support)
        self._blocks = SessionHistoryBlockProjectionService()

    async def ensure_local_session_for_invoke(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        agent_id: UUID,
        agent_source: session_common.SessionAgentSource,
        conversation_id: str | None,
    ) -> tuple[ConversationThread | None, session_common.SessionSource | None]:
        return await self._messages.ensure_local_session_for_invoke(
            db,
            user_id=user_id,
            agent_id=agent_id,
            agent_source=agent_source,
            conversation_id=conversation_id,
        )

    async def record_local_invoke_messages(
        self,
        db: AsyncSession,
        *,
        session: ConversationThread,
        source: session_common.SessionSource,
        user_id: UUID,
        agent_id: UUID,
        agent_source: session_common.SessionAgentSource,
        query: str,
        response_content: str,
        success: bool,
        context_id: str | None,
        invoke_metadata: dict[str, Any] | None = None,
        extra_metadata: dict[str, Any] | None = None,
        response_metadata: dict[str, Any] | None = None,
        response_blocks: list[dict[str, Any]] | None = None,
        idempotency_key: str | None = None,
        user_message_id: UUID | None = None,
        agent_message_id: UUID | None = None,
        user_sender: Literal["user", "automation"] = "user",
        agent_status: str | None = None,
        finish_reason: str | None = None,
        error_code: str | None = None,
    ) -> dict[str, UUID]:
        return await self._messages.record_local_invoke_messages(
            db,
            session=session,
            source=source,
            user_id=user_id,
            agent_id=agent_id,
            agent_source=agent_source,
            query=query,
            response_content=response_content,
            success=success,
            context_id=context_id,
            invoke_metadata=invoke_metadata,
            extra_metadata=extra_metadata,
            response_metadata=response_metadata,
            response_blocks=response_blocks,
            idempotency_key=idempotency_key,
            user_message_id=user_message_id,
            agent_message_id=agent_message_id,
            user_sender=user_sender,
            agent_status=agent_status,
            finish_reason=finish_reason,
            error_code=error_code,
        )

    async def record_local_invoke_messages_by_local_session_id(
        self,
        db: AsyncSession,
        *,
        local_session_id: UUID,
        source: session_common.SessionSource,
        user_id: UUID,
        agent_id: UUID,
        agent_source: session_common.SessionAgentSource,
        query: str,
        response_content: str,
        success: bool,
        context_id: str | None,
        invoke_metadata: dict[str, Any] | None = None,
        extra_metadata: dict[str, Any] | None = None,
        response_metadata: dict[str, Any] | None = None,
        response_blocks: list[dict[str, Any]] | None = None,
        idempotency_key: str | None = None,
        user_message_id: UUID | None = None,
        agent_message_id: UUID | None = None,
        user_sender: Literal["user", "automation"] = "user",
        agent_status: str | None = None,
        finish_reason: str | None = None,
        error_code: str | None = None,
    ) -> dict[str, UUID]:
        return await self._messages.record_local_invoke_messages_by_local_session_id(
            db,
            local_session_id=local_session_id,
            source=source,
            user_id=user_id,
            agent_id=agent_id,
            agent_source=agent_source,
            query=query,
            response_content=response_content,
            success=success,
            context_id=context_id,
            invoke_metadata=invoke_metadata,
            extra_metadata=extra_metadata,
            response_metadata=response_metadata,
            response_blocks=response_blocks,
            idempotency_key=idempotency_key,
            user_message_id=user_message_id,
            agent_message_id=agent_message_id,
            user_sender=user_sender,
            agent_status=agent_status,
            finish_reason=finish_reason,
            error_code=error_code,
        )

    async def record_user_message_by_local_session_id(
        self,
        db: AsyncSession,
        *,
        local_session_id: UUID,
        user_id: UUID,
        content: str,
        metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        user_message_id: UUID | None = None,
    ) -> dict[str, UUID]:
        return await self._messages.record_user_message_by_local_session_id(
            db,
            local_session_id=local_session_id,
            user_id=user_id,
            content=content,
            metadata=metadata,
            idempotency_key=idempotency_key,
            user_message_id=user_message_id,
        )

    async def ensure_local_invoke_message_headers_by_local_session_id(
        self,
        db: AsyncSession,
        *,
        local_session_id: UUID,
        source: session_common.SessionSource,
        user_id: UUID,
        agent_id: UUID,
        agent_source: session_common.SessionAgentSource,
        query: str,
        context_id: str | None,
        invoke_metadata: dict[str, Any] | None = None,
        extra_metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        user_message_id: UUID | None = None,
        agent_message_id: UUID | None = None,
        user_sender: Literal["user", "automation"] = "user",
    ) -> dict[str, UUID]:
        return await self._messages.ensure_local_invoke_message_headers_by_local_session_id(
            db,
            local_session_id=local_session_id,
            source=source,
            user_id=user_id,
            agent_id=agent_id,
            agent_source=agent_source,
            query=query,
            context_id=context_id,
            invoke_metadata=invoke_metadata,
            extra_metadata=extra_metadata,
            idempotency_key=idempotency_key,
            user_message_id=user_message_id,
            agent_message_id=agent_message_id,
            user_sender=user_sender,
        )

    async def record_interrupt_lifecycle_event_by_local_session_id(
        self,
        db: AsyncSession,
        *,
        local_session_id: UUID,
        user_id: UUID,
        event: dict[str, Any],
    ) -> UUID | None:
        return await self._events.record_interrupt_lifecycle_event_by_local_session_id(
            db,
            local_session_id=local_session_id,
            user_id=user_id,
            event=event,
        )

    async def record_interrupt_lifecycle_event(
        self,
        db: AsyncSession,
        *,
        conversation_id: UUID,
        user_id: UUID,
        event: dict[str, Any],
    ) -> UUID | None:
        return await self._events.record_interrupt_lifecycle_event(
            db,
            conversation_id=conversation_id,
            user_id=user_id,
            event=event,
        )

    async def record_preempt_event_by_local_session_id(
        self,
        db: AsyncSession,
        *,
        local_session_id: UUID,
        user_id: UUID,
        event: dict[str, Any],
    ) -> UUID | None:
        return await self._events.record_preempt_event_by_local_session_id(
            db,
            local_session_id=local_session_id,
            user_id=user_id,
            event=event,
        )

    async def record_preempt_event(
        self,
        db: AsyncSession,
        *,
        conversation_id: UUID,
        user_id: UUID,
        event: dict[str, Any],
    ) -> UUID | None:
        return await self._events.record_preempt_event(
            db,
            conversation_id=conversation_id,
            user_id=user_id,
            event=event,
        )

    async def append_agent_message_block_update(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        agent_message_id: UUID,
        seq: int,
        block_type: str,
        content: str,
        append: bool,
        is_finished: bool,
        block_id: str | None = None,
        lane_id: str | None = None,
        operation: str | None = None,
        base_seq: int | None = None,
        event_id: str | None = None,
        source: str | None = None,
        agent_message: AgentMessage | None = None,
    ) -> AgentMessageBlock | None:
        return await self._blocks.append_agent_message_block_update(
            db,
            user_id=user_id,
            agent_message_id=agent_message_id,
            seq=seq,
            block_type=block_type,
            content=content,
            append=append,
            is_finished=is_finished,
            block_id=block_id,
            lane_id=lane_id,
            operation=operation,
            base_seq=base_seq,
            event_id=event_id,
            source=source,
            agent_message=agent_message,
        )

    async def append_agent_message_block_updates(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        agent_message_id: UUID,
        updates: list[dict[str, Any]],
        agent_message: AgentMessage | None = None,
    ) -> list[AgentMessageBlock]:
        return await self._blocks.append_agent_message_block_updates(
            db,
            user_id=user_id,
            agent_message_id=agent_message_id,
            updates=updates,
            agent_message=agent_message,
        )

    async def has_agent_message_blocks(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        agent_message_id: UUID,
    ) -> bool:
        return await self._blocks.has_agent_message_blocks(
            db,
            user_id=user_id,
            agent_message_id=agent_message_id,
        )
