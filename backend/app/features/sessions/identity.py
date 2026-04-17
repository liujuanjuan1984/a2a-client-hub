"""Canonical conversation identity and external binding helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, cast
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
        return cast(
            UUID | None,
            await db.scalar(
                select(ConversationThread.id).where(
                    and_(
                        ConversationThread.user_id == user_id,
                        ConversationThread.status == ConversationThread.STATUS_ACTIVE,
                        ConversationThread.external_provider == resolved_provider,
                        ConversationThread.external_session_id == resolved_external_id,
                    )
                )
            ),
        )

    async def bind_external_session(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: Optional[UUID],
        source: Literal["manual", "scheduled"] | None,
        provider: str,
        external_session_id: str,
        agent_id: Optional[UUID],
        agent_source: Optional[str],
        context_id: Optional[str],
        title: str,
    ) -> UUID:
        result = await self.bind_external_session_with_state(
            db,
            user_id=user_id,
            conversation_id=conversation_id,
            source=source,
            provider=provider,
            external_session_id=external_session_id,
            agent_id=agent_id,
            agent_source=agent_source,
            context_id=context_id,
            title=title,
        )
        return result.conversation_id

    async def bind_external_session_with_state(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: Optional[UUID],
        source: Literal["manual", "scheduled"] | None,
        provider: str,
        external_session_id: str,
        agent_id: Optional[UUID],
        agent_source: Optional[str],
        context_id: Optional[str],
        title: str,
    ) -> ExternalBindingResult:
        now = utc_now()
        resolved_provider = normalize_provider(provider)
        resolved_external_id = normalize_non_empty_text(external_session_id)
        if not resolved_provider:
            raise ValueError("provider is required")
        if not resolved_external_id:
            raise ValueError("external_session_id is required")

        existing_by_external = cast(
            ConversationThread | None,
            await db.scalar(
                select(ConversationThread).where(
                    and_(
                        ConversationThread.user_id == user_id,
                        ConversationThread.status == ConversationThread.STATUS_ACTIVE,
                        ConversationThread.external_provider == resolved_provider,
                        ConversationThread.external_session_id == resolved_external_id,
                    )
                )
            ),
        )
        if existing_by_external:
            mutated = False
            existing_agent_id = cast(UUID | None, existing_by_external.agent_id)
            if agent_id and existing_agent_id != agent_id:
                setattr(existing_by_external, "agent_id", agent_id)
                mutated = True
            existing_agent_source = cast(str | None, existing_by_external.agent_source)
            if agent_source and existing_agent_source != agent_source:
                setattr(existing_by_external, "agent_source", agent_source)
                mutated = True
            normalized_context_id = normalize_non_empty_text(context_id)
            existing_context_id = cast(str | None, existing_by_external.context_id)
            if normalized_context_id and existing_context_id != normalized_context_id:
                setattr(existing_by_external, "context_id", normalized_context_id)
                mutated = True
            existing_title = cast(str, existing_by_external.title)
            if existing_title != title:
                normalized_title = ConversationThread.normalize_title(title)
                if ConversationThread.is_placeholder_title(
                    existing_title
                ) and not ConversationThread.is_placeholder_title(normalized_title):
                    setattr(existing_by_external, "title", normalized_title)
                    mutated = True
            if mutated:
                setattr(existing_by_external, "last_active_at", now)
            return ExternalBindingResult(
                conversation_id=cast(UUID, existing_by_external.id),
                mutated=mutated,
            )

        resolved_conversation_id = conversation_id

        try:
            async with db.begin_nested():
                if resolved_conversation_id is None:
                    resolved_source = _normalize_conversation_source(source)
                    thread = ConversationThread(
                        user_id=user_id,
                        source=resolved_source,
                        agent_id=agent_id,
                        agent_source=agent_source,
                        title=title or "Session",
                        last_active_at=now,
                        status=ConversationThread.STATUS_ACTIVE,
                    )
                    db.add(thread)
                    await db.flush()
                    resolved_conversation_id = cast(UUID, thread.id)
                persisted_thread = cast(
                    ConversationThread | None,
                    await db.scalar(
                        select(ConversationThread).where(
                            and_(
                                ConversationThread.id == resolved_conversation_id,
                                ConversationThread.user_id == user_id,
                                ConversationThread.status
                                == ConversationThread.STATUS_ACTIVE,
                            )
                        )
                    ),
                )
                if persisted_thread is None:
                    raise ValueError("session_not_found")
                setattr(persisted_thread, "external_provider", resolved_provider)
                setattr(persisted_thread, "external_session_id", resolved_external_id)
                setattr(
                    persisted_thread,
                    "context_id",
                    normalize_non_empty_text(context_id),
                )
                if agent_id:
                    setattr(persisted_thread, "agent_id", agent_id)
                if agent_source:
                    setattr(persisted_thread, "agent_source", agent_source)
                setattr(persisted_thread, "last_active_at", now)
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


def _normalize_conversation_source(
    source: Literal["manual", "scheduled"] | None,
) -> str:
    if source == ConversationThread.SOURCE_SCHEDULED:
        return ConversationThread.SOURCE_SCHEDULED
    return ConversationThread.SOURCE_MANUAL
