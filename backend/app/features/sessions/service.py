"""Session feature facade for unified conversation workflows."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_message_block import AgentMessageBlock
from app.db.models.conversation_thread import ConversationThread
from app.features.sessions.history_projection import SessionHistoryProjectionService
from app.features.sessions.inflight_service import SessionInflightService
from app.features.sessions.query_service import SessionQueryService
from app.features.sessions.support import SessionHubSupport

if TYPE_CHECKING:
    from app.features.sessions.common import (
        BindInflightTaskReport,
        PreemptedInvokeReport,
        SessionAgentSource,
        SessionSource,
    )


class SessionHubService:
    """Stable facade for unified session queries, inflight state, and history writes."""

    def __init__(self) -> None:
        self._support = SessionHubSupport()
        self._query = SessionQueryService(support=self._support)
        self._inflight = SessionInflightService(support=self._support)
        self._history = SessionHistoryProjectionService(support=self._support)

    async def list_sessions(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        page: int,
        size: int,
        source: SessionSource | None,
        agent_id: UUID | None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any], bool]:
        return await self._query.list_sessions(
            db,
            user_id=user_id,
            page=page,
            size=size,
            source=source,
            agent_id=agent_id,
        )

    async def get_session(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: str,
    ) -> tuple[dict[str, Any], bool]:
        return await self._query.get_session(
            db,
            user_id=user_id,
            conversation_id=conversation_id,
        )

    async def list_messages(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: str,
        before: str | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any], bool]:
        return await self._query.list_messages(
            db,
            user_id=user_id,
            conversation_id=conversation_id,
            before=before,
            limit=limit,
        )

    async def list_message_blocks(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: str,
        block_ids: list[UUID],
    ) -> tuple[list[dict[str, Any]], bool]:
        return await self._query.list_message_blocks(
            db,
            user_id=user_id,
            conversation_id=conversation_id,
            block_ids=block_ids,
        )

    async def get_message_items(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: str,
        message_ids: list[UUID],
    ) -> tuple[list[dict[str, Any]], bool]:
        return await self._query.get_message_items(
            db,
            user_id=user_id,
            conversation_id=conversation_id,
            message_ids=message_ids,
        )

    async def continue_session(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: str,
    ) -> tuple[dict[str, Any], bool]:
        return await self._query.continue_session(
            db,
            user_id=user_id,
            conversation_id=conversation_id,
        )

    async def register_inflight_invoke(
        self,
        *,
        user_id: UUID,
        conversation_id: UUID,
        gateway: Any,
        resolved: Any,
    ) -> str:
        return await self._inflight.register_inflight_invoke(
            user_id=user_id,
            conversation_id=conversation_id,
            gateway=gateway,
            resolved=resolved,
        )

    async def bind_inflight_task_id(
        self,
        *,
        user_id: UUID,
        conversation_id: UUID,
        token: str,
        task_id: str,
    ) -> bool:
        return await self._inflight.bind_inflight_task_id(
            user_id=user_id,
            conversation_id=conversation_id,
            token=token,
            task_id=task_id,
        )

    async def bind_inflight_task_id_report(
        self,
        *,
        user_id: UUID,
        conversation_id: UUID,
        token: str,
        task_id: str,
    ) -> BindInflightTaskReport:
        return await self._inflight.bind_inflight_task_id_report(
            user_id=user_id,
            conversation_id=conversation_id,
            token=token,
            task_id=task_id,
        )

    async def unregister_inflight_invoke(
        self,
        *,
        user_id: UUID,
        conversation_id: UUID,
        token: str,
    ) -> bool:
        return await self._inflight.unregister_inflight_invoke(
            user_id=user_id,
            conversation_id=conversation_id,
            token=token,
        )

    async def preempt_inflight_invoke(
        self,
        *,
        user_id: UUID,
        conversation_id: UUID,
        reason: str,
    ) -> bool:
        return await self._inflight.preempt_inflight_invoke(
            user_id=user_id,
            conversation_id=conversation_id,
            reason=reason,
        )

    async def preempt_inflight_invoke_report(
        self,
        *,
        user_id: UUID,
        conversation_id: UUID,
        reason: str,
        pending_event: dict[str, Any] | None = None,
    ) -> PreemptedInvokeReport:
        return await self._inflight.preempt_inflight_invoke_report(
            user_id=user_id,
            conversation_id=conversation_id,
            reason=reason,
            pending_event=pending_event,
        )

    async def cancel_session(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: str,
    ) -> tuple[dict[str, Any], bool]:
        return await self._inflight.cancel_session(
            db,
            user_id=user_id,
            conversation_id=conversation_id,
        )

    async def ensure_local_session_for_invoke(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        agent_id: UUID,
        agent_source: SessionAgentSource,
        conversation_id: str | None,
    ) -> tuple[ConversationThread | None, SessionSource | None]:
        return await self._history.ensure_local_session_for_invoke(
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
        source: SessionSource,
        user_id: UUID,
        agent_id: UUID,
        agent_source: SessionAgentSource,
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
        return await self._history.record_local_invoke_messages(
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
        source: SessionSource,
        user_id: UUID,
        agent_id: UUID,
        agent_source: SessionAgentSource,
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
        return await self._history.record_local_invoke_messages_by_local_session_id(
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

    async def ensure_local_invoke_message_headers_by_local_session_id(
        self,
        db: AsyncSession,
        *,
        local_session_id: UUID,
        source: SessionSource,
        user_id: UUID,
        agent_id: UUID,
        agent_source: SessionAgentSource,
        query: str,
        context_id: str | None,
        invoke_metadata: dict[str, Any] | None = None,
        extra_metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        user_message_id: UUID | None = None,
        agent_message_id: UUID | None = None,
        user_sender: Literal["user", "automation"] = "user",
    ) -> dict[str, UUID]:
        return (
            await self._history.ensure_local_invoke_message_headers_by_local_session_id(
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
        return await self._history.record_user_message_by_local_session_id(
            db,
            local_session_id=local_session_id,
            user_id=user_id,
            content=content,
            metadata=metadata,
            idempotency_key=idempotency_key,
            user_message_id=user_message_id,
        )

    async def record_actor_message_by_local_session_id(
        self,
        db: AsyncSession,
        *,
        local_session_id: UUID,
        user_id: UUID,
        sender: Literal["user", "automation"],
        content: str,
        metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        user_message_id: UUID | None = None,
    ) -> dict[str, UUID]:
        return await self._history.record_actor_message_by_local_session_id(
            db,
            local_session_id=local_session_id,
            user_id=user_id,
            sender=sender,
            content=content,
            metadata=metadata,
            idempotency_key=idempotency_key,
            user_message_id=user_message_id,
        )

    async def record_interrupt_lifecycle_event_by_local_session_id(
        self,
        db: AsyncSession,
        *,
        local_session_id: UUID,
        user_id: UUID,
        event: dict[str, Any],
    ) -> UUID | None:
        return await self._history.record_interrupt_lifecycle_event_by_local_session_id(
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
        return await self._history.record_interrupt_lifecycle_event(
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
        return await self._history.record_preempt_event_by_local_session_id(
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
        return await self._history.record_preempt_event(
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
        agent_message: Any | None = None,
    ) -> AgentMessageBlock | None:
        return await self._history.append_agent_message_block_update(
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
        agent_message: Any | None = None,
    ) -> list[AgentMessageBlock]:
        return await self._history.append_agent_message_block_updates(
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
        return await self._history.has_agent_message_blocks(
            db,
            user_id=user_id,
            agent_message_id=agent_message_id,
        )


session_hub_service = SessionHubService()

__all__ = [
    "SessionHubService",
    "session_hub_service",
]
