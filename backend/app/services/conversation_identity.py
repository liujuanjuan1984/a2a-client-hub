"""Canonical conversation identity and binding helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.conversation_binding import ConversationBinding
from app.db.models.conversation_thread import ConversationThread
from app.utils.timezone_util import utc_now


def _norm(value: Any) -> Optional[str]:
    if isinstance(value, str):
        trimmed = value.strip()
        if trimmed:
            return trimmed
    return None


class ConversationIdentityService:
    """Service that owns canonical conversation identity and binding rules."""

    async def resolve_or_create_for_local_session(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        local_session_id: UUID,
        agent_id: Optional[UUID],
        agent_source: Optional[str],
        title: str,
        last_active_at: Optional[datetime],
    ) -> ConversationThread:
        binding = await db.scalar(
            select(ConversationBinding)
            .options(selectinload(ConversationBinding.conversation))
            .where(
                and_(
                    ConversationBinding.user_id == user_id,
                    ConversationBinding.status == ConversationBinding.STATUS_ACTIVE,
                    ConversationBinding.local_session_id == local_session_id,
                )
            )
            .limit(1)
        )
        if binding and binding.conversation:
            now = utc_now()
            binding.last_seen_at = now
            thread = binding.conversation
            thread.agent_id = agent_id or thread.agent_id
            thread.agent_source = agent_source or thread.agent_source
            thread.title = title or thread.title
            thread.last_active_at = last_active_at or now
            return thread

        now = utc_now()
        thread = ConversationThread(
            user_id=user_id,
            agent_id=agent_id,
            agent_source=agent_source,
            title=title or "Session",
            last_active_at=last_active_at or now,
            status=ConversationThread.STATUS_ACTIVE,
        )
        db.add(thread)
        await db.flush()

        local_binding = ConversationBinding(
            user_id=user_id,
            conversation_id=thread.id,
            binding_kind=ConversationBinding.KIND_LOCAL_SESSION,
            local_session_id=local_session_id,
            agent_id=agent_id,
            agent_source=agent_source,
            is_primary=True,
            status=ConversationBinding.STATUS_ACTIVE,
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(local_binding)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            # Re-query in race conditions and return winner.
            rebound = await db.scalar(
                select(ConversationBinding)
                .options(selectinload(ConversationBinding.conversation))
                .where(
                    and_(
                        ConversationBinding.user_id == user_id,
                        ConversationBinding.status == ConversationBinding.STATUS_ACTIVE,
                        ConversationBinding.local_session_id == local_session_id,
                    )
                )
                .limit(1)
            )
            if rebound and rebound.conversation:
                return rebound.conversation
            raise
        return thread

    async def find_conversation_id_for_local_session(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        local_session_id: UUID,
    ) -> Optional[UUID]:
        return await db.scalar(
            select(ConversationBinding.conversation_id).where(
                and_(
                    ConversationBinding.user_id == user_id,
                    ConversationBinding.status == ConversationBinding.STATUS_ACTIVE,
                    ConversationBinding.local_session_id == local_session_id,
                )
            )
        )

    async def find_conversation_id_for_external(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        provider: str,
        agent_id: Optional[UUID],
        agent_source: Optional[str],
        external_session_id: str,
    ) -> Optional[UUID]:
        return await db.scalar(
            select(ConversationBinding.conversation_id).where(
                and_(
                    ConversationBinding.user_id == user_id,
                    ConversationBinding.status == ConversationBinding.STATUS_ACTIVE,
                    ConversationBinding.provider == provider,
                    ConversationBinding.agent_id == agent_id,
                    ConversationBinding.agent_source == agent_source,
                    ConversationBinding.external_session_id == external_session_id,
                )
            )
        )

    async def find_conversation_id_for_context(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        provider: Optional[str],
        agent_id: Optional[UUID],
        agent_source: Optional[str],
        context_id: str,
    ) -> Optional[UUID]:
        predicates = [
            ConversationBinding.user_id == user_id,
            ConversationBinding.status == ConversationBinding.STATUS_ACTIVE,
            ConversationBinding.context_id == context_id,
        ]
        if provider:
            predicates.append(ConversationBinding.provider == provider)
        if agent_id:
            predicates.append(ConversationBinding.agent_id == agent_id)
        if agent_source:
            predicates.append(ConversationBinding.agent_source == agent_source)
        return await db.scalar(
            select(ConversationBinding.conversation_id).where(and_(*predicates))
        )

    async def bind_external_session(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: Optional[UUID],
        provider: str,
        agent_id: Optional[UUID],
        agent_source: Optional[str],
        external_session_id: str,
        context_id: Optional[str],
        title: str,
        binding_metadata: Optional[dict[str, Any]],
    ) -> UUID:
        now = utc_now()
        resolved_provider = _norm(provider) or "external"
        resolved_external_id = _norm(external_session_id)
        if not resolved_external_id:
            raise ValueError("external_session_id is required")

        existing = await db.scalar(
            select(ConversationBinding).where(
                and_(
                    ConversationBinding.user_id == user_id,
                    ConversationBinding.status == ConversationBinding.STATUS_ACTIVE,
                    ConversationBinding.provider == resolved_provider,
                    ConversationBinding.agent_id == agent_id,
                    ConversationBinding.agent_source == agent_source,
                    ConversationBinding.external_session_id == resolved_external_id,
                )
            )
        )
        if existing:
            existing.last_seen_at = now
            if context_id:
                existing.context_id = context_id
            if isinstance(binding_metadata, dict) and binding_metadata:
                existing.binding_metadata = dict(binding_metadata)
            return existing.conversation_id

        resolved_conversation_id = conversation_id
        if resolved_conversation_id is None and context_id:
            resolved_conversation_id = await self.find_conversation_id_for_context(
                db,
                user_id=user_id,
                provider=resolved_provider,
                agent_id=agent_id,
                agent_source=agent_source,
                context_id=context_id,
            )
        if resolved_conversation_id is None:
            thread = ConversationThread(
                user_id=user_id,
                agent_id=agent_id,
                agent_source=agent_source,
                title=title or "Session",
                last_active_at=now,
                status=ConversationThread.STATUS_ACTIVE,
            )
            db.add(thread)
            await db.flush()
            resolved_conversation_id = thread.id

        binding = ConversationBinding(
            user_id=user_id,
            conversation_id=resolved_conversation_id,
            binding_kind=ConversationBinding.KIND_EXTERNAL_SESSION,
            provider=resolved_provider,
            agent_id=agent_id,
            agent_source=agent_source,
            external_session_id=resolved_external_id,
            context_id=_norm(context_id),
            binding_metadata=dict(binding_metadata or {}),
            status=ConversationBinding.STATUS_ACTIVE,
            is_primary=True,
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(binding)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            rebound = await self.find_conversation_id_for_external(
                db,
                user_id=user_id,
                provider=resolved_provider,
                agent_id=agent_id,
                agent_source=agent_source,
                external_session_id=resolved_external_id,
            )
            if rebound:
                return rebound
            raise

        if context_id:
            await self.bind_protocol_context(
                db,
                user_id=user_id,
                conversation_id=resolved_conversation_id,
                provider=resolved_provider,
                agent_id=agent_id,
                agent_source=agent_source,
                context_id=context_id,
                binding_metadata=binding_metadata,
            )

        return resolved_conversation_id

    async def bind_protocol_context(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: UUID,
        provider: Optional[str],
        agent_id: Optional[UUID],
        agent_source: Optional[str],
        context_id: str,
        binding_metadata: Optional[dict[str, Any]],
    ) -> None:
        resolved_context_id = _norm(context_id)
        if not resolved_context_id:
            return
        now = utc_now()
        existing = await db.scalar(
            select(ConversationBinding).where(
                and_(
                    ConversationBinding.user_id == user_id,
                    ConversationBinding.status == ConversationBinding.STATUS_ACTIVE,
                    ConversationBinding.binding_kind
                    == ConversationBinding.KIND_PROTOCOL_CONTEXT,
                    ConversationBinding.provider == _norm(provider),
                    ConversationBinding.agent_id == agent_id,
                    ConversationBinding.agent_source == agent_source,
                    ConversationBinding.context_id == resolved_context_id,
                )
            )
        )
        if existing:
            existing.last_seen_at = now
            existing.conversation_id = conversation_id
            if isinstance(binding_metadata, dict) and binding_metadata:
                existing.binding_metadata = dict(binding_metadata)
            return

        db.add(
            ConversationBinding(
                user_id=user_id,
                conversation_id=conversation_id,
                binding_kind=ConversationBinding.KIND_PROTOCOL_CONTEXT,
                provider=_norm(provider),
                agent_id=agent_id,
                agent_source=agent_source,
                context_id=resolved_context_id,
                binding_metadata=dict(binding_metadata or {}),
                status=ConversationBinding.STATUS_ACTIVE,
                is_primary=False,
                first_seen_at=now,
                last_seen_at=now,
            )
        )
        await db.flush()

    async def list_local_binding_rows(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        local_session_ids: list[UUID],
    ) -> list[ConversationBinding]:
        if not local_session_ids:
            return []
        result = await db.execute(
            select(ConversationBinding).where(
                and_(
                    ConversationBinding.user_id == user_id,
                    ConversationBinding.status == ConversationBinding.STATUS_ACTIVE,
                    ConversationBinding.local_session_id.in_(local_session_ids),
                )
            )
        )
        return list(result.scalars().all())


conversation_identity_service = ConversationIdentityService()


__all__ = ["ConversationIdentityService", "conversation_identity_service"]
