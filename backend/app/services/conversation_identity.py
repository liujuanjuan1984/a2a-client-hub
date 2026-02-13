"""Canonical conversation identity and binding helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation_binding import ConversationBinding
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
    """Service that owns canonical conversation identity and binding rules."""

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
            select(ConversationBinding.conversation_id).where(
                and_(
                    ConversationBinding.user_id == user_id,
                    ConversationBinding.status == ConversationBinding.STATUS_ACTIVE,
                    ConversationBinding.binding_kind
                    == ConversationBinding.KIND_EXTERNAL_SESSION,
                    ConversationBinding.provider == resolved_provider,
                    ConversationBinding.external_session_id == resolved_external_id,
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
                ConversationBinding.external_session_id,
                ConversationBinding.conversation_id,
            ).where(
                and_(
                    ConversationBinding.user_id == user_id,
                    ConversationBinding.status == ConversationBinding.STATUS_ACTIVE,
                    ConversationBinding.binding_kind
                    == ConversationBinding.KIND_EXTERNAL_SESSION,
                    ConversationBinding.provider == resolved_provider,
                    ConversationBinding.external_session_id.in_(normalized_ids),
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
            ConversationBinding.user_id == user_id,
            ConversationBinding.status == ConversationBinding.STATUS_ACTIVE,
            ConversationBinding.binding_kind
            == ConversationBinding.KIND_EXTERNAL_SESSION,
            ConversationBinding.context_id.in_(normalized_context_ids),
        ]
        if resolved_provider:
            filters.append(ConversationBinding.provider == resolved_provider)

        result = await db.execute(
            select(
                ConversationBinding.context_id,
                ConversationBinding.conversation_id,
            )
            .where(and_(*filters))
            .order_by(
                ConversationBinding.context_id.asc(),
                ConversationBinding.last_seen_at.desc(),
                ConversationBinding.id.desc(),
            )
            .distinct(ConversationBinding.context_id)
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
            select(
                ConversationBinding.local_session_id,
                ConversationBinding.conversation_id,
            )
            .where(
                and_(
                    ConversationBinding.user_id == user_id,
                    ConversationBinding.status == ConversationBinding.STATUS_ACTIVE,
                    ConversationBinding.binding_kind
                    == ConversationBinding.KIND_EXTERNAL_SESSION,
                    ConversationBinding.local_session_id.in_(
                        normalized_local_session_ids
                    ),
                )
            )
            .order_by(
                ConversationBinding.local_session_id.asc(),
                ConversationBinding.last_seen_at.desc(),
                ConversationBinding.id.desc(),
            )
            .distinct(ConversationBinding.local_session_id)
        )
        mapped: dict[UUID, UUID] = {}
        for local_session_id, conversation_id in result.all():
            if isinstance(local_session_id, UUID) and local_session_id not in mapped:
                mapped[local_session_id] = conversation_id
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

        result = await db.execute(
            select(
                ConversationBinding.local_session_id,
                ConversationBinding.conversation_id,
                ConversationBinding.provider,
                ConversationBinding.external_session_id,
                ConversationBinding.context_id,
                ConversationBinding.agent_id,
                ConversationBinding.agent_source,
            )
            .where(
                and_(
                    ConversationBinding.user_id == user_id,
                    ConversationBinding.status == ConversationBinding.STATUS_ACTIVE,
                    ConversationBinding.binding_kind
                    == ConversationBinding.KIND_EXTERNAL_SESSION,
                    ConversationBinding.local_session_id.in_(
                        normalized_local_session_ids
                    ),
                )
            )
            .order_by(
                ConversationBinding.local_session_id.asc(),
                ConversationBinding.last_seen_at.desc(),
                ConversationBinding.id.desc(),
            )
            .distinct(ConversationBinding.local_session_id)
        )
        mapped: dict[UUID, ExternalBindingLocator] = {}
        for (
            local_session_id,
            conversation_id,
            provider,
            external_session_id,
            context_id,
            agent_id,
            agent_source,
        ) in result.all():
            if (
                not isinstance(local_session_id, UUID)
                or local_session_id in mapped
                or not isinstance(conversation_id, UUID)
                or not isinstance(provider, str)
                or not isinstance(external_session_id, str)
            ):
                continue
            mapped[local_session_id] = ExternalBindingLocator(
                conversation_id=conversation_id,
                provider=provider,
                external_session_id=external_session_id,
                context_id=context_id if isinstance(context_id, str) else None,
                agent_id=agent_id if isinstance(agent_id, UUID) else None,
                agent_source=agent_source if isinstance(agent_source, str) else None,
                local_session_id=local_session_id,
            )
        return mapped

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

        existing = await db.scalar(
            select(ConversationBinding).where(
                and_(
                    ConversationBinding.user_id == user_id,
                    ConversationBinding.status == ConversationBinding.STATUS_ACTIVE,
                    ConversationBinding.binding_kind
                    == ConversationBinding.KIND_EXTERNAL_SESSION,
                    ConversationBinding.provider == resolved_provider,
                    ConversationBinding.external_session_id == resolved_external_id,
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
            normalized_context_id = normalize_non_empty_text(context_id)
            if normalized_context_id and existing.context_id != normalized_context_id:
                existing.context_id = normalized_context_id
                mutated = True
            if local_session_id and existing.local_session_id != local_session_id:
                existing.local_session_id = local_session_id
                mutated = True
            if isinstance(binding_metadata, dict) and binding_metadata:
                normalized_metadata = dict(binding_metadata)
                if existing.binding_metadata != normalized_metadata:
                    existing.binding_metadata = normalized_metadata
                    mutated = True
            if mutated:
                existing.last_seen_at = now
            return ExternalBindingResult(
                conversation_id=existing.conversation_id,
                mutated=mutated,
            )

        resolved_conversation_id = conversation_id

        try:
            async with db.begin_nested():
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
                db.add(
                    ConversationBinding(
                        user_id=user_id,
                        conversation_id=resolved_conversation_id,
                        binding_kind=ConversationBinding.KIND_EXTERNAL_SESSION,
                        provider=resolved_provider,
                        agent_id=agent_id,
                        agent_source=agent_source,
                        local_session_id=local_session_id,
                        external_session_id=resolved_external_id,
                        context_id=normalize_non_empty_text(context_id),
                        binding_metadata=dict(binding_metadata or {}),
                        status=ConversationBinding.STATUS_ACTIVE,
                        is_primary=True,
                        first_seen_at=now,
                        last_seen_at=now,
                    )
                )
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
