"""Unified conversation domain helpers and query service.

This module provides a single read model for session list/history/continue across:
- local manual chat sessions
- local scheduled sessions
- local OpenCode-bound sessions
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_message import AgentMessage
from app.db.models.agent_message_chunk import AgentMessageChunk
from app.db.models.conversation_thread import ConversationThread
from app.handlers import agent_message as agent_message_handler
from app.handlers import agent_message_chunk as agent_message_chunk_handler
from app.services.conversation_identity import conversation_identity_service
from app.utils.idempotency_key import normalize_idempotency_key
from app.utils.payload_extract import extract_provider_and_external_session_id
from app.utils.session_identity import normalize_non_empty_text, normalize_provider
from app.utils.timezone_util import utc_now

SessionSource = Literal["manual", "scheduled"]
ResolvedSource = Literal["manual", "scheduled"]


@dataclass(frozen=True)
class ResolvedConversationTarget:
    source: ResolvedSource
    thread: ConversationThread


class SessionHubService:
    async def list_sessions(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        page: int,
        size: int,
        source: Optional[SessionSource],
    ) -> tuple[list[dict[str, Any]], dict[str, Any], bool]:
        page_items = await self._list_local_sessions(db, user_id=user_id, source=source)
        total = len(page_items)
        pages = (total + size - 1) // size if size else 0
        offset = (page - 1) * size
        page_items = page_items[offset : offset + size]

        pagination = {
            "page": page,
            "size": size,
            "total": total,
            "pages": pages,
        }
        return page_items, {"pagination": pagination}, False

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
        items: list[dict[str, Any]] = []

        for thread in threads:
            resolved_source = _resolve_session_source(
                thread_source=thread.source,
                fallback_source=None,
            )
            if source and source != resolved_source:
                continue
            title_fallback = (
                "Scheduled Session"
                if resolved_source == "scheduled"
                else "Manual Session"
            )
            thread_title = thread.title if thread.title else title_fallback
            if ConversationThread.is_placeholder_title(thread_title):
                thread_title = (
                    "Session" if resolved_source == "manual" else title_fallback
                )
            items.append(
                {
                    "conversationId": str(thread.id),
                    "source": resolved_source,
                    "external_provider": normalize_provider(thread.external_provider),
                    "external_session_id": normalize_non_empty_text(
                        thread.external_session_id
                    ),
                    "agent_id": thread.agent_id,
                    "agent_source": thread.agent_source or "personal",
                    "title": thread_title,
                    "last_active_at": thread.last_active_at,
                    "created_at": thread.created_at,
                }
            )

        return items

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
        session = target.thread if target else None
        external_session_id = normalize_non_empty_text(
            session.external_session_id if session else None
        )

        resolved_source = _resolve_session_source(
            thread_source=session.source if session else None,
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
        agent_message_ids = [
            message.id
            for message in messages
            if isinstance(message.id, UUID)
            and _sender_to_role(message.sender) == "agent"
        ]
        chunks_by_message_id: dict[UUID, list[AgentMessageChunk]] = {}
        if agent_message_ids:
            chunks = await agent_message_chunk_handler.list_chunks_by_message_ids(
                db,
                user_id=user_id,
                message_ids=agent_message_ids,
            )
            for chunk in chunks:
                if not isinstance(chunk.message_id, UUID):
                    continue
                chunks_by_message_id.setdefault(chunk.message_id, []).append(chunk)
        total = await agent_message_handler.count_agent_messages(
            db,
            user_id=user_id,
            conversation_id=resolved_conversation_id,
        )
        pages = (total + size - 1) // size if size else 0
        items: list[dict[str, Any]] = []
        for message in messages:
            message_metadata = dict(getattr(message, "message_metadata", None) or {})
            message_metadata.pop("message_blocks", None)
            resolved_content = message.content or ""
            if (
                isinstance(message.id, UUID)
                and _sender_to_role(getattr(message, "sender", "")) == "agent"
            ):
                chunk_entries = chunks_by_message_id.get(message.id, [])
                if chunk_entries:
                    projected_content, _ = _project_message_from_chunks(chunk_entries)
                    if projected_content:
                        resolved_content = projected_content
                    message_metadata["chunk_count"] = len(chunk_entries)
                if isinstance(message.status, str) and message.status.strip():
                    message_metadata.setdefault("stream_status", message.status.strip())
                stream_meta = message_metadata.get("stream")
                if not isinstance(stream_meta, dict):
                    stream_meta = {}
                if message.finish_reason:
                    stream_meta.setdefault("finish_reason", message.finish_reason)
                if message.error_code:
                    existing_error = stream_meta.get("error")
                    if not isinstance(existing_error, dict):
                        existing_error = {}
                    existing_error.setdefault("error_code", message.error_code)
                    stream_meta["error"] = existing_error
                if stream_meta:
                    message_metadata["stream"] = stream_meta
            items.append(
                {
                    "id": str(message.id),
                    "role": _sender_to_role(getattr(message, "sender", "")),
                    "content": resolved_content,
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
                else None
            ),
            "agent_source": (
                session.agent_source
                if session and isinstance(session.agent_source, str)
                else None
            ),
            "upstream_session_id": external_session_id,
        }
        pagination = {
            "page": page,
            "size": size,
            "total": int(total),
            "pages": pages,
        }
        return items, {"pagination": pagination, "meta": meta}, False

    async def list_message_blocks(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: str,
        message_id: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Any], bool]:
        resolved_conversation_id = _parse_conversation_id(conversation_id)
        resolved_message_id = _parse_message_id(message_id)
        message = await db.scalar(
            select(AgentMessage).where(
                and_(
                    AgentMessage.user_id == user_id,
                    AgentMessage.conversation_id == resolved_conversation_id,
                    AgentMessage.id == resolved_message_id,
                )
            )
        )
        if message is None:
            raise ValueError("message_not_found")

        role = _sender_to_role(getattr(message, "sender", ""))
        chunk_count = 0
        blocks: list[dict[str, Any]] = []
        if role == "agent":
            chunks = await agent_message_chunk_handler.list_chunks_by_message_ids(
                db,
                user_id=user_id,
                message_ids=[resolved_message_id],
            )
            chunk_count = len(chunks)
            if chunks:
                _, blocks = _project_message_from_chunks(chunks)

        meta = {
            "conversationId": str(resolved_conversation_id),
            "messageId": str(resolved_message_id),
            "role": role,
            "chunkCount": chunk_count,
            "hasBlocks": bool(blocks),
        }
        return blocks, meta, False

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
        session = target.thread if target else None
        provider = normalize_provider(session.external_provider if session else None)
        external_session_id = normalize_non_empty_text(
            session.external_session_id if session else None
        )
        context_id = normalize_non_empty_text(session.context_id if session else None)

        if target is None:
            return (
                _build_continue_response(
                    conversation_id=resolved_conversation_id,
                    source="manual",
                    metadata={
                        k: v
                        for k, v in [
                            ("provider", provider),
                            ("externalSessionId", external_session_id),
                            ("contextId", context_id),
                        ]
                        if v is not None
                    },
                ),
                False,
            )

        resolved_provider = provider
        resolved_external_session_id = external_session_id

        resolved_source = _resolve_session_source(
            thread_source=session.source if session else None,
            fallback_source=target.source,
        )
        conversation_id = resolved_conversation_id
        db_mutated = False
        if resolved_provider and resolved_external_session_id:
            resolved_agent_source: Literal["personal", "shared"] | None = None
            if target.thread.agent_source in {"personal", "shared"}:
                resolved_agent_source = target.thread.agent_source
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
                    source=resolved_source,
                    provider=resolved_provider,
                    external_session_id=resolved_external_session_id,
                    agent_id=(
                        target.thread.agent_id
                        if isinstance(target.thread.agent_id, UUID)
                        else (
                            session.agent_id
                            if session and isinstance(session.agent_id, UUID)
                            else None
                        )
                    ),
                    agent_source=resolved_agent_source,
                    context_id=context_id,
                    title=(session.title if session else "Session") or "Session",
                )
            )
            conversation_id = bind_result.conversation_id
            db_mutated = bind_result.mutated
        return (
            _build_continue_response(
                conversation_id=conversation_id or resolved_conversation_id,
                source=resolved_source,
                metadata={
                    k: v
                    for k, v in [
                        ("provider", resolved_provider),
                        ("externalSessionId", resolved_external_session_id),
                        ("contextId", context_id),
                    ]
                    if v is not None
                },
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
            target.thread.id
            if target and isinstance(target.thread.id, UUID)
            else normalized_conversation_id
        )

        session = (
            target.thread
            if target
            else await db.scalar(
                select(ConversationThread).where(
                    and_(
                        ConversationThread.id == local_session_id,
                        ConversationThread.user_id == user_id,
                        ConversationThread.status == ConversationThread.STATUS_ACTIVE,
                    )
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
                source=ConversationThread.SOURCE_MANUAL,
                agent_id=agent_id,
                agent_source=agent_source,
                title="Session",
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
        idempotency_key: Optional[str] = None,
        agent_status: str | None = None,
        finish_reason: str | None = None,
        error_code: str | None = None,
    ) -> dict[str, UUID]:
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
        if context_id and isinstance(context_id, str):
            metadata["context_id"] = context_id
        if provider_from_invoke:
            metadata["provider"] = provider_from_invoke
        if external_session_id:
            metadata["externalSessionId"] = external_session_id
        if extra_metadata:
            metadata.update(extra_metadata)
        normalized_user_message_id = normalize_non_empty_text(user_message_id)
        normalized_client_agent_message_id = normalize_non_empty_text(
            client_agent_message_id
        )
        normalized_idempotency_key = normalize_idempotency_key(idempotency_key)
        if normalized_user_message_id:
            metadata["client_message_id"] = normalized_user_message_id
        if normalized_idempotency_key:
            metadata["invoke_idempotency_key"] = normalized_idempotency_key
        if (
            source == "manual"
            and (session_title := _derive_session_title_from_query(query))
            and ConversationThread.is_placeholder_title(session.title)
        ):
            session.title = session_title

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
            invoke_title = _derive_session_title_from_invoke_metadata(invoke_metadata)
            bind_title = invoke_title if invoke_title else session.title
            conversation_id = await conversation_identity_service.bind_external_session(
                db,
                user_id=user_id,
                conversation_id=conversation_id,
                source=source,
                provider=provider_from_invoke,
                external_session_id=external_session_id,
                agent_id=agent_id,
                agent_source=agent_source,
                context_id=context_id if isinstance(context_id, str) else None,
                title=bind_title or "Session",
            )
        else:
            normalized_provider = normalize_provider(provider_from_invoke)
            normalized_context_id = normalize_non_empty_text(context_id)
            if normalized_provider and session.external_provider != normalized_provider:
                session.external_provider = normalized_provider
            if normalized_context_id and session.context_id != normalized_context_id:
                session.context_id = normalized_context_id

        metadata["conversation_id"] = str(conversation_id)
        agent_metadata = dict(metadata)
        if normalized_client_agent_message_id:
            agent_metadata["client_message_id"] = normalized_client_agent_message_id
        if response_metadata:
            for key, value in response_metadata.items():
                if key == "message_blocks":
                    continue
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
        resolved_agent_status = (
            normalize_non_empty_text(agent_status)
            if isinstance(agent_status, str)
            else None
        )
        if not resolved_agent_status:
            resolved_agent_status = "done" if success else "error"
        resolved_finish_reason = normalize_non_empty_text(finish_reason)
        resolved_error_code = normalize_non_empty_text(error_code)
        summary_text = _derive_agent_summary_text(response_content)
        existing_user_message: AgentMessage | None = None
        existing_agent_message: AgentMessage | None = None
        if normalized_idempotency_key:
            existing_user_message = await self._find_message_by_idempotency_key(
                db,
                user_id=user_id,
                conversation_id=conversation_id,
                sender="user",
                idempotency_key=normalized_idempotency_key,
            )
            existing_agent_message = await self._find_message_by_idempotency_key(
                db,
                user_id=user_id,
                conversation_id=conversation_id,
                sender="agent",
                idempotency_key=normalized_idempotency_key,
            )

        if existing_user_message is None:
            try:
                user_message = await agent_message_handler.create_agent_message(
                    db,
                    user_id=user_id,
                    content=query,
                    sender="user",
                    status="done",
                    conversation_id=conversation_id,
                    metadata=metadata,
                    invoke_idempotency_key=normalized_idempotency_key,
                )
            except agent_message_handler.AgentMessageCreationError as exc:
                if not (
                    normalized_idempotency_key
                    and _is_idempotency_unique_violation(
                        exc,
                        index_name="uq_agent_messages_conversation_sender_invoke_idempotency_key",
                    )
                ):
                    raise
                recovered_user_message = await self._find_message_by_idempotency_key(
                    db,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    sender="user",
                    idempotency_key=normalized_idempotency_key,
                )
                if recovered_user_message is None:
                    raise
                user_message = recovered_user_message
        else:
            user_message = existing_user_message
            if normalized_idempotency_key:
                user_message.invoke_idempotency_key = normalized_idempotency_key

        if existing_agent_message is None:
            try:
                agent_message = await agent_message_handler.create_agent_message(
                    db,
                    user_id=user_id,
                    content=response_content,
                    sender="agent",
                    conversation_id=conversation_id,
                    status=resolved_agent_status,
                    finish_reason=resolved_finish_reason,
                    error_code=resolved_error_code,
                    summary_text=summary_text,
                    metadata=agent_metadata,
                    invoke_idempotency_key=normalized_idempotency_key,
                )
            except agent_message_handler.AgentMessageCreationError as exc:
                if not (
                    normalized_idempotency_key
                    and _is_idempotency_unique_violation(
                        exc,
                        index_name="uq_agent_messages_conversation_sender_invoke_idempotency_key",
                    )
                ):
                    raise
                recovered_agent_message = await self._find_message_by_idempotency_key(
                    db,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    sender="agent",
                    idempotency_key=normalized_idempotency_key,
                )
                if recovered_agent_message is None:
                    raise
                agent_message = await agent_message_handler.update_agent_message(
                    db,
                    message=recovered_agent_message,
                    content=response_content,
                    status=resolved_agent_status,
                    finish_reason=resolved_finish_reason,
                    error_code=resolved_error_code,
                    summary_text=summary_text,
                    message_metadata=agent_metadata,
                    invoke_idempotency_key=normalized_idempotency_key,
                )
        else:
            agent_message = await agent_message_handler.update_agent_message(
                db,
                message=existing_agent_message,
                content=response_content,
                status=resolved_agent_status,
                finish_reason=resolved_finish_reason,
                error_code=resolved_error_code,
                summary_text=summary_text,
                message_metadata=agent_metadata,
                invoke_idempotency_key=normalized_idempotency_key,
            )
        target_session = session
        if conversation_id != session.id:
            rebound_session = await self._get_local_session_by_id(
                db,
                user_id=user_id,
                local_session_id=conversation_id,
            )
            if rebound_session is not None:
                target_session = rebound_session
        target_session.last_active_at = utc_now()
        return {
            "conversation_id": conversation_id,
            "user_message_id": user_message.id,
            "agent_message_id": agent_message.id,
        }

    async def _find_message_by_idempotency_key(
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
        existing = await db.scalar(stmt)
        if existing is not None:
            return existing

        # Backward-compatibility fallback for rows created before dedicated column
        # migration/backfill. Found records are upgraded in-place for future lookups.
        legacy_stmt = (
            select(AgentMessage)
            .where(
                and_(
                    AgentMessage.user_id == user_id,
                    AgentMessage.conversation_id == conversation_id,
                    AgentMessage.sender == sender,
                )
            )
            .order_by(AgentMessage.created_at.desc(), AgentMessage.id.desc())
            .limit(50)
        )
        candidates = list((await db.scalars(legacy_stmt)).all())
        for candidate in candidates:
            metadata = candidate.message_metadata
            if not isinstance(metadata, dict):
                continue
            candidate_key = normalize_idempotency_key(
                metadata.get("invoke_idempotency_key")
            )
            if candidate_key == idempotency_key:
                candidate.invoke_idempotency_key = idempotency_key
                return candidate
        return None

    async def record_local_invoke_messages_by_local_session_id(
        self,
        db: AsyncSession,
        *,
        local_session_id: UUID,
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
        idempotency_key: Optional[str] = None,
        agent_status: str | None = None,
        finish_reason: str | None = None,
        error_code: str | None = None,
    ) -> dict[str, UUID]:
        session = await self._get_local_session_by_id(
            db,
            user_id=user_id,
            local_session_id=local_session_id,
        )
        if session is None:
            return {}

        return await self.record_local_invoke_messages(
            db,
            session=session,
            source=source,
            user_id=user_id,
            agent_id=agent_id,
            agent_source=agent_source,
            query=query,
            response_content=response_content,
            success=success,
            context_id=context_id,
            user_message_id=user_message_id,
            client_agent_message_id=client_agent_message_id,
            invoke_metadata=invoke_metadata,
            extra_metadata=extra_metadata,
            response_metadata=response_metadata,
            idempotency_key=idempotency_key,
            agent_status=agent_status,
            finish_reason=finish_reason,
            error_code=error_code,
        )

    async def ensure_local_invoke_message_headers_by_local_session_id(
        self,
        db: AsyncSession,
        *,
        local_session_id: UUID,
        source: SessionSource,
        user_id: UUID,
        agent_id: UUID,
        agent_source: Literal["personal", "shared"],
        query: str,
        context_id: Optional[str],
        user_message_id: Optional[str] = None,
        client_agent_message_id: Optional[str] = None,
        invoke_metadata: Optional[Dict[str, Any]] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, UUID]:
        session = await self._get_local_session_by_id(
            db,
            user_id=user_id,
            local_session_id=local_session_id,
        )
        if session is None:
            return {}

        normalized_idempotency_key = normalize_idempotency_key(idempotency_key)
        if normalized_idempotency_key:
            existing_user_message = await db.scalar(
                select(AgentMessage).where(
                    and_(
                        AgentMessage.user_id == user_id,
                        AgentMessage.conversation_id == local_session_id,
                        AgentMessage.sender.in_(["user", "automation"]),
                        AgentMessage.invoke_idempotency_key
                        == normalized_idempotency_key,
                    )
                )
            )
            existing_agent_message = await db.scalar(
                select(AgentMessage).where(
                    and_(
                        AgentMessage.user_id == user_id,
                        AgentMessage.conversation_id == local_session_id,
                        AgentMessage.sender == "agent",
                        AgentMessage.invoke_idempotency_key
                        == normalized_idempotency_key,
                    )
                )
            )
            if existing_user_message and existing_agent_message:
                return {
                    "conversation_id": local_session_id,
                    "user_message_id": existing_user_message.id,
                    "agent_message_id": existing_agent_message.id,
                }

        return await self.record_local_invoke_messages(
            db,
            session=session,
            source=source,
            user_id=user_id,
            agent_id=agent_id,
            agent_source=agent_source,
            query=query,
            response_content="",
            success=False,
            context_id=context_id,
            user_message_id=user_message_id,
            client_agent_message_id=client_agent_message_id,
            invoke_metadata=invoke_metadata,
            extra_metadata=extra_metadata,
            response_metadata=None,
            idempotency_key=idempotency_key,
            agent_status="streaming",
            finish_reason=None,
            error_code=None,
        )

    async def append_agent_message_chunk(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        agent_message_id: UUID,
        seq: int,
        block_type: str,
        content: str,
        append: bool,
        is_finished: bool,
        event_id: str | None = None,
        source: str | None = None,
    ) -> AgentMessageChunk | None:
        if seq <= 0:
            return None
        message = await db.scalar(
            select(AgentMessage).where(
                and_(
                    AgentMessage.id == agent_message_id,
                    AgentMessage.user_id == user_id,
                    AgentMessage.sender == "agent",
                )
            )
        )
        if message is None:
            return None
        normalized_event_id = normalize_non_empty_text(event_id)
        if normalized_event_id:
            existing_by_event = (
                await agent_message_chunk_handler.find_chunk_by_message_and_event_id(
                    db,
                    user_id=user_id,
                    message_id=agent_message_id,
                    event_id=normalized_event_id,
                )
            )
            if existing_by_event is not None:
                return None
        existing_by_seq = (
            await agent_message_chunk_handler.find_chunk_by_message_and_seq(
                db,
                user_id=user_id,
                message_id=agent_message_id,
                seq=seq,
            )
        )
        if existing_by_seq is not None:
            return None
        try:
            async with db.begin_nested():
                return await agent_message_chunk_handler.create_chunk(
                    db,
                    user_id=user_id,
                    message_id=agent_message_id,
                    seq=seq,
                    block_type=block_type,
                    content=content,
                    append=append,
                    is_finished=is_finished,
                    event_id=normalized_event_id,
                    source=normalize_non_empty_text(source),
                )
        except IntegrityError as exc:
            if not (
                _is_idempotency_unique_violation(
                    exc, index_name="uq_agent_message_chunks_message_id_seq"
                )
                or _is_idempotency_unique_violation(
                    exc, index_name="uq_agent_message_chunks_message_id_event_id"
                )
            ):
                raise
            return None

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
        local_session_id = conversation_id
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
                thread=local_session,
            )
        if local_session.source == ConversationThread.SOURCE_SCHEDULED:
            return ResolvedConversationTarget(
                source="scheduled",
                thread=local_session,
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


def _parse_message_id(value: str) -> UUID:
    trimmed = (value or "").strip()
    if not trimmed:
        raise ValueError("message_id is required")
    try:
        return UUID(trimmed)
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid_message_id") from exc


def _build_continue_response(
    *,
    conversation_id: UUID,
    source: ResolvedSource,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return {
        "conversationId": str(conversation_id),
        "source": source,
        "metadata": metadata,
    }


def _resolve_session_source(
    *,
    thread_source: str | None,
    fallback_source: ResolvedSource | None,
) -> ResolvedSource:
    if thread_source == ConversationThread.SOURCE_SCHEDULED:
        return "scheduled"
    if thread_source == ConversationThread.SOURCE_MANUAL:
        return "manual"
    if fallback_source in {"manual", "scheduled"}:
        return fallback_source
    return "manual"


def _sender_to_role(sender: str) -> str:
    normalized = (sender or "").strip().lower()
    if normalized in {"user", "automation"}:
        return "user"
    if normalized == "agent":
        return "agent"
    return "system"


def _derive_session_title_from_query(query: str) -> str | None:
    trimmed_query = query.strip() if isinstance(query, str) else ""
    if not trimmed_query:
        return None
    return trimmed_query[: ConversationThread.TITLE_MAX_LENGTH]


def _derive_agent_summary_text(content: str | None, *, max_chars: int = 2048) -> str:
    if not isinstance(content, str):
        return ""
    trimmed = content.strip()
    if not trimmed:
        return ""
    return trimmed[:max_chars]


def _project_message_from_chunks(
    chunks: list[AgentMessageChunk],
) -> tuple[str, list[dict[str, Any]]]:
    ordered = sorted(
        chunks,
        key=lambda item: (
            int(item.seq) if isinstance(item.seq, int) else 0,
            item.created_at,
            item.id,
        ),
    )
    projected_blocks: list[dict[str, Any]] = []
    block_seq = 0
    for chunk in ordered:
        delta = chunk.content if isinstance(chunk.content, str) else ""
        block_type = (
            chunk.block_type.strip().lower()
            if isinstance(chunk.block_type, str) and chunk.block_type.strip()
            else "text"
        )
        append = bool(chunk.append)
        is_finished = bool(chunk.is_finished)

        overwrite = not append
        last = projected_blocks[-1] if projected_blocks else None

        def _mark_last_finished() -> None:
            if isinstance(last, dict) and last.get("is_finished") is False:
                last["is_finished"] = True

        if overwrite:
            if (
                isinstance(last, dict)
                and last.get("type") == block_type
                and last.get("is_finished") is False
            ):
                last["content"] = delta
                last["is_finished"] = is_finished
                continue
            _mark_last_finished()
            block_seq += 1
            projected_blocks.append(
                {
                    "id": f"block-{block_seq}",
                    "seq": block_seq,
                    "type": block_type,
                    "content": delta,
                    "is_finished": is_finished,
                }
            )
            continue

        if (
            isinstance(last, dict)
            and last.get("type") == block_type
            and last.get("is_finished") is False
        ):
            current = last.get("content")
            last["content"] = f"{current if isinstance(current, str) else ''}{delta}"
            last["is_finished"] = is_finished
            continue

        _mark_last_finished()
        block_seq += 1
        projected_blocks.append(
            {
                "id": f"block-{block_seq}",
                "seq": block_seq,
                "type": block_type,
                "content": delta,
                "is_finished": is_finished,
            }
        )

    for idx, block in enumerate(projected_blocks, start=1):
        block["id"] = f"block-{idx}"
        block["seq"] = idx

    text_content = "".join(
        block.get("content", "")
        for block in projected_blocks
        if block.get("type") == "text" and isinstance(block.get("content"), str)
    )
    return text_content, projected_blocks


def _derive_session_title_from_invoke_metadata(
    metadata: Optional[Dict[str, Any]],
) -> str | None:
    if not isinstance(metadata, dict):
        return None
    root_title = normalize_non_empty_text(metadata.get("title"))
    if root_title:
        return root_title[: ConversationThread.TITLE_MAX_LENGTH]
    nested = metadata.get("opencode")
    if isinstance(nested, dict):
        nested_title = normalize_non_empty_text(nested.get("title"))
        if nested_title:
            return nested_title[: ConversationThread.TITLE_MAX_LENGTH]
    return None


session_hub_service = SessionHubService()


def _is_idempotency_unique_violation(exc: BaseException, *, index_name: str) -> bool:
    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, IntegrityError):
            if index_name in str(current):
                return True
            original = getattr(current, "orig", None)
            if original is not None and index_name in str(original):
                return True
        current = current.__cause__ or current.__context__
    return False


__all__ = [
    "ResolvedConversationTarget",
    "SessionHubService",
    "SessionSource",
    "session_hub_service",
]
