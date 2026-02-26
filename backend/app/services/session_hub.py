"""Unified conversation domain helpers and query service.

This module provides a single read model for session list/history/continue across:
- local manual chat sessions
- local scheduled sessions
- local OpenCode-bound sessions
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_message import AgentMessage
from app.db.models.agent_message_block import AgentMessageBlock
from app.db.models.conversation_thread import ConversationThread
from app.handlers import agent_message as agent_message_handler
from app.handlers import agent_message_block as agent_message_block_handler
from app.services.conversation_identity import conversation_identity_service
from app.utils.idempotency_key import normalize_idempotency_key
from app.utils.payload_extract import extract_provider_and_external_session_id
from app.utils.session_identity import normalize_non_empty_text, normalize_provider
from app.utils.timezone_util import utc_now

SessionSource = Literal["manual", "scheduled"]
ResolvedSource = Literal["manual", "scheduled"]
BlocksQueryMode = Literal["full", "text_with_placeholders", "outline"]


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
        agent_id: Optional[UUID],
    ) -> tuple[list[dict[str, Any]], dict[str, Any], bool]:
        page_items = await self._list_local_sessions(
            db,
            user_id=user_id,
            source=source,
            agent_id=agent_id,
        )
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
        agent_id: Optional[UUID],
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
            if agent_id and thread.agent_id != agent_id:
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
        total = await agent_message_handler.count_agent_messages(
            db,
            user_id=user_id,
            conversation_id=resolved_conversation_id,
        )
        pages = (total + size - 1) // size if size else 0
        items: list[dict[str, Any]] = []
        for message in messages:
            message_metadata = _sanitize_message_metadata_for_api(
                getattr(message, "message_metadata", None)
            )
            role = _sender_to_role(getattr(message, "sender", ""))
            if isinstance(message.id, UUID) and role == "agent":
                summary_text = normalize_non_empty_text(
                    getattr(message, "summary_text", None)
                )
                if summary_text:
                    message_metadata.setdefault("summary_text", summary_text)
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
                    "role": role,
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

    async def query_message_blocks(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: str,
        message_ids: list[str],
        mode: BlocksQueryMode,
    ) -> tuple[list[dict[str, Any]], dict[str, Any], bool]:
        resolved_conversation_id = _parse_conversation_id(conversation_id)
        if mode not in {"full", "text_with_placeholders", "outline"}:
            raise ValueError("invalid_blocks_mode")

        if not message_ids:
            raise ValueError("invalid_message_id")

        resolved_message_ids: list[UUID] = []
        for message_id in message_ids:
            resolved = _parse_message_id(message_id)
            if resolved not in resolved_message_ids:
                resolved_message_ids.append(resolved)

        rows = list(
            (
                await db.scalars(
                    select(AgentMessage).where(
                        and_(
                            AgentMessage.user_id == user_id,
                            AgentMessage.conversation_id == resolved_conversation_id,
                            AgentMessage.id.in_(resolved_message_ids),
                        )
                    )
                )
            ).all()
        )
        message_by_id = {row.id: row for row in rows if isinstance(row.id, UUID)}
        if len(message_by_id) != len(resolved_message_ids):
            raise ValueError("message_not_found")

        blocks_by_message_id: dict[UUID, list[AgentMessageBlock]] = {}
        if resolved_message_ids:
            blocks = await agent_message_block_handler.list_blocks_by_message_ids(
                db,
                user_id=user_id,
                message_ids=resolved_message_ids,
            )
            for block in blocks:
                if not isinstance(block.message_id, UUID):
                    continue
                blocks_by_message_id.setdefault(block.message_id, []).append(block)

        items: list[dict[str, Any]] = []
        for message_id in resolved_message_ids:
            message = message_by_id[message_id]
            role = _sender_to_role(getattr(message, "sender", ""))
            raw_blocks = blocks_by_message_id.get(message_id, [])
            rendered_blocks = _render_blocks_for_mode(raw_blocks, mode=mode)
            block_count = len(raw_blocks)
            has_blocks = bool(raw_blocks)
            items.append(
                {
                    "messageId": str(message_id),
                    "role": role,
                    "blockCount": block_count,
                    "hasBlocks": has_blocks,
                    "blocks": rendered_blocks,
                }
            )

        meta = {
            "conversationId": str(resolved_conversation_id),
            "mode": mode,
        }
        return items, meta, False

    async def query_message_block_detail(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: str,
        message_id: str,
        block_seq: int,
    ) -> tuple[dict[str, Any], bool]:
        resolved_conversation_id = _parse_conversation_id(conversation_id)
        resolved_message_id = _parse_message_id(message_id)
        if block_seq <= 0:
            raise ValueError("invalid_block_seq")
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
        block = await agent_message_block_handler.find_block_by_message_and_block_seq(
            db,
            user_id=user_id,
            message_id=resolved_message_id,
            block_seq=block_seq,
        )
        if block is None:
            raise ValueError("block_not_found")
        rendered = _render_block_item(block, mode="full")
        return {
            "messageId": str(resolved_message_id),
            "block": rendered,
        }, False

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
        invoke_metadata: Optional[Dict[str, Any]] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
        response_metadata: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        user_message_id: UUID | None = None,
        agent_message_id: UUID | None = None,
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
        query_hash = _build_query_hash(query)
        metadata["query_hash"] = query_hash
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
        normalized_idempotency_key = normalize_idempotency_key(idempotency_key)
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
        requested_user_message = (
            await self._find_message_by_id_and_sender(
                db,
                user_id=user_id,
                message_id=user_message_id,
                sender="user",
                conversation_id=conversation_id,
            )
            if isinstance(user_message_id, UUID)
            else None
        )
        requested_agent_message = (
            await self._find_message_by_id_and_sender(
                db,
                user_id=user_id,
                message_id=agent_message_id,
                sender="agent",
                conversation_id=conversation_id,
            )
            if isinstance(agent_message_id, UUID)
            else None
        )
        existing_user_message: AgentMessage | None = requested_user_message
        existing_agent_message: AgentMessage | None = requested_agent_message
        if normalized_idempotency_key:
            idempotent_user_message = await self._find_message_by_idempotency_key(
                db,
                user_id=user_id,
                conversation_id=conversation_id,
                sender="user",
                idempotency_key=normalized_idempotency_key,
            )
            idempotent_agent_message = await self._find_message_by_idempotency_key(
                db,
                user_id=user_id,
                conversation_id=conversation_id,
                sender="agent",
                idempotency_key=normalized_idempotency_key,
            )
            if (
                existing_user_message is not None
                and idempotent_user_message is not None
                and existing_user_message.id != idempotent_user_message.id
            ):
                raise ValueError("message_id_conflict")
            if (
                existing_agent_message is not None
                and idempotent_agent_message is not None
                and existing_agent_message.id != idempotent_agent_message.id
            ):
                raise ValueError("message_id_conflict")
            if existing_user_message is None:
                existing_user_message = idempotent_user_message
            if existing_agent_message is None:
                existing_agent_message = idempotent_agent_message

        if existing_user_message is None:
            try:
                user_message = await agent_message_handler.create_agent_message(
                    db,
                    **(
                        {"id": user_message_id}
                        if isinstance(user_message_id, UUID)
                        else {}
                    ),
                    user_id=user_id,
                    sender="user",
                    status="done",
                    conversation_id=conversation_id,
                    metadata=metadata,
                    invoke_idempotency_key=normalized_idempotency_key,
                )
            except agent_message_handler.AgentMessageCreationError as exc:
                if isinstance(user_message_id, UUID) and _is_agent_message_pk_violation(
                    exc
                ):
                    raise ValueError("message_id_conflict") from exc
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
                if (
                    isinstance(user_message_id, UUID)
                    and recovered_user_message.id != user_message_id
                ):
                    raise ValueError("message_id_conflict")
                user_message = recovered_user_message
        else:
            user_message = existing_user_message
            if isinstance(user_message_id, UUID) and user_message.id != user_message_id:
                raise ValueError("message_id_conflict")
            if normalized_idempotency_key:
                user_message.invoke_idempotency_key = normalized_idempotency_key
        await self._ensure_idempotent_user_query(
            db,
            user_id=user_id,
            user_message=user_message,
            query=query,
            query_hash=query_hash,
            idempotency_key=normalized_idempotency_key,
        )

        if existing_agent_message is None:
            try:
                agent_message = await agent_message_handler.create_agent_message(
                    db,
                    **(
                        {"id": agent_message_id}
                        if isinstance(agent_message_id, UUID)
                        else {}
                    ),
                    user_id=user_id,
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
                if isinstance(
                    agent_message_id, UUID
                ) and _is_agent_message_pk_violation(exc):
                    raise ValueError("message_id_conflict") from exc
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
                if (
                    isinstance(agent_message_id, UUID)
                    and recovered_agent_message.id != agent_message_id
                ):
                    raise ValueError("message_id_conflict")
                agent_message = await agent_message_handler.update_agent_message(
                    db,
                    message=recovered_agent_message,
                    status=resolved_agent_status,
                    finish_reason=resolved_finish_reason,
                    error_code=resolved_error_code,
                    summary_text=summary_text,
                    message_metadata=agent_metadata,
                    invoke_idempotency_key=normalized_idempotency_key,
                )
        else:
            if (
                isinstance(agent_message_id, UUID)
                and existing_agent_message.id != agent_message_id
            ):
                raise ValueError("message_id_conflict")
            agent_message = await agent_message_handler.update_agent_message(
                db,
                message=existing_agent_message,
                status=resolved_agent_status,
                finish_reason=resolved_finish_reason,
                error_code=resolved_error_code,
                summary_text=summary_text,
                message_metadata=agent_metadata,
                invoke_idempotency_key=normalized_idempotency_key,
            )
        await self._upsert_single_text_block(
            db,
            user_id=user_id,
            message_id=user_message.id,
            content=query,
            source="user_input",
        )
        if isinstance(response_content, str) and response_content:
            existing_agent_blocks = (
                await agent_message_block_handler.list_blocks_by_message_id(
                    db,
                    user_id=user_id,
                    message_id=agent_message.id,
                )
            )
            can_upsert_snapshot = not existing_agent_blocks or (
                len(existing_agent_blocks) == 1
                and int(existing_agent_blocks[0].block_seq) == 1
                and _normalize_block_type(existing_agent_blocks[0].block_type) == "text"
                and normalize_non_empty_text(existing_agent_blocks[0].source)
                in {"final_snapshot", "finalize_snapshot"}
            )
            if can_upsert_snapshot:
                await self._upsert_single_text_block(
                    db,
                    user_id=user_id,
                    message_id=agent_message.id,
                    content=response_content,
                    source="finalize_snapshot",
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
        return existing

    async def _find_message_by_id_and_sender(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        message_id: UUID,
        sender: str,
        conversation_id: UUID,
    ) -> AgentMessage | None:
        message = await db.scalar(
            select(AgentMessage).where(
                and_(
                    AgentMessage.id == message_id,
                    AgentMessage.user_id == user_id,
                )
            )
        )
        if message is None:
            return None
        normalized_sender = (sender or "").strip().lower()
        message_sender = (message.sender or "").strip().lower()
        if normalized_sender == "user":
            is_user_sender = message_sender in {"user", "automation"}
            if not is_user_sender:
                raise ValueError("message_id_conflict")
        elif message_sender != normalized_sender:
            raise ValueError("message_id_conflict")
        if message.conversation_id != conversation_id:
            raise ValueError("message_id_conflict")
        return message

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
        invoke_metadata: Optional[Dict[str, Any]] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
        response_metadata: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        user_message_id: UUID | None = None,
        agent_message_id: UUID | None = None,
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
            invoke_metadata=invoke_metadata,
            extra_metadata=extra_metadata,
            response_metadata=response_metadata,
            idempotency_key=idempotency_key,
            user_message_id=user_message_id,
            agent_message_id=agent_message_id,
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
        invoke_metadata: Optional[Dict[str, Any]] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        user_message_id: UUID | None = None,
        agent_message_id: UUID | None = None,
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
                if (
                    isinstance(user_message_id, UUID)
                    and existing_user_message.id != user_message_id
                ):
                    raise ValueError("message_id_conflict")
                if (
                    isinstance(agent_message_id, UUID)
                    and existing_agent_message.id != agent_message_id
                ):
                    raise ValueError("message_id_conflict")
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
            invoke_metadata=invoke_metadata,
            extra_metadata=extra_metadata,
            response_metadata=None,
            idempotency_key=idempotency_key,
            user_message_id=user_message_id,
            agent_message_id=agent_message_id,
            agent_status="streaming",
            finish_reason=None,
            error_code=None,
        )

    async def append_agent_message_block_update(
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
    ) -> AgentMessageBlock | None:
        if seq <= 0:
            return None
        normalized_content = str(content or "")
        if not normalized_content:
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

        message_metadata = dict(getattr(message, "message_metadata", None) or {})
        cursor_state = _read_block_cursor_state(message_metadata)
        if seq <= cursor_state["last_event_seq"]:
            return None

        normalized_type = _normalize_block_type(block_type)
        normalized_source = normalize_non_empty_text(source)
        overwrite = (not append) or normalized_source in {
            "final_snapshot",
            "finalize_snapshot",
        }
        active_block_seq = cursor_state["active_block_seq"]

        active_block: AgentMessageBlock | None = None
        if active_block_seq > 0:
            active_block = (
                await agent_message_block_handler.find_block_by_message_and_block_seq(
                    db,
                    user_id=user_id,
                    message_id=agent_message_id,
                    block_seq=active_block_seq,
                )
            )
        if active_block is None:
            active_block = (
                await agent_message_block_handler.find_last_block_for_message(
                    db,
                    user_id=user_id,
                    message_id=agent_message_id,
                )
            )

        persisted_block: AgentMessageBlock | None = None
        if overwrite:
            if (
                active_block is not None
                and active_block.block_type == normalized_type
                and not bool(active_block.is_finished)
            ):
                active_block.content = normalized_content
                active_block.is_finished = bool(is_finished)
                active_block.source = normalized_source or active_block.source
                if active_block.start_event_seq is None:
                    active_block.start_event_seq = seq
                if (
                    active_block.end_event_seq is None
                    or seq >= active_block.end_event_seq
                ):
                    active_block.end_event_seq = seq
                normalized_event_id = normalize_non_empty_text(event_id)
                if normalized_event_id and not active_block.start_event_id:
                    active_block.start_event_id = normalized_event_id
                if normalized_event_id:
                    active_block.end_event_id = normalized_event_id
                persisted_block = active_block
            else:
                if active_block is not None and not bool(active_block.is_finished):
                    active_block.is_finished = True
                next_block_seq = (
                    max(
                        cursor_state["last_block_seq"],
                        int(getattr(active_block, "block_seq", 0) or 0),
                    )
                    + 1
                )
                normalized_event_id = normalize_non_empty_text(event_id)
                persisted_block = await _create_block_with_conflict_recovery(
                    db,
                    user_id=user_id,
                    message_id=agent_message_id,
                    block_seq=next_block_seq,
                    block_type=normalized_type,
                    content=normalized_content,
                    is_finished=bool(is_finished),
                    source=normalized_source,
                    start_event_seq=seq,
                    end_event_seq=seq,
                    start_event_id=normalized_event_id,
                    end_event_id=normalized_event_id,
                )
        else:
            if (
                active_block is not None
                and active_block.block_type == normalized_type
                and not bool(active_block.is_finished)
            ):
                current_content = (
                    active_block.content
                    if isinstance(active_block.content, str)
                    else ""
                )
                active_block.content = f"{current_content}{normalized_content}"
                active_block.is_finished = bool(is_finished)
                active_block.source = normalized_source or active_block.source
                if active_block.start_event_seq is None:
                    active_block.start_event_seq = seq
                if (
                    active_block.end_event_seq is None
                    or seq >= active_block.end_event_seq
                ):
                    active_block.end_event_seq = seq
                normalized_event_id = normalize_non_empty_text(event_id)
                if normalized_event_id and not active_block.start_event_id:
                    active_block.start_event_id = normalized_event_id
                if normalized_event_id:
                    active_block.end_event_id = normalized_event_id
                persisted_block = active_block
            else:
                if active_block is not None and not bool(active_block.is_finished):
                    active_block.is_finished = True
                next_block_seq = (
                    max(
                        cursor_state["last_block_seq"],
                        int(getattr(active_block, "block_seq", 0) or 0),
                    )
                    + 1
                )
                normalized_event_id = normalize_non_empty_text(event_id)
                persisted_block = await _create_block_with_conflict_recovery(
                    db,
                    user_id=user_id,
                    message_id=agent_message_id,
                    block_seq=next_block_seq,
                    block_type=normalized_type,
                    content=normalized_content,
                    is_finished=bool(is_finished),
                    source=normalized_source,
                    start_event_seq=seq,
                    end_event_seq=seq,
                    start_event_id=normalized_event_id,
                    end_event_id=normalized_event_id,
                )

        if persisted_block is None:
            return None
        cursor_state["last_event_seq"] = seq
        cursor_state["last_block_seq"] = max(
            cursor_state["last_block_seq"],
            int(getattr(persisted_block, "block_seq", 0) or 0),
        )
        if bool(getattr(persisted_block, "is_finished", False)):
            cursor_state["active_block_seq"] = 0
        else:
            cursor_state["active_block_seq"] = int(
                getattr(persisted_block, "block_seq", 0) or 0
            )
        _write_block_cursor_state(message_metadata, cursor_state)
        message.message_metadata = message_metadata
        await db.flush()
        return persisted_block

    async def has_agent_message_blocks(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        agent_message_id: UUID,
    ) -> bool:
        return await agent_message_block_handler.has_blocks_for_message(
            db,
            user_id=user_id,
            message_id=agent_message_id,
        )

    async def _ensure_idempotent_user_query(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        user_message: AgentMessage,
        query: str,
        query_hash: str,
        idempotency_key: str | None,
    ) -> None:
        if not idempotency_key:
            return
        message_metadata = dict(getattr(user_message, "message_metadata", None) or {})
        existing_query_hash = normalize_non_empty_text(
            message_metadata.get("query_hash")
        )
        if existing_query_hash and existing_query_hash != query_hash:
            raise ValueError("idempotency_conflict")
        if not existing_query_hash:
            first_block = (
                await agent_message_block_handler.find_block_by_message_and_block_seq(
                    db,
                    user_id=user_id,
                    message_id=user_message.id,
                    block_seq=1,
                )
            )
            if first_block is not None:
                persisted_query = (
                    first_block.content if isinstance(first_block.content, str) else ""
                )
                if persisted_query != query:
                    raise ValueError("idempotency_conflict")
        if message_metadata.get("query_hash") != query_hash:
            message_metadata["query_hash"] = query_hash
            user_message.message_metadata = message_metadata
            await db.flush()

    async def _upsert_single_text_block(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        message_id: UUID,
        content: str,
        source: str | None = None,
    ) -> AgentMessageBlock | None:
        existing = (
            await agent_message_block_handler.find_block_by_message_and_block_seq(
                db,
                user_id=user_id,
                message_id=message_id,
                block_seq=1,
            )
        )
        if existing is None:
            existing = await _create_block_with_conflict_recovery(
                db,
                user_id=user_id,
                message_id=message_id,
                block_seq=1,
                block_type="text",
                content=str(content or ""),
                is_finished=True,
                source=normalize_non_empty_text(source),
                start_event_seq=None,
                end_event_seq=None,
                start_event_id=None,
                end_event_id=None,
            )
            if existing is None:
                return None
        existing.block_type = "text"
        existing.content = str(content or "")
        existing.is_finished = True
        normalized_source = normalize_non_empty_text(source)
        if normalized_source:
            existing.source = normalized_source
        await db.flush()
        return existing

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


def _sanitize_message_metadata_for_api(metadata: Any) -> dict[str, Any]:
    resolved = dict(metadata) if isinstance(metadata, dict) else {}
    resolved.pop("message_blocks", None)
    resolved.pop("_block_cursor", None)
    for key in list(resolved.keys()):
        if isinstance(key, str) and key.startswith("_"):
            resolved.pop(key, None)
    return resolved


def _normalize_block_type(raw_type: str | None) -> str:
    normalized = (raw_type or "").strip().lower()
    if normalized in {"text", "reasoning", "tool_call", "system_error"}:
        return normalized
    return "text"


def _read_block_cursor_state(metadata: dict[str, Any]) -> dict[str, int]:
    raw_cursor = metadata.get("_block_cursor")
    cursor = raw_cursor if isinstance(raw_cursor, dict) else {}

    def _int_or_zero(value: Any) -> int:
        if isinstance(value, int):
            return max(value, 0)
        if isinstance(value, str) and value.strip().isdigit():
            return max(int(value.strip()), 0)
        return 0

    return {
        "last_event_seq": _int_or_zero(cursor.get("last_event_seq")),
        "last_block_seq": _int_or_zero(cursor.get("last_block_seq")),
        "active_block_seq": _int_or_zero(cursor.get("active_block_seq")),
    }


def _write_block_cursor_state(metadata: dict[str, Any], cursor: dict[str, int]) -> None:
    metadata["_block_cursor"] = {
        "last_event_seq": int(max(cursor.get("last_event_seq", 0), 0)),
        "last_block_seq": int(max(cursor.get("last_block_seq", 0), 0)),
        "active_block_seq": int(max(cursor.get("active_block_seq", 0), 0)),
    }


def _render_block_item(
    block: AgentMessageBlock,
    *,
    mode: BlocksQueryMode,
) -> dict[str, Any]:
    raw_content = block.content if isinstance(block.content, str) else ""
    block_type = _normalize_block_type(block.block_type)
    if mode == "full":
        rendered_content = raw_content
    elif mode == "text_with_placeholders":
        rendered_content = raw_content if block_type == "text" else None
    else:
        rendered_content = None
    return {
        "id": str(block.id),
        "messageId": str(block.message_id),
        "seq": int(block.block_seq),
        "type": block_type,
        "content": rendered_content,
        "contentLength": len(raw_content),
        "isFinished": bool(block.is_finished),
    }


def _render_blocks_for_mode(
    blocks: list[AgentMessageBlock], *, mode: BlocksQueryMode
) -> list[dict[str, Any]]:
    return [_render_block_item(block, mode=mode) for block in blocks]


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


def _build_query_hash(query: str) -> str:
    return hashlib.sha256(str(query or "").encode("utf-8")).hexdigest()


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


def _is_agent_message_pk_violation(exc: BaseException) -> bool:
    return _is_idempotency_unique_violation(exc, index_name="agent_messages_pkey")


async def _create_block_with_conflict_recovery(
    db: AsyncSession,
    *,
    user_id: UUID,
    message_id: UUID,
    block_seq: int,
    block_type: str,
    content: str,
    is_finished: bool,
    source: str | None,
    start_event_seq: int | None,
    end_event_seq: int | None,
    start_event_id: str | None,
    end_event_id: str | None,
) -> AgentMessageBlock | None:
    """Insert one block with best-effort recovery for concurrent same-seq writes."""
    try:
        async with db.begin_nested():
            return await agent_message_block_handler.create_block(
                db,
                user_id=user_id,
                message_id=message_id,
                block_seq=block_seq,
                block_type=block_type,
                content=content,
                is_finished=is_finished,
                source=source,
                start_event_seq=start_event_seq,
                end_event_seq=end_event_seq,
                start_event_id=start_event_id,
                end_event_id=end_event_id,
            )
    except IntegrityError as exc:
        if not _is_idempotency_unique_violation(
            exc, index_name="ix_agent_message_blocks_message_id_block_seq"
        ):
            raise
        return await agent_message_block_handler.find_block_by_message_and_block_seq(
            db,
            user_id=user_id,
            message_id=message_id,
            block_seq=block_seq,
        )


__all__ = [
    "ResolvedConversationTarget",
    "SessionHubService",
    "SessionSource",
    "session_hub_service",
]
