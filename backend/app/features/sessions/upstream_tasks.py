"""Durable upstream task ownership helpers for conversations."""

from __future__ import annotations

from typing import Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation_thread import ConversationThread
from app.db.models.conversation_upstream_task import ConversationUpstreamTask
from app.features.sessions.common import normalize_non_empty_text
from app.utils.timezone_util import utc_now

UpstreamTaskBindingSource = Literal[
    "stream_identity",
    "final_metadata",
    "metadata_backfill",
]


class ConversationUpstreamTaskService:
    """Maintains local proof that an upstream task belongs to a conversation."""

    async def record_binding(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: UUID,
        task_id: str,
        agent_id: UUID | None = None,
        agent_source: str | None = None,
        message_id: UUID | None = None,
        source: UpstreamTaskBindingSource = "stream_identity",
        status_hint: str | None = None,
    ) -> ConversationUpstreamTask | None:
        normalized_task_id = normalize_non_empty_text(task_id)
        if not normalized_task_id:
            return None

        thread = cast(
            ConversationThread | None,
            await db.scalar(
                select(ConversationThread).where(
                    and_(
                        ConversationThread.id == conversation_id,
                        ConversationThread.user_id == user_id,
                        ConversationThread.status == ConversationThread.STATUS_ACTIVE,
                    )
                )
            ),
        )
        if thread is None:
            return None

        resolved_agent_id = agent_id or cast(UUID | None, thread.agent_id)
        resolved_agent_source = agent_source or cast(str | None, thread.agent_source)
        normalized_status_hint = normalize_non_empty_text(status_hint)
        observed_at = utc_now()
        insert_stmt = insert(ConversationUpstreamTask).values(
            id=uuid4(),
            user_id=user_id,
            conversation_id=conversation_id,
            agent_id=resolved_agent_id,
            agent_source=resolved_agent_source,
            upstream_task_id=normalized_task_id,
            first_seen_message_id=message_id,
            latest_message_id=message_id,
            source=source,
            status_hint=normalized_status_hint,
            updated_at=observed_at,
        )
        excluded = insert_stmt.excluded
        upsert_stmt = insert_stmt.on_conflict_do_update(
            constraint="uq_conversation_upstream_tasks_user_conversation_task",
            set_={
                "agent_id": func.coalesce(
                    excluded.agent_id,
                    ConversationUpstreamTask.agent_id,
                ),
                "agent_source": func.coalesce(
                    excluded.agent_source,
                    ConversationUpstreamTask.agent_source,
                ),
                "first_seen_message_id": func.coalesce(
                    ConversationUpstreamTask.first_seen_message_id,
                    excluded.first_seen_message_id,
                ),
                "latest_message_id": func.coalesce(
                    excluded.latest_message_id,
                    ConversationUpstreamTask.latest_message_id,
                ),
                "source": excluded.source,
                "status_hint": func.coalesce(
                    excluded.status_hint,
                    ConversationUpstreamTask.status_hint,
                ),
                "updated_at": observed_at,
            },
        ).returning(ConversationUpstreamTask.id)
        binding_id = (await db.execute(upsert_stmt)).scalar_one_or_none()
        if binding_id is None:
            return None
        binding = cast(
            ConversationUpstreamTask | None,
            await db.scalar(
                select(ConversationUpstreamTask).where(
                    ConversationUpstreamTask.id == binding_id
                )
            ),
        )
        return binding

    async def verify_binding(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: UUID,
        task_id: str,
    ) -> bool:
        normalized_task_id = normalize_non_empty_text(task_id)
        if not normalized_task_id:
            return False
        binding_id = await db.scalar(
            select(ConversationUpstreamTask.id)
            .where(
                and_(
                    ConversationUpstreamTask.user_id == user_id,
                    ConversationUpstreamTask.conversation_id == conversation_id,
                    ConversationUpstreamTask.upstream_task_id == normalized_task_id,
                )
            )
            .limit(1)
        )
        return binding_id is not None


conversation_upstream_task_service = ConversationUpstreamTaskService()
