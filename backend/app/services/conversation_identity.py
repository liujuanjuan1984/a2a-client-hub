"""Canonical conversation identity and binding helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation_thread import ConversationThread
from app.utils.session_identity import normalize_non_empty_text, normalize_provider
from app.utils.timezone_util import utc_now


@dataclass(frozen=True)
class ExternalBindingResult:
    conversation_id: UUID
    mutated: bool


@dataclass(frozen=True)
class ExternalBindingLocator:
    conversation_id: UUID
    provider: str
    external_session_id: str
    context_id: Optional[str]
    agent_id: Optional[UUID]
    agent_source: Optional[str]
    local_session_id: Optional[UUID]


class ConversationIdentityService:
    """Service that owns canonical conversation identity and binding rules.

    External binding fields are persisted directly on ``conversation_threads``.
    """

    async def find_conversation_id_for_external(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        provider: str,
        external_session_id: str,
    ) -> Optional[UUID]:
        resolved_provider = normalize_provider(provider)
        resolved_external_id = normalize_non_empty_text(external_session_id)
        if not resolved_provider or not resolved_external_id:
            return None
        return await db.scalar(
            select(ConversationThread.id).where(
                and_(
                    ConversationThread.user_id == user_id,
                    ConversationThread.status == ConversationThread.STATUS_ACTIVE,
                    ConversationThread.external_provider == resolved_provider,
                    ConversationThread.external_session_id == resolved_external_id,
                )
            )
        )

    async def find_conversation_ids_for_external_batch(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        provider: str,
        external_session_ids: list[str],
    ) -> dict[str, UUID]:
        resolved_provider = normalize_provider(provider)
        if not resolved_provider:
            return {}
        normalized_ids = sorted(
            {
                normalized
                for item in external_session_ids
                if (normalized := normalize_non_empty_text(item))
            }
        )
        if not normalized_ids:
            return {}

        result = await db.execute(
            select(
                ConversationThread.external_session_id,
                ConversationThread.id,
            ).where(
                and_(
                    ConversationThread.user_id == user_id,
                    ConversationThread.status == ConversationThread.STATUS_ACTIVE,
                    ConversationThread.external_provider == resolved_provider,
                    ConversationThread.external_session_id.in_(normalized_ids),
                )
            )
        )
        mapped: dict[str, UUID] = {}
        for external_session_id, conversation_id in result.all():
            if (
                isinstance(external_session_id, str)
                and external_session_id not in mapped
            ):
                mapped[external_session_id] = conversation_id
        return mapped

    async def find_conversation_id_for_context(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        context_id: str,
        provider: Optional[str] = None,
    ) -> Optional[UUID]:
        mapped = await self.find_conversation_ids_for_context_batch(
            db,
            user_id=user_id,
            context_ids=[context_id],
            provider=provider,
        )
        resolved_context_id = normalize_non_empty_text(context_id)
        if not resolved_context_id:
            return None
        return mapped.get(resolved_context_id)

    async def find_conversation_ids_for_context_batch(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        context_ids: list[str],
        provider: Optional[str] = None,
    ) -> dict[str, UUID]:
        normalized_context_ids = sorted(
            {
                normalized
                for item in context_ids
                if (normalized := normalize_non_empty_text(item))
            }
        )
        if not normalized_context_ids:
            return {}
        resolved_provider = normalize_provider(provider) if provider else None

        filters = [
            ConversationThread.user_id == user_id,
            ConversationThread.status == ConversationThread.STATUS_ACTIVE,
            ConversationThread.context_id.in_(normalized_context_ids),
        ]
        if resolved_provider:
            filters.append(ConversationThread.external_provider == resolved_provider)

        result = await db.execute(
            select(
                ConversationThread.context_id,
                ConversationThread.id,
            )
            .where(and_(*filters))
            .order_by(
                ConversationThread.context_id.asc(),
                ConversationThread.last_active_at.desc(),
                ConversationThread.id.desc(),
            )
            .distinct(ConversationThread.context_id)
        )
        mapped: dict[str, UUID] = {}
        for context_id, conversation_id in result.all():
            if isinstance(context_id, str) and context_id not in mapped:
                mapped[context_id] = conversation_id
        return mapped

    async def find_conversation_id_for_local_session(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        local_session_id: UUID,
    ) -> Optional[UUID]:
        mapped = await self.find_conversation_ids_for_local_sessions_batch(
            db,
            user_id=user_id,
            local_session_ids=[local_session_id],
        )
        return mapped.get(local_session_id)

    async def find_conversation_ids_for_local_sessions_batch(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        local_session_ids: list[UUID],
    ) -> dict[UUID, UUID]:
        normalized_local_session_ids = sorted({item for item in local_session_ids})
        if not normalized_local_session_ids:
            return {}

        result = await db.execute(
            select(ConversationThread.id).where(
                and_(
                    ConversationThread.user_id == user_id,
                    ConversationThread.id.in_(normalized_local_session_ids),
                    ConversationThread.status == ConversationThread.STATUS_ACTIVE,
                )
            )
        )
        mapped: dict[UUID, UUID] = {}
        for (conversation_id,) in result.all():
            if isinstance(conversation_id, UUID):
                mapped[conversation_id] = conversation_id
        return mapped

    async def find_latest_external_binding_for_conversation(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: UUID,
    ) -> Optional[ExternalBindingLocator]:
        mapped = await self.find_latest_external_bindings_for_conversations_batch(
            db,
            user_id=user_id,
            conversation_ids=[conversation_id],
        )
        return mapped.get(conversation_id)

    async def find_latest_external_bindings_for_conversations_batch(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        conversation_ids: list[UUID],
    ) -> dict[UUID, ExternalBindingLocator]:
        normalized_conversation_ids = sorted({item for item in conversation_ids})
        if not normalized_conversation_ids:
            return {}

        result = await db.execute(
            select(
                ConversationThread.id,
                ConversationThread.external_provider,
                ConversationThread.external_session_id,
                ConversationThread.context_id,
                ConversationThread.agent_id,
                ConversationThread.agent_source,
            )
            .where(
                and_(
                    ConversationThread.user_id == user_id,
                    ConversationThread.status == ConversationThread.STATUS_ACTIVE,
                    ConversationThread.id.in_(normalized_conversation_ids),
                    ConversationThread.external_provider.is_not(None),
                    ConversationThread.external_session_id.is_not(None),
                )
            )
            .order_by(
                ConversationThread.id.asc(),
                ConversationThread.last_active_at.desc(),
            )
            .distinct(ConversationThread.id)
        )
        mapped: dict[UUID, ExternalBindingLocator] = {}
        for (
            conversation_id,
            provider,
            external_session_id,
            context_id,
            agent_id,
            agent_source,
        ) in result.all():
            if (
                not isinstance(conversation_id, UUID)
                or conversation_id in mapped
                or not isinstance(provider, str)
                or not isinstance(external_session_id, str)
            ):
                continue
            mapped[conversation_id] = ExternalBindingLocator(
                conversation_id=conversation_id,
                provider=provider,
                external_session_id=external_session_id,
                context_id=context_id if isinstance(context_id, str) else None,
                agent_id=agent_id if isinstance(agent_id, UUID) else None,
                agent_source=agent_source if isinstance(agent_source, str) else None,
                local_session_id=conversation_id,
            )
        return mapped

    async def find_latest_external_binding_for_local_session(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        local_session_id: UUID,
    ) -> Optional[ExternalBindingLocator]:
        mapped = await self.find_latest_external_bindings_for_local_sessions_batch(
            db,
            user_id=user_id,
            local_session_ids=[local_session_id],
        )
        return mapped.get(local_session_id)

    async def find_latest_external_bindings_for_local_sessions_batch(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        local_session_ids: list[UUID],
    ) -> dict[UUID, ExternalBindingLocator]:
        normalized_local_session_ids = sorted({item for item in local_session_ids})
        if not normalized_local_session_ids:
            return {}

        mapped = await self.find_latest_external_bindings_for_conversations_batch(
            db,
            user_id=user_id,
            conversation_ids=normalized_local_session_ids,
        )
        return {conversation_id: locator for conversation_id, locator in mapped.items()}

    async def bind_external_session(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: Optional[UUID],
        provider: str,
        external_session_id: str,
        agent_id: Optional[UUID],
        agent_source: Optional[str],
        context_id: Optional[str],
        title: str,
        binding_metadata: Optional[dict[str, Any]],
        local_session_id: Optional[UUID] = None,
    ) -> UUID:
        result = await self.bind_external_session_with_state(
            db,
            user_id=user_id,
            conversation_id=conversation_id,
            provider=provider,
            external_session_id=external_session_id,
            agent_id=agent_id,
            agent_source=agent_source,
            context_id=context_id,
            local_session_id=local_session_id,
            title=title,
            binding_metadata=binding_metadata,
        )
        return result.conversation_id

    async def bind_external_session_with_state(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: Optional[UUID],
        provider: str,
        external_session_id: str,
        agent_id: Optional[UUID],
        agent_source: Optional[str],
        context_id: Optional[str],
        title: str,
        binding_metadata: Optional[dict[str, Any]],
        local_session_id: Optional[UUID] = None,
    ) -> ExternalBindingResult:
        now = utc_now()
        resolved_provider = normalize_provider(provider)
        resolved_external_id = normalize_non_empty_text(external_session_id)
        if not resolved_provider:
            raise ValueError("provider is required")
        if not resolved_external_id:
            raise ValueError("external_session_id is required")

        existing_by_external = await db.scalar(
            select(ConversationThread).where(
                and_(
                    ConversationThread.user_id == user_id,
                    ConversationThread.status == ConversationThread.STATUS_ACTIVE,
                    ConversationThread.external_provider == resolved_provider,
                    ConversationThread.external_session_id == resolved_external_id,
                )
            )
        )
        if existing_by_external:
            mutated = False
            if agent_id and existing_by_external.agent_id != agent_id:
                existing_by_external.agent_id = agent_id
                mutated = True
            if agent_source and existing_by_external.agent_source != agent_source:
                existing_by_external.agent_source = agent_source
                mutated = True
            normalized_context_id = normalize_non_empty_text(context_id)
            if (
                normalized_context_id
                and existing_by_external.context_id != normalized_context_id
            ):
                existing_by_external.context_id = normalized_context_id
                mutated = True
            if existing_by_external.source != ConversationThread.SOURCE_OPENCODE:
                existing_by_external.source = ConversationThread.SOURCE_OPENCODE
                mutated = True
            if mutated:
                existing_by_external.last_active_at = now
            return ExternalBindingResult(
                conversation_id=existing_by_external.id,
                mutated=mutated,
            )

        resolved_conversation_id = conversation_id

        try:
            async with db.begin_nested():
                if resolved_conversation_id is None:
                    thread = ConversationThread(
                        user_id=user_id,
                        source=ConversationThread.SOURCE_OPENCODE,
                        agent_id=agent_id,
                        agent_source=agent_source,
                        title=title or "Session",
                        last_active_at=now,
                        status=ConversationThread.STATUS_ACTIVE,
                    )
                    db.add(thread)
                    await db.flush()
                    resolved_conversation_id = thread.id
                thread = await db.scalar(
                    select(ConversationThread).where(
                        and_(
                            ConversationThread.id == resolved_conversation_id,
                            ConversationThread.user_id == user_id,
                            ConversationThread.status
                            == ConversationThread.STATUS_ACTIVE,
                        )
                    )
                )
                if thread is None:
                    raise ValueError("session_not_found")
                thread.external_provider = resolved_provider
                thread.external_session_id = resolved_external_id
                thread.context_id = normalize_non_empty_text(context_id)
                thread.source = ConversationThread.SOURCE_OPENCODE
                if agent_id:
                    thread.agent_id = agent_id
                if agent_source:
                    thread.agent_source = agent_source
                thread.last_active_at = now
                await db.flush()
        except IntegrityError:
            rebound = await self.find_conversation_id_for_external(
                db,
                user_id=user_id,
                provider=resolved_provider,
                external_session_id=resolved_external_id,
            )
            if rebound:
                return ExternalBindingResult(conversation_id=rebound, mutated=False)
            raise

        return ExternalBindingResult(
            conversation_id=resolved_conversation_id,
            mutated=True,
        )


conversation_identity_service = ConversationIdentityService()


__all__ = ["ConversationIdentityService", "conversation_identity_service"]
