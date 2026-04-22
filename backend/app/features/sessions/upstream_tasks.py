"""Durable upstream task ownership helpers for conversations."""

from __future__ import annotations

from typing import Literal, cast
from uuid import UUID

from sqlalchemy import and_, select
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

        binding = cast(
            ConversationUpstreamTask | None,
            await db.scalar(
                select(ConversationUpstreamTask).where(
                    and_(
                        ConversationUpstreamTask.user_id == user_id,
                        ConversationUpstreamTask.conversation_id == conversation_id,
                        ConversationUpstreamTask.upstream_task_id == normalized_task_id,
                    )
                )
            ),
        )
        if binding is None:
            binding = ConversationUpstreamTask(
                user_id=user_id,
                conversation_id=conversation_id,
                agent_id=agent_id or cast(UUID | None, thread.agent_id),
                agent_source=agent_source or cast(str | None, thread.agent_source),
                upstream_task_id=normalized_task_id,
                first_seen_message_id=message_id,
                latest_message_id=message_id,
                source=source,
                status_hint=normalize_non_empty_text(status_hint),
            )
            db.add(binding)
            await db.flush()
            return binding

        mutated = False
        if agent_id is not None and cast(UUID | None, binding.agent_id) != agent_id:
            setattr(binding, "agent_id", agent_id)
            mutated = True
        normalized_agent_source = normalize_non_empty_text(agent_source)
        if (
            normalized_agent_source is not None
            and cast(str | None, binding.agent_source) != normalized_agent_source
        ):
            setattr(binding, "agent_source", normalized_agent_source)
            mutated = True
        if (
            message_id is not None
            and cast(UUID | None, binding.first_seen_message_id) is None
        ):
            setattr(binding, "first_seen_message_id", message_id)
            mutated = True
        if (
            message_id is not None
            and cast(UUID | None, binding.latest_message_id) != message_id
        ):
            setattr(binding, "latest_message_id", message_id)
            mutated = True
        normalized_status_hint = normalize_non_empty_text(status_hint)
        if (
            normalized_status_hint is not None
            and cast(str | None, binding.status_hint) != normalized_status_hint
        ):
            setattr(binding, "status_hint", normalized_status_hint)
            mutated = True
        if cast(str | None, binding.source) != source:
            setattr(binding, "source", source)
            mutated = True
        if mutated:
            setattr(binding, "updated_at", utc_now())
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
