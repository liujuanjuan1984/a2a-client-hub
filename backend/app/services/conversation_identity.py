"""Canonical conversation identity and external binding helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation_binding import ConversationBinding
from app.db.models.conversation_thread import ConversationThread
from app.utils.session_identity import normalize_non_empty_text, normalize_provider
from app.utils.timezone_util import utc_now


@dataclass(frozen=True)
class ExternalBindingResult:
    conversation_id: UUID
    mutated: bool


class ConversationIdentityService:
    """Service that owns canonical conversation identity and binding rules."""

    async def find_conversation_id_by_binding(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        provider: Optional[str] = None,
        external_session_id: Optional[str] = None,
        local_session_id: Optional[UUID] = None,
        context_id: Optional[str] = None,
    ) -> Optional[UUID]:
        """Find a canonical conversation ID using any active binding."""
        resolved_provider = normalize_provider(provider)
        resolved_external_id = normalize_non_empty_text(external_session_id)
        resolved_context_id = normalize_non_empty_text(context_id)

        conditions = []
        if local_session_id:
            conditions.append(ConversationBinding.local_session_id == local_session_id)
        if resolved_provider and resolved_external_id:
            conditions.append(
                and_(
                    ConversationBinding.provider == resolved_provider,
                    ConversationBinding.external_session_id == resolved_external_id,
                )
            )
        if resolved_provider and resolved_context_id:
            conditions.append(
                and_(
                    ConversationBinding.provider == resolved_provider,
                    ConversationBinding.context_id == resolved_context_id,
                )
            )

        if not conditions:
            return None

        stmt = (
            select(ConversationBinding.conversation_id)
            .where(
                and_(
                    ConversationBinding.user_id == user_id,
                    ConversationBinding.status == ConversationBinding.STATUS_ACTIVE,
                    or_(*conditions),
                )
            )
            .order_by(
                ConversationBinding.is_primary.desc(),
                ConversationBinding.confidence.desc(),
            )
            .limit(1)
        )
        return await db.scalar(stmt)

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
        binding_metadata: Optional[Dict[str, Any]] = None,
    ) -> ExternalBindingResult:
        """Upsert a binding between an external session and a canonical thread."""
        now = utc_now()
        resolved_provider = normalize_provider(provider)
        resolved_external_id = normalize_non_empty_text(external_session_id)
        resolved_context_id = normalize_non_empty_text(context_id)

        if not resolved_provider:
            raise ValueError("provider is required")
        if not resolved_external_id:
            raise ValueError("external_session_id is required")

        # 1. Try to find existing thread via binding
        existing_thread_id = await self.find_conversation_id_by_binding(
            db,
            user_id=user_id,
            provider=resolved_provider,
            external_session_id=resolved_external_id,
            local_session_id=conversation_id if conversation_id else None,
        )

        target_thread_id = existing_thread_id or conversation_id
        mutated = False

        if target_thread_id:
            # Check if thread exists and is active
            thread = await db.get(ConversationThread, target_thread_id)
            if thread and thread.status == ConversationThread.STATUS_ACTIVE:
                # Update thread fields for backward compatibility/quick access
                if thread.external_provider != resolved_provider:
                    thread.external_provider = resolved_provider
                    mutated = True
                if thread.external_session_id != resolved_external_id:
                    thread.external_session_id = resolved_external_id
                    mutated = True
                if resolved_context_id and thread.context_id != resolved_context_id:
                    thread.context_id = resolved_context_id
                    mutated = True

                normalized_title = ConversationThread.normalize_title(title)
                if ConversationThread.is_placeholder_title(
                    thread.title
                ) and not ConversationThread.is_placeholder_title(normalized_title):
                    thread.title = normalized_title
                    mutated = True

                if mutated:
                    thread.last_active_at = now
            else:
                target_thread_id = None  # Thread vanished or merged

        # 2. Create thread if still none
        if not target_thread_id:
            resolved_source = _normalize_conversation_source(source)
            thread = ConversationThread(
                user_id=user_id,
                source=resolved_source,
                agent_id=agent_id,
                agent_source=agent_source,
                title=title or "Session",
                external_provider=resolved_provider,
                external_session_id=resolved_external_id,
                context_id=resolved_context_id,
                last_active_at=now,
                status=ConversationThread.STATUS_ACTIVE,
            )
            db.add(thread)
            await db.flush()
            target_thread_id = thread.id
            mutated = True

        # 3. Upsert binding
        # We use a best-effort approach to upsert without full conflict handling here,
        # relying on the calling code's transaction or specific conflict logic if needed.
        # For external sessions, we want to ensure a primary binding exists.

        stmt = select(ConversationBinding).where(
            and_(
                ConversationBinding.user_id == user_id,
                ConversationBinding.provider == resolved_provider,
                ConversationBinding.agent_id == agent_id,
                ConversationBinding.agent_source == agent_source,
                ConversationBinding.external_session_id == resolved_external_id,
                ConversationBinding.status == ConversationBinding.STATUS_ACTIVE,
            )
        )
        binding = await db.scalar(stmt)

        if binding:
            if binding.conversation_id != target_thread_id:
                # Re-bind? Or keep old?
                # According to #92, we should merge or re-point.
                binding.conversation_id = target_thread_id
                mutated = True

            if resolved_context_id and binding.context_id != resolved_context_id:
                binding.context_id = resolved_context_id
                mutated = True

            binding.last_seen_at = now
            if binding_metadata:
                binding.binding_metadata = {
                    **(binding.binding_metadata or {}),
                    **binding_metadata,
                }
                mutated = True
        else:
            binding = ConversationBinding(
                user_id=user_id,
                conversation_id=target_thread_id,
                binding_kind=ConversationBinding.KIND_EXTERNAL,
                provider=resolved_provider,
                agent_id=agent_id,
                agent_source=agent_source,
                external_session_id=resolved_external_id,
                context_id=resolved_context_id,
                binding_metadata=binding_metadata or {},
                is_primary=True,
                first_seen_at=now,
                last_seen_at=now,
            )
            db.add(binding)
            mutated = True

        if mutated:
            await db.flush()

        return ExternalBindingResult(
            conversation_id=target_thread_id,
            mutated=mutated,
        )

    async def bind_local_session(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: UUID,
        local_session_id: UUID,
    ) -> bool:
        """Bind a local UUID session (e.g. from frontend) to a canonical thread."""
        now = utc_now()
        stmt = select(ConversationBinding).where(
            and_(
                ConversationBinding.user_id == user_id,
                ConversationBinding.local_session_id == local_session_id,
                ConversationBinding.status == ConversationBinding.STATUS_ACTIVE,
            )
        )
        binding = await db.scalar(stmt)
        if binding:
            if binding.conversation_id == conversation_id:
                return False
            binding.conversation_id = conversation_id
            binding.last_seen_at = now
            await db.flush()
            return True

        binding = ConversationBinding(
            user_id=user_id,
            conversation_id=conversation_id,
            binding_kind=ConversationBinding.KIND_LOCAL,
            local_session_id=local_session_id,
            is_primary=True,
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(binding)
        await db.flush()
        return True


conversation_identity_service = ConversationIdentityService()


def _normalize_conversation_source(
    source: Literal["manual", "scheduled"] | None,
) -> str:
    if source == ConversationThread.SOURCE_SCHEDULED:
        return ConversationThread.SOURCE_SCHEDULED
    return ConversationThread.SOURCE_MANUAL


__all__ = ["ConversationIdentityService", "conversation_identity_service"]
