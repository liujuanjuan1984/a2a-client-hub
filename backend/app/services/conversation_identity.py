"""Canonical conversation identity and binding helpers."""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation_binding import ConversationBinding
from app.db.models.conversation_thread import ConversationThread
from app.utils.timezone_util import utc_now


def _norm_text(value: Any) -> Optional[str]:
    if isinstance(value, str):
        trimmed = value.strip()
        if trimmed:
            return trimmed
    return None


def _norm_provider(value: Any) -> Optional[str]:
    normalized = _norm_text(value)
    if normalized is None:
        return None
    return normalized.lower()


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
        resolved_provider = _norm_provider(provider)
        resolved_external_id = _norm_text(external_session_id)
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
        resolved_provider = _norm_provider(provider)
        if not resolved_provider:
            return {}
        normalized_ids = sorted(
            {_norm_text(item) for item in external_session_ids if _norm_text(item)}
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
    ) -> UUID:
        now = utc_now()
        resolved_provider = _norm_provider(provider)
        resolved_external_id = _norm_text(external_session_id)
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
            existing.last_seen_at = now
            existing.agent_id = agent_id or existing.agent_id
            existing.agent_source = agent_source or existing.agent_source
            if context_id:
                existing.context_id = _norm_text(context_id)
            if isinstance(binding_metadata, dict) and binding_metadata:
                existing.binding_metadata = dict(binding_metadata)
            return existing.conversation_id

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
                        external_session_id=resolved_external_id,
                        context_id=_norm_text(context_id),
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
                return rebound
            raise

        return resolved_conversation_id


conversation_identity_service = ConversationIdentityService()


__all__ = ["ConversationIdentityService", "conversation_identity_service"]
