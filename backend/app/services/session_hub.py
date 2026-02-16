"""Unified conversation domain helpers and query service.

This module provides a single read model for session list/history/continue across:
- local manual chat sessions
- local scheduled sessions
- local OpenCode-bound sessions
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_message import AgentMessage
from app.db.models.conversation_thread import ConversationThread
from app.handlers import agent_message as agent_message_handler
from app.services.conversation_identity import conversation_identity_service
from app.utils.payload_extract import (
    as_dict,
    extract_context_id,
    extract_provider_and_external_session_id,
    pick_first_non_empty_str,
)
from app.utils.session_identity import normalize_non_empty_text, normalize_provider
from app.utils.timezone_util import utc_now

SessionSource = Literal["manual", "scheduled", "opencode"]
ResolvedSource = Literal["manual", "scheduled", "opencode"]


@dataclass(frozen=True)
class ResolvedConversationTarget:
    source: ResolvedSource
    local_session_id: Optional[UUID] = None
    conversation_id: UUID | None = None
    agent_id: Optional[UUID] = None
    agent_source: Optional[Literal["personal", "shared"]] = None
    external_session_id: Optional[str] = None


def _to_utc_epoch_seconds(value: Any) -> float:
    if isinstance(value, datetime):
        normalized = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return normalized.astimezone(timezone.utc).timestamp()
    if isinstance(value, str):
        try:
            normalized = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return float("-inf")
        if normalized.tzinfo is None:
            normalized = normalized.replace(tzinfo=timezone.utc)
        return normalized.astimezone(timezone.utc).timestamp()
    return float("-inf")


def _session_order_key(item: dict[str, Any]) -> tuple[float, float, str]:
    last_active = _to_utc_epoch_seconds(item.get("last_active_at"))
    created = _to_utc_epoch_seconds(item.get("created_at"))
    conversation_id = str(item.get("conversationId") or "")
    return (last_active, created, conversation_id)


class SessionHubService:
    _LOCAL_SESSION_SOURCES: set[ResolvedSource] = {
        "manual",
        "scheduled",
    }

    async def list_sessions(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        page: int,
        size: int,
        refresh: bool,
        source: Optional[SessionSource],
    ) -> tuple[list[dict[str, Any]], dict[str, Any], bool]:
        page_items = await self._list_local_sessions(db, user_id=user_id, source=source)
        page_items.sort(key=_session_order_key, reverse=True)
        total = len(page_items)
        pages = (total + size - 1) // size if size else 0
        offset = (page - 1) * size
        page_items = page_items[offset : offset + size]

        meta = {
            "opencode_total_agents": 0,
            "opencode_refreshed_agents": 0,
            "opencode_cached_agents": 0,
            "opencode_partial_failures": 0,
        }
        pagination = {
            "page": page,
            "size": size,
            "total": total,
            "pages": pages,
        }
        return page_items, {"pagination": pagination, "meta": meta}, False

    async def _list_local_sessions(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        source: Optional[SessionSource],
    ) -> list[dict[str, Any]]:
        stmt = (
            select(ConversationThread)
            .where(
                and_(
                    ConversationThread.user_id == user_id,
                    ConversationThread.status == ConversationThread.STATUS_ACTIVE,
                    ConversationThread.source.in_(
                        [
                            ConversationThread.SOURCE_MANUAL,
                            ConversationThread.SOURCE_SCHEDULED,
                            ConversationThread.SOURCE_OPENCODE,
                        ]
                    ),
                )
            )
            .order_by(
                ConversationThread.last_active_at.desc(),
                ConversationThread.created_at.desc(),
            )
        )
        threads = list((await db.execute(stmt)).scalars().all())

        session_ids = [thread.id for thread in threads]
        latest_metadata_map = await self._latest_local_message_metadata_map(
            db, user_id=user_id, local_conversation_ids=session_ids
        )
        binding_conversation_map = await conversation_identity_service.find_conversation_ids_for_local_sessions_batch(
            db,
            user_id=user_id,
            local_session_ids=session_ids,
        )
        binding_locator_map = await conversation_identity_service.find_latest_external_bindings_for_local_sessions_batch(
            db,
            user_id=user_id,
            local_session_ids=session_ids,
        )
        context_ids = [
            context_id
            for context_id in (
                extract_context_id(latest_metadata_map.get(session.id, {}))
                for session in threads
            )
            if isinstance(context_id, str) and context_id
        ]
        context_conversation_map = (
            await conversation_identity_service.find_conversation_ids_for_context_batch(
                db,
                user_id=user_id,
                context_ids=context_ids,
            )
        )
        items: list[dict[str, Any]] = []

        for thread in threads:
            latest_metadata = latest_metadata_map.get(thread.id, {})
            (
                metadata_provider,
                metadata_external_id,
            ) = extract_provider_and_external_session_id(latest_metadata)
            metadata_context_id = extract_context_id(latest_metadata)
            binding_locator = binding_locator_map.get(thread.id)
            if not metadata_provider and binding_locator:
                metadata_provider = binding_locator.provider
            if not metadata_external_id and binding_locator:
                metadata_external_id = binding_locator.external_session_id
            if not metadata_context_id and binding_locator:
                metadata_context_id = binding_locator.context_id
            conversation_id = binding_conversation_map.get(thread.id)
            if conversation_id is None and binding_locator:
                conversation_id = binding_locator.conversation_id
            if conversation_id is None and metadata_context_id:
                conversation_id = context_conversation_map.get(metadata_context_id)
            resolved_source = _resolve_session_source(
                thread_source=thread.source,
                provider=metadata_provider,
                external_session_id=metadata_external_id,
                context_id=metadata_context_id,
                fallback_source=None,
            )
            if source and source != resolved_source:
                continue
            title_fallback = (
                "Scheduled Session"
                if resolved_source == "scheduled"
                else "OpenCode Session"
                if resolved_source == "opencode"
                else "Manual Session"
            )
            items.append(
                {
                    "conversationId": str(conversation_id or thread.id),
                    "source": resolved_source,
                    "agent_id": thread.agent_id,
                    "agent_source": thread.agent_source or "personal",
                    "provider": metadata_provider,
                    "external_session_id": metadata_external_id,
                    "context_id": metadata_context_id,
                    "title": thread.title or title_fallback,
                    "last_active_at": thread.last_active_at,
                    "created_at": thread.created_at,
                }
            )

        return items

    async def _latest_local_message_metadata_map(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        local_conversation_ids: list[UUID],
    ) -> dict[UUID, Dict[str, Any]]:
        if not local_conversation_ids:
            return {}
        stmt = (
            select(AgentMessage.conversation_id, AgentMessage.message_metadata)
            .where(
                and_(
                    AgentMessage.user_id == user_id,
                    AgentMessage.conversation_id.in_(local_conversation_ids),
                )
            )
            .order_by(
                AgentMessage.conversation_id.asc(),
                AgentMessage.created_at.desc(),
                AgentMessage.id.desc(),
            )
            .distinct(AgentMessage.conversation_id)
        )
        rows = (await db.execute(stmt)).all()
        mapped: dict[UUID, Dict[str, Any]] = {}
        for row in rows:
            conversation_id = row.conversation_id
            if not isinstance(conversation_id, UUID):
                continue
            metadata = (
                dict(row.message_metadata)
                if isinstance(row.message_metadata, dict)
                else {}
            )
            mapped[conversation_id] = metadata
        return mapped

    async def list_messages(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: str,
        page: int,
        size: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any], bool]:
        resolved_conversation_id = _parse_conversation_id(conversation_id)
        target = await self._resolve_conversation_target(
            db,
            user_id=user_id,
            conversation_id=resolved_conversation_id,
        )
        session = await db.scalar(
            select(ConversationThread).where(
                and_(
                    ConversationThread.id == resolved_conversation_id,
                    ConversationThread.user_id == user_id,
                    ConversationThread.status == ConversationThread.STATUS_ACTIVE,
                )
            )
        )
        latest_metadata_map = await self._latest_local_message_metadata_map(
            db,
            user_id=user_id,
            local_conversation_ids=[resolved_conversation_id],
        )
        latest_metadata = latest_metadata_map.get(resolved_conversation_id, {})
        provider, external_session_id = extract_provider_and_external_session_id(
            latest_metadata
        )
        context_id = extract_context_id(latest_metadata)
        binding_locator = await conversation_identity_service.find_latest_external_binding_for_conversation(
            db,
            user_id=user_id,
            conversation_id=resolved_conversation_id,
        )
        if not provider and binding_locator:
            provider = binding_locator.provider
        if not external_session_id and binding_locator:
            external_session_id = binding_locator.external_session_id
        if not context_id and binding_locator:
            context_id = binding_locator.context_id

        normalized_provider = normalize_provider(provider)
        normalized_external_session_id = normalize_non_empty_text(external_session_id)

        resolved_source = _resolve_session_source(
            thread_source=session.source if session else None,
            provider=normalized_provider,
            external_session_id=normalized_external_session_id,
            context_id=context_id,
            fallback_source=target.source if target else None,
        )
        offset = (page - 1) * size
        messages = await agent_message_handler.list_agent_messages(
            db,
            user_id=user_id,
            limit=size,
            offset=offset,
            conversation_id=resolved_conversation_id,
        )
        total = await agent_message_handler.count_agent_messages(
            db,
            user_id=user_id,
            conversation_id=resolved_conversation_id,
        )
        pages = (total + size - 1) // size if size else 0
        items: list[dict[str, Any]] = []
        for message in messages:
            message_metadata = dict(getattr(message, "message_metadata", None) or {})
            message_metadata.setdefault("local_message_id", str(message.id))
            items.append(
                {
                    "id": _resolve_local_message_item_id(message, message_metadata),
                    "role": _sender_to_role(getattr(message, "sender", "")),
                    "content": message.content or "",
                    "created_at": message.created_at,
                    "metadata": message_metadata,
                }
            )
        meta = {
            "conversationId": str(resolved_conversation_id),
            "source": resolved_source,
            "agent_id": (
                str(session.agent_id)
                if session and isinstance(session.agent_id, UUID)
                else str(target.agent_id)
                if target and isinstance(target.agent_id, UUID)
                else None
            ),
            "agent_source": (
                session.agent_source
                if session and isinstance(session.agent_source, str)
                else target.agent_source
                if target and isinstance(target.agent_source, str)
                else None
            ),
            "upstream_session_id": normalized_external_session_id,
        }
        pagination = {
            "page": page,
            "size": size,
            "total": int(total),
            "pages": pages,
        }
        return items, {"pagination": pagination, "meta": meta}, False

    async def continue_session(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: str,
    ) -> tuple[dict[str, Any], bool]:
        resolved_conversation_id = _parse_conversation_id(conversation_id)
        target = await self._resolve_conversation_target(
            db,
            user_id=user_id,
            conversation_id=resolved_conversation_id,
        )
        session = await db.scalar(
            select(ConversationThread).where(
                and_(
                    ConversationThread.id == resolved_conversation_id,
                    ConversationThread.user_id == user_id,
                    ConversationThread.status == ConversationThread.STATUS_ACTIVE,
                )
            )
        )
        latest_metadata_map = await self._latest_local_message_metadata_map(
            db,
            user_id=user_id,
            local_conversation_ids=[resolved_conversation_id],
        )
        latest_metadata = latest_metadata_map.get(resolved_conversation_id, {})
        provider, external_session_id = extract_provider_and_external_session_id(
            latest_metadata
        )
        context_id = extract_context_id(latest_metadata)

        binding_locator = await conversation_identity_service.find_latest_external_binding_for_conversation(
            db,
            user_id=user_id,
            conversation_id=resolved_conversation_id,
        )
        if not provider and binding_locator:
            provider = binding_locator.provider
        if not external_session_id and binding_locator:
            external_session_id = binding_locator.external_session_id
        if not context_id and binding_locator:
            context_id = binding_locator.context_id

        if target is None:
            return (
                _build_continue_response(
                    conversation_id=resolved_conversation_id,
                    source="manual",
                    provider=normalize_provider(provider),
                    external_session_id=normalize_non_empty_text(external_session_id),
                    context_id=context_id if isinstance(context_id, str) else None,
                    metadata={},
                ),
                False,
            )

        resolved_provider = normalize_provider(provider)
        resolved_external_session_id = normalize_non_empty_text(external_session_id)
        if target.source == "opencode" and not resolved_provider:
            resolved_provider = "opencode"

        resolved_source = _resolve_session_source(
            thread_source=session.source if session else None,
            provider=resolved_provider,
            external_session_id=resolved_external_session_id,
            context_id=context_id,
            fallback_source=target.source,
        )
        conversation_id = resolved_conversation_id
        db_mutated = False
        if resolved_provider and resolved_external_session_id:
            resolved_agent_source: Literal["personal", "shared"] | None = None
            if target.agent_source in {"personal", "shared"}:
                resolved_agent_source = target.agent_source
            elif (
                session
                and isinstance(session.agent_source, str)
                and session.agent_source in {"personal", "shared"}
            ):
                resolved_agent_source = session.agent_source
            bind_result = (
                await conversation_identity_service.bind_external_session_with_state(
                    db,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    provider=resolved_provider,
                    external_session_id=resolved_external_session_id,
                    agent_id=(
                        target.agent_id
                        if isinstance(target.agent_id, UUID)
                        else session.agent_id
                        if session and isinstance(session.agent_id, UUID)
                        else None
                    ),
                    agent_source=resolved_agent_source,
                    context_id=context_id if isinstance(context_id, str) else None,
                    title=(session.title if session else "Session") or "Session",
                    binding_metadata={
                        "provider": resolved_provider,
                        "external_session_id": resolved_external_session_id,
                    },
                    local_session_id=(
                        target.local_session_id
                        if isinstance(target.local_session_id, UUID)
                        else session.id
                        if session
                        else None
                    ),
                )
            )
            conversation_id = bind_result.conversation_id
            db_mutated = bind_result.mutated
        continue_metadata = _build_continue_invoke_metadata(
            provider=resolved_provider,
            external_session_id=resolved_external_session_id,
        )
        return (
            _build_continue_response(
                conversation_id=conversation_id or resolved_conversation_id,
                source=resolved_source,
                provider=resolved_provider,
                external_session_id=resolved_external_session_id,
                context_id=context_id if isinstance(context_id, str) else None,
                metadata=continue_metadata,
            ),
            db_mutated,
        )

    async def ensure_local_session_for_invoke(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        agent_id: UUID,
        agent_source: Literal["personal", "shared"],
        conversation_id: Optional[str],
    ) -> tuple[Optional[ConversationThread], Optional[SessionSource]]:
        if not conversation_id:
            return None, None
        try:
            normalized_conversation_id = _parse_conversation_id(conversation_id)
        except ValueError as exc:
            raise ValueError("invalid_conversation_id") from exc

        target = await self._resolve_conversation_target(
            db,
            user_id=user_id,
            conversation_id=normalized_conversation_id,
        )

        local_session_id = (
            target.local_session_id
            if target and isinstance(target.local_session_id, UUID)
            else normalized_conversation_id
        )

        session = await db.scalar(
            select(ConversationThread).where(
                and_(
                    ConversationThread.id == local_session_id,
                    ConversationThread.user_id == user_id,
                    ConversationThread.status == ConversationThread.STATUS_ACTIVE,
                )
            )
        )

        if session is None:
            existing_session_id = await db.scalar(
                select(ConversationThread.id).where(
                    ConversationThread.id == local_session_id
                )
            )
            if existing_session_id is not None:
                raise ValueError("invalid_conversation_id")
            session = ConversationThread(
                id=local_session_id,
                user_id=user_id,
                source=(
                    ConversationThread.SOURCE_OPENCODE
                    if target and target.source == "opencode"
                    else ConversationThread.SOURCE_MANUAL
                ),
                agent_id=agent_id,
                agent_source=agent_source,
                title=(
                    f"OpenCode Session {str(local_session_id)[:8]}"
                    if target and target.source == "opencode"
                    else f"Manual Session {str(local_session_id)[:8]}"
                ),
                last_active_at=utc_now(),
                status=ConversationThread.STATUS_ACTIVE,
            )
            db.add(session)
            try:
                await db.flush()
            except IntegrityError as exc:
                await db.rollback()
                raise ValueError("invalid_conversation_id") from exc

        local_source: SessionSource
        if session.source == ConversationThread.SOURCE_MANUAL:
            local_source = "manual"
        elif session.source == ConversationThread.SOURCE_SCHEDULED:
            local_source = "scheduled"
        elif session.source == ConversationThread.SOURCE_OPENCODE:
            local_source = "opencode"
        else:
            raise ValueError("invalid_conversation_id")

        session.agent_id = agent_id
        session.agent_source = agent_source
        session.last_active_at = utc_now()
        if local_source == "manual":
            await self._ensure_local_conversation_thread(
                db,
                user_id=user_id,
                conversation_id=session.id,
                agent_id=agent_id,
                agent_source=agent_source,
                title=session.title or "Session",
                source="manual",
            )
            return session, "manual"
        return session, local_source

    async def record_local_invoke_messages(
        self,
        db: AsyncSession,
        *,
        session: ConversationThread,
        source: SessionSource,
        user_id: UUID,
        agent_id: UUID,
        agent_source: Literal["personal", "shared"],
        query: str,
        response_content: str,
        success: bool,
        context_id: Optional[str],
        user_message_id: Optional[str] = None,
        client_agent_message_id: Optional[str] = None,
        invoke_metadata: Optional[Dict[str, Any]] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
        response_metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        metadata: Dict[str, Any] = {
            "source": source,
            "agent_id": str(agent_id),
            "conversation_id": str(session.id),
            "success": success,
        }
        (
            provider_from_invoke,
            external_session_id,
        ) = extract_provider_and_external_session_id(invoke_metadata or {})
        if not provider_from_invoke and source == "opencode":
            provider_from_invoke = normalize_provider("opencode")
        if context_id and isinstance(context_id, str):
            metadata["context_id"] = context_id
        if provider_from_invoke:
            metadata["provider"] = provider_from_invoke
        if external_session_id:
            metadata["external_session_id"] = external_session_id
        if extra_metadata:
            metadata.update(extra_metadata)
        normalized_user_message_id = normalize_non_empty_text(user_message_id)
        normalized_client_agent_message_id = normalize_non_empty_text(
            client_agent_message_id
        )
        if normalized_user_message_id:
            metadata["client_message_id"] = normalized_user_message_id

        conversation_id: UUID = session.id
        if source == "manual":
            await self._ensure_local_conversation_thread(
                db,
                user_id=user_id,
                conversation_id=session.id,
                agent_id=agent_id,
                agent_source=agent_source,
                title=session.title or "Session",
                source="manual",
            )
        if provider_from_invoke and external_session_id:
            conversation_id = await conversation_identity_service.bind_external_session(
                db,
                user_id=user_id,
                conversation_id=conversation_id,
                provider=provider_from_invoke,
                external_session_id=external_session_id,
                agent_id=agent_id,
                agent_source=agent_source,
                context_id=context_id if isinstance(context_id, str) else None,
                title=session.title or "Session",
                binding_metadata=invoke_metadata,
                local_session_id=session.id,
            )
        elif context_id and isinstance(context_id, str):
            resolved_conversation_id = (
                await conversation_identity_service.find_conversation_id_for_context(
                    db,
                    user_id=user_id,
                    context_id=context_id,
                    provider=provider_from_invoke,
                )
            )
            if isinstance(resolved_conversation_id, UUID):
                conversation_id = resolved_conversation_id

        await agent_message_handler.create_agent_message(
            db,
            user_id=user_id,
            content=query,
            sender="user",
            conversation_id=conversation_id,
            metadata=metadata,
        )
        agent_metadata = dict(metadata)
        if normalized_client_agent_message_id:
            agent_metadata["client_message_id"] = normalized_client_agent_message_id
        if response_metadata:
            for key, value in response_metadata.items():
                if (
                    key in agent_metadata
                    and isinstance(agent_metadata[key], dict)
                    and isinstance(value, dict)
                ):
                    merged_nested = dict(agent_metadata[key])
                    merged_nested.update(value)
                    agent_metadata[key] = merged_nested
                    continue
                agent_metadata[key] = value
        await agent_message_handler.create_agent_message(
            db,
            user_id=user_id,
            content=response_content,
            sender="agent",
            conversation_id=conversation_id,
            metadata=agent_metadata,
        )
        session.last_active_at = utc_now()

    async def _get_local_session(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        local_session_id: UUID,
        source: Literal["manual", "scheduled"],
    ) -> ConversationThread:
        expected_source = (
            ConversationThread.SOURCE_MANUAL
            if source == "manual"
            else ConversationThread.SOURCE_SCHEDULED
        )
        session = await db.scalar(
            select(ConversationThread).where(
                and_(
                    ConversationThread.id == local_session_id,
                    ConversationThread.user_id == user_id,
                    ConversationThread.status == ConversationThread.STATUS_ACTIVE,
                    ConversationThread.source == expected_source,
                )
            )
        )
        if session is None:
            raise ValueError("session_not_found")
        return session

    async def _get_local_session_by_id(
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
                            ConversationThread.SOURCE_OPENCODE,
                        ]
                    ),
                )
            )
        )

    async def _resolve_conversation_target(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: UUID,
    ) -> ResolvedConversationTarget | None:
        binding_locator = await conversation_identity_service.find_latest_external_binding_for_conversation(
            db,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        if (
            binding_locator
            and normalize_provider(binding_locator.provider) == "opencode"
            and isinstance(binding_locator.agent_id, UUID)
            and binding_locator.agent_source in {"personal", "shared"}
            and isinstance(binding_locator.external_session_id, str)
            and binding_locator.external_session_id
        ):
            return ResolvedConversationTarget(
                source="opencode",
                conversation_id=conversation_id,
                local_session_id=(
                    binding_locator.local_session_id
                    if isinstance(binding_locator.local_session_id, UUID)
                    else None
                ),
                agent_id=binding_locator.agent_id,
                agent_source=binding_locator.agent_source,  # type: ignore[arg-type]
                external_session_id=binding_locator.external_session_id,
            )

        local_session_id = (
            binding_locator.local_session_id
            if binding_locator and isinstance(binding_locator.local_session_id, UUID)
            else conversation_id
        )
        local_session = await self._get_local_session_by_id(
            db,
            user_id=user_id,
            local_session_id=local_session_id,
        )
        if local_session is None:
            return None
        if local_session.source == ConversationThread.SOURCE_MANUAL:
            return ResolvedConversationTarget(
                source="manual",
                local_session_id=local_session.id,
                conversation_id=conversation_id,
            )
        if local_session.source == ConversationThread.SOURCE_SCHEDULED:
            return ResolvedConversationTarget(
                source="scheduled",
                local_session_id=local_session.id,
                conversation_id=conversation_id,
            )
        if local_session.source == ConversationThread.SOURCE_OPENCODE:
            return ResolvedConversationTarget(
                source="opencode",
                local_session_id=local_session.id,
                conversation_id=conversation_id,
                agent_id=local_session.agent_id,
                agent_source=(
                    local_session.agent_source
                    if local_session.agent_source in {"personal", "shared"}
                    else None
                ),
            )
        return None

    async def _ensure_local_conversation_thread(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: UUID,
        agent_id: Optional[UUID],
        agent_source: Optional[Literal["personal", "shared"]],
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


def _parse_conversation_id(value: str) -> UUID:
    trimmed = (value or "").strip()
    if not trimmed:
        raise ValueError("conversation_id is required")
    try:
        return UUID(trimmed)
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid_conversation_id") from exc


def _build_continue_response(
    *,
    conversation_id: UUID,
    source: ResolvedSource,
    provider: Optional[str],
    external_session_id: Optional[str],
    context_id: Optional[str],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return {
        "conversationId": str(conversation_id),
        "source": source,
        "provider": provider,
        "externalSessionId": external_session_id,
        "contextId": context_id,
        "metadata": metadata,
    }


def _build_continue_invoke_metadata(
    *,
    provider: str | None,
    external_session_id: str | None,
) -> dict[str, Any]:
    if normalize_provider(provider) == "opencode" and isinstance(
        external_session_id, str
    ):
        normalized = external_session_id.strip()
        if normalized:
            # Upstream opencode-a2a-serve contract requires this key explicitly.
            return {"opencode_session_id": normalized}
    return {}


def _resolve_session_source(
    *,
    thread_source: str | None,
    provider: str | None,
    external_session_id: str | None,
    context_id: str | None,
    fallback_source: ResolvedSource | None,
) -> ResolvedSource:
    if thread_source == ConversationThread.SOURCE_SCHEDULED:
        return "scheduled"
    normalized_provider = normalize_provider(provider)
    if normalized_provider == "opencode" and (
        normalize_non_empty_text(external_session_id)
        or normalize_non_empty_text(context_id)
    ):
        return "opencode"
    if thread_source == ConversationThread.SOURCE_OPENCODE:
        return "opencode"
    if fallback_source in {"manual", "scheduled", "opencode"}:
        return fallback_source
    return "manual"


def _sender_to_role(sender: str) -> str:
    normalized = (sender or "").strip().lower()
    if normalized in {"user", "automation"}:
        return "user"
    if normalized == "agent":
        return "agent"
    return "system"


def _resolve_local_message_item_id(
    message: AgentMessage, metadata: dict[str, Any]
) -> str:
    role = _sender_to_role(getattr(message, "sender", ""))
    if role == "agent":
        upstream_message_id = normalize_non_empty_text(
            metadata.get("upstream_message_id")
            or metadata.get("message_id")
            or metadata.get("messageId")
        )
        if upstream_message_id:
            return upstream_message_id
    if role in {"user", "agent"}:
        client_message_id = normalize_non_empty_text(
            metadata.get("client_message_id")
            or metadata.get("clientMessageId")
            or metadata.get("request_message_id")
            or metadata.get("requestMessageId")
        )
        if client_message_id:
            return client_message_id
    return str(message.id)


def _map_opencode_message(item: Any, index: int) -> Dict[str, Any]:
    obj = as_dict(item)
    parsed_content = _try_parse_json_object(
        pick_first_non_empty_str(obj, ["content", "message"]) or ""
    )
    raw_info = _extract_opencode_raw_info(obj, parsed_content)
    message_id = str(
        obj.get("id")
        or obj.get("message_id")
        or obj.get("messageId")
        or raw_info.get("id")
        or parsed_content.get("messageId")
        or f"opencode-{index}"
    )

    role = _map_role(
        pick_first_non_empty_str(obj, ["role", "type", "sender"])
        or pick_first_non_empty_str(raw_info, ["role"])
        or pick_first_non_empty_str(parsed_content, ["role"])
    )

    message_blocks = _extract_opencode_message_blocks(
        obj, parsed_content=parsed_content
    )
    content = _extract_content(
        obj,
        parsed_content=parsed_content,
        message_blocks=message_blocks,
    )
    created_at = _extract_timestamp(
        obj, raw_info=raw_info, parsed_content=parsed_content
    )

    metadata: dict[str, Any] = {}
    if message_blocks:
        metadata["message_blocks"] = message_blocks

    return {
        "id": message_id,
        "role": role,
        "content": content,
        "created_at": created_at,
        "metadata": metadata,
    }


def _map_role(raw: Optional[str]) -> str:
    normalized = (raw or "").strip().lower()
    if normalized in {"assistant", "agent"}:
        return "agent"
    if normalized in {"user", "human", "automation"}:
        return "user"
    return "system"


def _extract_content(
    obj: Dict[str, Any],
    *,
    parsed_content: dict[str, Any],
    message_blocks: list[dict[str, Any]],
) -> str:
    if message_blocks:
        return "".join(
            block.get("content", "")
            for block in message_blocks
            if block.get("type") == "text" and isinstance(block.get("content"), str)
        )

    direct = pick_first_non_empty_str(obj, ["text", "content", "message"])
    if direct:
        parsed_direct = _try_parse_json_object(direct)
        if parsed_direct:
            if _extract_opencode_message_parts(parsed_direct):
                return ""
            if parsed_direct.get("kind") == "message":
                return ""
        return direct

    if parsed_content and parsed_content.get("kind") == "message":
        return ""
    return ""


def _extract_timestamp(
    obj: Dict[str, Any],
    *,
    raw_info: dict[str, Any],
    parsed_content: dict[str, Any],
) -> datetime:
    direct = pick_first_non_empty_str(
        obj, ["created_at", "createdAt", "timestamp", "ts"]
    )
    if direct:
        try:
            return datetime.fromisoformat(direct.replace("Z", "+00:00")).astimezone(
                timezone.utc
            )
        except ValueError:
            pass

    ms = _pick_epoch_millis(obj, keys=("created", "updated", "completed"))
    if ms is None:
        ms = _pick_epoch_millis(
            as_dict(raw_info.get("time")), keys=("created", "updated", "completed")
        )
    if ms is None:
        parsed_raw_info = _extract_opencode_raw_info(parsed_content, {})
        ms = _pick_epoch_millis(
            as_dict(parsed_raw_info.get("time")),
            keys=("created", "updated", "completed"),
        )

    if isinstance(ms, int):
        try:
            return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            pass

    return utc_now()


def _pick_epoch_millis(payload: dict[str, Any], *, keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
    return None


def _try_parse_json_object(value: str) -> dict[str, Any]:
    stripped = (value or "").strip()
    if not stripped.startswith("{"):
        return {}
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _extract_opencode_raw_info(
    obj: dict[str, Any], parsed_content: dict[str, Any]
) -> dict[str, Any]:
    raw_info = as_dict(
        as_dict(as_dict(as_dict(obj.get("metadata")).get("opencode")).get("raw")).get(
            "info"
        )
    )
    if raw_info:
        return raw_info
    return as_dict(
        as_dict(
            as_dict(as_dict(parsed_content.get("metadata")).get("opencode")).get("raw")
        ).get("info")
    )


def _extract_opencode_message_parts(
    obj: dict[str, Any],
) -> list[dict[str, Any]]:
    parts = obj.get("parts")
    if isinstance(parts, list):
        return [part for part in parts if isinstance(part, dict)]
    raw_parts = as_dict(
        as_dict(as_dict(as_dict(obj.get("metadata")).get("opencode")).get("raw"))
    ).get("parts")
    if isinstance(raw_parts, list):
        return [part for part in raw_parts if isinstance(part, dict)]
    return []


def _extract_tool_call_block_content(part: dict[str, Any]) -> str:
    state = as_dict(part.get("state"))
    payload: dict[str, Any] = {}
    for source_key, target_key in (
        ("callID", "call_id"),
        ("call_id", "call_id"),
        ("tool", "tool"),
    ):
        value = part.get(source_key)
        if isinstance(value, str) and value.strip():
            payload[target_key] = value.strip()
    for key in ("status", "title"):
        value = state.get(key)
        if isinstance(value, str) and value.strip():
            payload[key] = value.strip()
    if not payload:
        return ""
    return json.dumps(payload, ensure_ascii=False)


def _extract_opencode_message_blocks(
    obj: dict[str, Any], *, parsed_content: dict[str, Any]
) -> list[dict[str, Any]]:
    parts = _extract_opencode_message_parts(obj)
    if not parts:
        parts = _extract_opencode_message_parts(parsed_content)
    blocks: list[dict[str, Any]] = []
    for index, part in enumerate(parts):
        raw_kind = str(part.get("kind") or part.get("type") or "").strip().lower()
        if not raw_kind:
            continue
        block_type: str | None = None
        content = ""
        if raw_kind in {"text"}:
            text = part.get("text")
            if isinstance(text, str):
                content = text
            block_type = "text"
        elif raw_kind in {"reasoning"}:
            text = part.get("text")
            if isinstance(text, str):
                content = text
            block_type = "reasoning"
        elif raw_kind in {"tool"}:
            content = _extract_tool_call_block_content(part)
            block_type = "tool_call"
        if not block_type or not content:
            continue
        blocks.append(
            {
                "id": f"history-block-{index + 1}",
                "type": block_type,
                "content": content,
                "is_finished": True,
            }
        )
    return blocks


session_hub_service = SessionHubService()

__all__ = [
    "ResolvedConversationTarget",
    "SessionHubService",
    "SessionSource",
    "session_hub_service",
]
