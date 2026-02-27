"""Unified conversation domain helpers and query service.

This module provides a single read model for session list/history/continue across:
- local manual chat sessions
- local scheduled sessions
- local OpenCode-bound sessions
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Literal, Optional
from uuid import UUID, uuid4

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.agent_message import AgentMessage
from app.db.models.agent_message_block import AgentMessageBlock
from app.db.models.conversation_thread import ConversationThread
from app.handlers import agent_message as agent_message_handler
from app.handlers import agent_message_block as agent_message_block_handler
from app.services.conversation_identity import conversation_identity_service
from app.utils.idempotency_key import normalize_idempotency_key
from app.utils.payload_extract import extract_provider_and_external_session_id
from app.utils.session_identity import normalize_non_empty_text, normalize_provider
from app.utils.timezone_util import ensure_utc, utc_now

SessionSource = Literal["manual", "scheduled"]
ResolvedSource = Literal["manual", "scheduled"]
logger = get_logger(__name__)


@dataclass(frozen=True)
class ResolvedConversationTarget:
    source: ResolvedSource
    thread: ConversationThread


@dataclass(frozen=True)
class MessagesBeforeCursor:
    created_at: datetime
    sender_priority: int
    message_id: UUID


@dataclass
class _InflightInvokeEntry:
    token: str
    task_id: str | None = None
    gateway: Any | None = None
    resolved: Any | None = None
    cancel_requested: bool = False
    cancel_reason: str | None = None


_inflight_invokes_lock = asyncio.Lock()
_inflight_invokes: dict[tuple[str, str], dict[str, _InflightInvokeEntry]] = {}
_INFLIGHT_CANCEL_TERMINAL_ERROR_CODES = {
    "task_not_found",
    "task_not_cancelable",
    "invalid_task_id",
}


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
        offset = (page - 1) * size if page > 0 else 0
        limit = size if size > 0 else None

        page_items, total = await self._list_local_sessions(
            db,
            user_id=user_id,
            source=source,
            agent_id=agent_id,
            limit=limit,
            offset=offset,
        )
        pages = (total + size - 1) // size if size else 0

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
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> tuple[list[dict[str, Any]], int]:
        filters = [
            ConversationThread.user_id == user_id,
            ConversationThread.status == ConversationThread.STATUS_ACTIVE,
            ConversationThread.source.in_(
                [
                    ConversationThread.SOURCE_MANUAL,
                    ConversationThread.SOURCE_SCHEDULED,
                ]
            ),
        ]
        if source:
            # SessionSource values ("manual", "scheduled") match ConversationThread constants
            filters.append(ConversationThread.source == source)
        if agent_id:
            filters.append(ConversationThread.agent_id == agent_id)

        # Count total
        count_stmt = (
            select(func.count()).select_from(ConversationThread).where(and_(*filters))
        )
        total = (await db.execute(count_stmt)).scalar() or 0

        # Query threads
        stmt = (
            select(ConversationThread)
            .where(and_(*filters))
            .order_by(
                ConversationThread.last_active_at.desc(),
                ConversationThread.created_at.desc(),
            )
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        if offset is not None:
            stmt = stmt.offset(offset)

        threads = list((await db.execute(stmt)).scalars().all())
        items: list[dict[str, Any]] = []

        for thread in threads:
            resolved_source = _resolve_session_source(
                thread_source=thread.source,
                fallback_source=None,
            )
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

        return items, total

    async def list_messages(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: str,
        before: str | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any], bool]:
        resolved_conversation_id = _parse_conversation_id(conversation_id)

        cursor = _parse_messages_before_cursor(before) if before else None
        sender_priority = case(
            (AgentMessage.sender.in_(["user", "automation"]), 0),
            else_=1,
        )
        stmt = select(AgentMessage).where(
            and_(
                AgentMessage.user_id == user_id,
                AgentMessage.conversation_id == resolved_conversation_id,
            )
        )
        if cursor is not None:
            stmt = stmt.where(
                or_(
                    AgentMessage.created_at < cursor.created_at,
                    and_(
                        AgentMessage.created_at == cursor.created_at,
                        sender_priority < cursor.sender_priority,
                    ),
                    and_(
                        AgentMessage.created_at == cursor.created_at,
                        sender_priority == cursor.sender_priority,
                        AgentMessage.id < cursor.message_id,
                    ),
                )
            )

        rows = list(
            (
                await db.scalars(
                    stmt.order_by(
                        AgentMessage.created_at.desc(),
                        sender_priority.desc(),
                        AgentMessage.id.desc(),
                    ).limit(limit + 1)
                )
            ).all()
        )
        has_more_before = len(rows) > limit
        if has_more_before:
            rows = rows[:limit]
        messages = list(reversed(rows))

        message_ids = [
            message.id for message in messages if isinstance(message.id, UUID)
        ]
        blocks_by_message_id: dict[UUID, list[AgentMessageBlock]] = {}
        if message_ids:
            blocks = await agent_message_block_handler.list_blocks_by_message_ids(
                db,
                user_id=user_id,
                message_ids=message_ids,
            )
            for block in blocks:
                if not isinstance(block.message_id, UUID):
                    continue
                blocks_by_message_id.setdefault(block.message_id, []).append(block)

        items: list[dict[str, Any]] = []
        next_before_cursor: str | None = None
        for message in messages:
            role = _sender_to_role(getattr(message, "sender", ""))
            raw_blocks = (
                blocks_by_message_id.get(message.id, [])
                if isinstance(message.id, UUID)
                else []
            )
            status = (
                normalize_non_empty_text(getattr(message, "status", None)) or "done"
            )
            items.append(
                {
                    "id": str(message.id),
                    "role": role,
                    "created_at": message.created_at,
                    "status": status,
                    "blocks": _render_blocks(raw_blocks),
                }
            )

        if has_more_before and items:
            oldest = items[0]
            role_priority = _sender_priority_for_role(str(oldest.get("role") or ""))
            try:
                oldest_created_at = ensure_utc(oldest["created_at"])
                oldest_id = UUID(str(oldest["id"]))
                next_before_cursor = _encode_messages_before_cursor(
                    created_at=oldest_created_at,
                    sender_priority=role_priority,
                    message_id=oldest_id,
                )
            except (TypeError, ValueError):
                next_before_cursor = None

        page_info = {
            "hasMoreBefore": has_more_before,
            "nextBefore": next_before_cursor,
        }
        return items, {"pageInfo": page_info}, False

    async def list_message_blocks(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: str,
        block_ids: list[UUID],
    ) -> tuple[list[dict[str, Any]], bool]:
        resolved_conversation_id = _parse_conversation_id(conversation_id)
        ordered_ids = _dedupe_uuid_list_keep_order(block_ids)
        if not ordered_ids:
            return [], False

        stmt = (
            select(AgentMessageBlock)
            .join(AgentMessage, AgentMessage.id == AgentMessageBlock.message_id)
            .where(
                and_(
                    AgentMessageBlock.user_id == user_id,
                    AgentMessage.user_id == user_id,
                    AgentMessage.conversation_id == resolved_conversation_id,
                    AgentMessageBlock.id.in_(ordered_ids),
                )
            )
        )
        blocks = list((await db.scalars(stmt)).all())
        by_id = {
            block.id: block
            for block in blocks
            if isinstance(block.id, UUID) and isinstance(block.message_id, UUID)
        }
        if any(block_id not in by_id for block_id in ordered_ids):
            raise ValueError("block_not_found")

        items = [_render_block_detail_item(by_id[block_id]) for block_id in ordered_ids]
        return items, False

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

    @staticmethod
    def _inflight_key(*, user_id: UUID, conversation_id: UUID) -> tuple[str, str]:
        return (str(user_id), str(conversation_id))

    @staticmethod
    def _copy_inflight_entry(entry: _InflightInvokeEntry) -> _InflightInvokeEntry:
        return _InflightInvokeEntry(
            token=entry.token,
            task_id=entry.task_id,
            gateway=entry.gateway,
            resolved=entry.resolved,
            cancel_requested=entry.cancel_requested,
            cancel_reason=entry.cancel_reason,
        )

    async def register_inflight_invoke(
        self,
        *,
        user_id: UUID,
        conversation_id: UUID,
        gateway: Any,
        resolved: Any,
    ) -> str:
        token = str(uuid4())
        key = self._inflight_key(user_id=user_id, conversation_id=conversation_id)
        async with _inflight_invokes_lock:
            bucket = _inflight_invokes.setdefault(key, {})
            bucket[token] = _InflightInvokeEntry(
                token=token,
                task_id=None,
                gateway=gateway,
                resolved=resolved,
            )
        return token

    async def bind_inflight_task_id(
        self,
        *,
        user_id: UUID,
        conversation_id: UUID,
        token: str,
        task_id: str,
    ) -> bool:
        normalized_task_id = normalize_non_empty_text(task_id)
        if not normalized_task_id:
            return False
        key = self._inflight_key(user_id=user_id, conversation_id=conversation_id)
        pending_cancel_snapshot: _InflightInvokeEntry | None = None
        async with _inflight_invokes_lock:
            bucket = _inflight_invokes.get(key)
            current = bucket.get(token) if bucket is not None else None
            if current is None or current.token != token:
                return False
            current.task_id = normalized_task_id
            if current.cancel_requested:
                pending_cancel_snapshot = self._copy_inflight_entry(current)
        if pending_cancel_snapshot is not None:
            try:
                success, error_code = await self._cancel_inflight_task(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    snapshot=pending_cancel_snapshot,
                    reason=pending_cancel_snapshot.cancel_reason or "hub_user_cancel",
                )
                if not success:
                    logger.warning(
                        "Deferred inflight cancellation failed after task binding",
                        extra={
                            "user_id": str(user_id),
                            "conversation_id": str(conversation_id),
                            "token": pending_cancel_snapshot.token,
                            "task_id": pending_cancel_snapshot.task_id,
                            "error_code": error_code,
                        },
                    )
            except Exception:
                # Bind path must not interrupt streaming event handling.
                logger.warning(
                    "Deferred inflight cancellation raised after task binding",
                    exc_info=True,
                    extra={
                        "user_id": str(user_id),
                        "conversation_id": str(conversation_id),
                        "token": pending_cancel_snapshot.token,
                        "task_id": pending_cancel_snapshot.task_id,
                    },
                )
        return True

    async def unregister_inflight_invoke(
        self,
        *,
        user_id: UUID,
        conversation_id: UUID,
        token: str,
    ) -> bool:
        key = self._inflight_key(user_id=user_id, conversation_id=conversation_id)
        async with _inflight_invokes_lock:
            bucket = _inflight_invokes.get(key)
            if not bucket or token not in bucket:
                return False
            bucket.pop(token, None)
            if not bucket:
                _inflight_invokes.pop(key, None)
            return True

    async def _list_inflight_invoke_snapshots(
        self,
        *,
        user_id: UUID,
        conversation_id: UUID,
    ) -> list[_InflightInvokeEntry]:
        key = self._inflight_key(user_id=user_id, conversation_id=conversation_id)
        async with _inflight_invokes_lock:
            bucket = _inflight_invokes.get(key) or {}
            return [self._copy_inflight_entry(entry) for entry in bucket.values()]

    async def _mark_inflight_cancel_requested(
        self,
        *,
        user_id: UUID,
        conversation_id: UUID,
        token: str,
        reason: str,
    ) -> _InflightInvokeEntry | None:
        normalized_reason = normalize_non_empty_text(reason) or "hub_user_cancel"
        key = self._inflight_key(user_id=user_id, conversation_id=conversation_id)
        async with _inflight_invokes_lock:
            bucket = _inflight_invokes.get(key)
            current = bucket.get(token) if bucket is not None else None
            if current is None:
                return None
            current.cancel_requested = True
            current.cancel_reason = normalized_reason
            return self._copy_inflight_entry(current)

    async def _cancel_inflight_task(
        self,
        *,
        user_id: UUID,
        conversation_id: UUID,
        snapshot: _InflightInvokeEntry,
        reason: str,
    ) -> tuple[bool, str | None]:
        if (
            not snapshot.task_id
            or snapshot.gateway is None
            or snapshot.resolved is None
        ):
            return False, None
        normalized_reason = normalize_non_empty_text(reason) or "hub_user_cancel"
        cancel_result = await snapshot.gateway.cancel_task(
            resolved=snapshot.resolved,
            task_id=snapshot.task_id,
            metadata={"source": normalized_reason},
        )
        success = bool(cancel_result.get("success"))
        error_code = normalize_non_empty_text(
            str(cancel_result.get("error_code") or "")
        )
        if success or error_code in _INFLIGHT_CANCEL_TERMINAL_ERROR_CODES:
            await self.unregister_inflight_invoke(
                user_id=user_id,
                conversation_id=conversation_id,
                token=snapshot.token,
            )
            return True, error_code or None
        return False, error_code or None

    async def preempt_inflight_invoke(
        self,
        *,
        user_id: UUID,
        conversation_id: UUID,
        reason: str,
    ) -> bool:
        snapshots = await self._list_inflight_invoke_snapshots(
            user_id=user_id,
            conversation_id=conversation_id,
        )
        if not snapshots:
            return False

        preempted = False
        for snapshot in snapshots:
            if snapshot.task_id is None:
                marked = await self._mark_inflight_cancel_requested(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    token=snapshot.token,
                    reason=reason,
                )
                if marked is not None:
                    preempted = True
                continue

            success, _ = await self._cancel_inflight_task(
                user_id=user_id,
                conversation_id=conversation_id,
                snapshot=snapshot,
                reason=reason,
            )
            if not success:
                raise ValueError("invoke_interrupt_failed")
            preempted = True
        return preempted

    async def cancel_session(
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
        if target is None:
            raise ValueError("session_not_found")

        snapshots = await self._list_inflight_invoke_snapshots(
            user_id=user_id,
            conversation_id=resolved_conversation_id,
        )
        if not snapshots:
            return (
                {
                    "conversationId": str(resolved_conversation_id),
                    "taskId": None,
                    "cancelled": False,
                    "status": "no_inflight",
                },
                False,
            )

        accepted_task_id: str | None = None
        pending_requested = False
        terminal_task_id: str | None = None
        for snapshot in snapshots:
            if snapshot.task_id is None:
                marked = await self._mark_inflight_cancel_requested(
                    user_id=user_id,
                    conversation_id=resolved_conversation_id,
                    token=snapshot.token,
                    reason="hub_user_cancel",
                )
                if marked is not None:
                    pending_requested = True
                continue

            success, error_code = await self._cancel_inflight_task(
                user_id=user_id,
                conversation_id=resolved_conversation_id,
                snapshot=snapshot,
                reason="hub_user_cancel",
            )
            if success and error_code not in _INFLIGHT_CANCEL_TERMINAL_ERROR_CODES:
                if accepted_task_id is None:
                    accepted_task_id = snapshot.task_id
                continue
            if success and error_code in _INFLIGHT_CANCEL_TERMINAL_ERROR_CODES:
                if terminal_task_id is None:
                    terminal_task_id = snapshot.task_id
                continue

            if error_code in {"timeout", "agent_unavailable"}:
                raise ValueError("upstream_unreachable")
            if error_code in {
                "upstream_http_error",
                "outbound_not_allowed",
                "client_reset",
            }:
                raise ValueError("upstream_http_error")
            raise ValueError("upstream_error")

        if accepted_task_id is not None:
            return (
                {
                    "conversationId": str(resolved_conversation_id),
                    "taskId": accepted_task_id,
                    "cancelled": True,
                    "status": "accepted",
                },
                False,
            )

        if pending_requested:
            return (
                {
                    "conversationId": str(resolved_conversation_id),
                    "taskId": None,
                    "cancelled": True,
                    "status": "pending",
                },
                False,
            )

        if terminal_task_id is not None:
            return (
                {
                    "conversationId": str(resolved_conversation_id),
                    "taskId": terminal_task_id,
                    "cancelled": False,
                    "status": "already_terminal",
                },
                False,
            )

        return (
            {
                "conversationId": str(resolved_conversation_id),
                "taskId": None,
                "cancelled": False,
                "status": "no_inflight",
            },
            False,
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


def _encode_messages_before_cursor(
    *,
    created_at: datetime,
    sender_priority: int,
    message_id: UUID,
) -> str:
    payload = {
        "created_at": ensure_utc(created_at).isoformat(),
        "sender_priority": 0 if sender_priority <= 0 else 1,
        "message_id": str(message_id),
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("utf-8")
    return encoded.rstrip("=")


def _parse_messages_before_cursor(raw: str) -> MessagesBeforeCursor:
    trimmed = (raw or "").strip()
    if not trimmed:
        raise ValueError("invalid_before_cursor")
    padding = "=" * (-len(trimmed) % 4)
    try:
        decoded = base64.urlsafe_b64decode(f"{trimmed}{padding}".encode("utf-8"))
        payload = json.loads(decoded.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid_before_cursor") from exc

    if not isinstance(payload, dict):
        raise ValueError("invalid_before_cursor")
    created_at_raw = payload.get("created_at")
    sender_priority_raw = payload.get("sender_priority")
    message_id_raw = payload.get("message_id")
    if not isinstance(created_at_raw, str) or not isinstance(message_id_raw, str):
        raise ValueError("invalid_before_cursor")
    try:
        created_at = ensure_utc(
            datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
        )
        message_id = UUID(message_id_raw)
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid_before_cursor") from exc

    try:
        sender_priority = int(sender_priority_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid_before_cursor") from exc
    if sender_priority not in {0, 1}:
        raise ValueError("invalid_before_cursor")
    return MessagesBeforeCursor(
        created_at=created_at,
        sender_priority=sender_priority,
        message_id=message_id,
    )


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


def _sender_priority_for_role(role: str) -> int:
    return 0 if role == "user" else 1


def _derive_session_title_from_query(query: str) -> str | None:
    trimmed_query = query.strip() if isinstance(query, str) else ""
    if not trimmed_query:
        return None
    return trimmed_query[: ConversationThread.TITLE_MAX_LENGTH]


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
) -> dict[str, Any]:
    raw_content = block.content if isinstance(block.content, str) else ""
    block_type = _normalize_block_type(block.block_type)
    if block_type in {"reasoning", "tool_call"}:
        raw_content = ""
    return {
        "id": str(block.id),
        "type": block_type,
        "content": raw_content,
        "isFinished": bool(block.is_finished),
    }


def _render_blocks(blocks: list[AgentMessageBlock]) -> list[dict[str, Any]]:
    return [_render_block_item(block) for block in blocks]


def _render_block_detail_item(
    block: AgentMessageBlock,
) -> dict[str, Any]:
    raw_content = block.content if isinstance(block.content, str) else ""
    return {
        "id": str(block.id),
        "messageId": str(block.message_id),
        "type": _normalize_block_type(block.block_type),
        "content": raw_content,
        "isFinished": bool(block.is_finished),
    }


def _dedupe_uuid_list_keep_order(values: list[UUID]) -> list[UUID]:
    deduped: list[UUID] = []
    seen: set[UUID] = set()
    for value in values:
        if not isinstance(value, UUID):
            continue
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


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
