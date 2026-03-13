"""Shared persistence helpers for the unified session domain."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_message import AgentMessage
from app.db.models.conversation_thread import ConversationThread
from app.handlers import agent_message_block as agent_message_block_handler
from app.services.session_hub_common import (
    ResolvedConversationTarget,
    build_query_hash,
    create_block_with_conflict_recovery,
    normalize_non_empty_text,
)
from app.utils.timezone_util import utc_now


class SessionHubSupport:
    """Shared DB helpers used by session hub collaborators."""

    async def get_local_session_by_id(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        local_session_id: UUID,
    ) -> ConversationThread | None:
        return await db.scalar(
            select(ConversationThread).where(
                and_(
                    ConversationThread.id == local_session_id,
                    ConversationThread.user_id == user_id,
                    ConversationThread.status == ConversationThread.STATUS_ACTIVE,
                    ConversationThread.source.in_(
                        [
                            ConversationThread.SOURCE_MANUAL,
                            ConversationThread.SOURCE_SCHEDULED,
                        ]
                    ),
                )
            )
        )

    async def resolve_conversation_target(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: UUID,
    ) -> ResolvedConversationTarget | None:
        local_session = await self.get_local_session_by_id(
            db,
            user_id=user_id,
            local_session_id=conversation_id,
        )
        if local_session is None:
            return None
        if local_session.source == ConversationThread.SOURCE_MANUAL:
            return ResolvedConversationTarget(source="manual", thread=local_session)
        if local_session.source == ConversationThread.SOURCE_SCHEDULED:
            return ResolvedConversationTarget(source="scheduled", thread=local_session)
        return None

    async def ensure_local_conversation_thread(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: UUID,
        agent_id: UUID | None,
        agent_source: Literal["personal", "shared"] | None,
        title: str,
        source: Literal["manual", "scheduled"],
    ) -> bool:
        existing = await db.scalar(
            select(ConversationThread).where(
                and_(
                    ConversationThread.id == conversation_id,
                    ConversationThread.user_id == user_id,
                )
            )
        )
        if existing:
            mutated = False
            if agent_id and existing.agent_id != agent_id:
                existing.agent_id = agent_id
                mutated = True
            if agent_source and existing.agent_source != agent_source:
                existing.agent_source = agent_source
                mutated = True
            if title and existing.title != title:
                existing.title = title
                mutated = True
            expected_source = (
                ConversationThread.SOURCE_MANUAL
                if source == "manual"
                else ConversationThread.SOURCE_SCHEDULED
            )
            if existing.source != expected_source:
                existing.source = expected_source
                mutated = True
            existing.last_active_at = utc_now()
            return mutated

        db.add(
            ConversationThread(
                id=conversation_id,
                user_id=user_id,
                agent_id=agent_id,
                agent_source=agent_source,
                source=(
                    ConversationThread.SOURCE_MANUAL
                    if source == "manual"
                    else ConversationThread.SOURCE_SCHEDULED
                ),
                title=title or "Session",
                last_active_at=utc_now(),
                status=ConversationThread.STATUS_ACTIVE,
            )
        )
        await db.flush()
        return True

    async def find_message_by_idempotency_key(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: UUID,
        sender: str,
        idempotency_key: str,
    ) -> AgentMessage | None:
        stmt = (
            select(AgentMessage)
            .where(
                and_(
                    AgentMessage.user_id == user_id,
                    AgentMessage.conversation_id == conversation_id,
                    AgentMessage.sender == sender,
                    AgentMessage.invoke_idempotency_key == idempotency_key,
                )
            )
            .order_by(AgentMessage.created_at.desc(), AgentMessage.id.desc())
            .limit(1)
        )
        return await db.scalar(stmt)

    async def find_message_by_id_and_sender(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        message_id: UUID,
        sender: str,
        conversation_id: UUID,
    ) -> AgentMessage | None:
        message = await db.scalar(
            select(AgentMessage).where(
                and_(
                    AgentMessage.id == message_id,
                    AgentMessage.user_id == user_id,
                )
            )
        )
        if message is None:
            return None
        normalized_sender = (sender or "").strip().lower()
        message_sender = (message.sender or "").strip().lower()
        if normalized_sender == "user":
            is_user_sender = message_sender in {"user", "automation"}
            if not is_user_sender:
                raise ValueError("message_id_conflict")
        elif message_sender != normalized_sender:
            raise ValueError("message_id_conflict")
        if message.conversation_id != conversation_id:
            raise ValueError("message_id_conflict")
        return message

    async def ensure_idempotent_user_query(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        user_message: AgentMessage,
        query: str,
        idempotency_key: str | None,
    ) -> None:
        if not idempotency_key:
            return
        query_hash = build_query_hash(query)
        message_metadata = dict(getattr(user_message, "message_metadata", None) or {})
        existing_query_hash = normalize_non_empty_text(
            message_metadata.get("query_hash")
        )
        if existing_query_hash and existing_query_hash != query_hash:
            raise ValueError("idempotency_conflict")
        if not existing_query_hash:
            first_block = (
                await agent_message_block_handler.find_block_by_message_and_block_seq(
                    db,
                    user_id=user_id,
                    message_id=user_message.id,
                    block_seq=1,
                )
            )
            if first_block is not None:
                persisted_query = (
                    first_block.content if isinstance(first_block.content, str) else ""
                )
                if persisted_query != query:
                    raise ValueError("idempotency_conflict")
        if message_metadata.get("query_hash") != query_hash:
            message_metadata["query_hash"] = query_hash
            user_message.message_metadata = message_metadata
            await db.flush()

    async def upsert_single_text_block(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        message_id: UUID,
        content: str,
        source: str | None = None,
    ):
        existing = (
            await agent_message_block_handler.find_block_by_message_and_block_seq(
                db,
                user_id=user_id,
                message_id=message_id,
                block_seq=1,
            )
        )
        if existing is None:
            existing = await create_block_with_conflict_recovery(
                db,
                user_id=user_id,
                message_id=message_id,
                block_seq=1,
                block_type="text",
                content=str(content or ""),
                is_finished=True,
                source=normalize_non_empty_text(source),
                start_event_seq=None,
                end_event_seq=None,
                start_event_id=None,
                end_event_id=None,
            )
            if existing is None:
                return None
        existing.block_type = "text"
        existing.content = str(content or "")
        existing.is_finished = True
        normalized_source = normalize_non_empty_text(source)
        if normalized_source:
            existing.source = normalized_source
        await db.flush()
        return existing
