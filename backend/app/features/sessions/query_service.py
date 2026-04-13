"""Query-side services for the unified session domain."""

from __future__ import annotations

from typing import Any, Literal, cast
from uuid import UUID

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_message import AgentMessage
from app.db.models.agent_message_block import AgentMessageBlock
from app.db.models.conversation_thread import ConversationThread
from app.features.invoke.shared_metadata import merge_preferred_session_binding_metadata
from app.features.self_management_shared.constants import (
    SELF_MANAGEMENT_BUILT_IN_AGENT_PUBLIC_ID,
)
from app.features.sessions import block_store
from app.features.sessions.common import (
    MessagesBeforeCursor,
    ResolvedConversationTarget,
    SessionSource,
    build_continue_response,
    dedupe_uuid_list_keep_order,
    encode_messages_before_cursor,
    parse_conversation_id,
    parse_messages_before_cursor,
    project_message_blocks,
    render_block_detail_item,
    resolve_session_source,
    sender_priority_for_role,
    sender_to_role,
)
from app.features.sessions.identity import conversation_identity_service
from app.features.sessions.support import SessionHubSupport
from app.features.working_directory import extract_working_directory
from app.utils.session_identity import normalize_non_empty_text, normalize_provider
from app.utils.timezone_util import ensure_utc


class SessionQueryService:
    """Read-model queries and continue-session resolution."""

    def __init__(self, *, support: SessionHubSupport) -> None:
        self._support = support

    def _serialize_thread_summary(self, thread: ConversationThread) -> dict[str, Any]:
        thread_source = cast(str | None, thread.source)
        thread_title_raw = cast(str, thread.title)
        thread_external_provider = cast(str | None, thread.external_provider)
        thread_external_session_id = cast(str | None, thread.external_session_id)
        thread_agent_id = cast(UUID | None, thread.agent_id)
        thread_agent_source = cast(str | None, thread.agent_source)
        resolved_source = resolve_session_source(
            thread_source=thread_source,
            fallback_source=None,
        )
        title_fallback = (
            "Scheduled Session" if resolved_source == "scheduled" else "Manual Session"
        )
        thread_title = thread_title_raw if thread_title_raw else title_fallback
        if ConversationThread.is_placeholder_title(thread_title):
            thread_title = "Session" if resolved_source == "manual" else title_fallback
        serialized_agent_id: str | None = (
            str(thread_agent_id) if thread_agent_id is not None else None
        )
        serialized_agent_source = thread_agent_source or "personal"
        if thread_agent_source == "builtin":
            serialized_agent_id = SELF_MANAGEMENT_BUILT_IN_AGENT_PUBLIC_ID
            serialized_agent_source = "builtin"
        return {
            "conversationId": str(thread.id),
            "source": resolved_source,
            "external_provider": normalize_provider(thread_external_provider),
            "external_session_id": normalize_non_empty_text(thread_external_session_id),
            "agent_id": serialized_agent_id,
            "agent_source": serialized_agent_source,
            "title": thread_title,
            "last_active_at": thread.last_active_at,
            "created_at": thread.created_at,
        }

    def _serialize_message_item(
        self,
        *,
        message: AgentMessage,
        blocks_by_message_id: dict[UUID, list[AgentMessageBlock]],
    ) -> dict[str, Any]:
        message_id = cast(UUID, message.id)
        role = sender_to_role(getattr(message, "sender", ""))
        raw_blocks: list[AgentMessageBlock] = blocks_by_message_id.get(message_id, [])
        status = normalize_non_empty_text(getattr(message, "status", None)) or "done"
        rendered_blocks, content = project_message_blocks(
            raw_blocks,
            message_status=status,
        )
        return {
            "id": str(message_id),
            "role": role,
            "content": content,
            "created_at": message.created_at,
            "status": status,
            "blocks": rendered_blocks,
        }

    async def _resolve_working_directory(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: UUID,
    ) -> str | None:
        stmt = (
            select(AgentMessage.message_metadata)
            .where(
                and_(
                    AgentMessage.user_id == user_id,
                    AgentMessage.conversation_id == conversation_id,
                )
            )
            .order_by(AgentMessage.created_at.desc(), AgentMessage.id.desc())
            .limit(20)
        )
        for raw_metadata in (await db.execute(stmt)).scalars().all():
            if isinstance(raw_metadata, dict):
                resolved = extract_working_directory(raw_metadata)
                if resolved:
                    return resolved
        return None

    async def list_sessions(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        page: int,
        size: int,
        source: SessionSource | None,
        agent_id: UUID | None,
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
        source: SessionSource | None,
        agent_id: UUID | None,
        limit: int | None = None,
        offset: int | None = None,
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
            filters.append(ConversationThread.source == source)
        if agent_id:
            filters.append(ConversationThread.agent_id == agent_id)

        count_stmt = (
            select(func.count()).select_from(ConversationThread).where(and_(*filters))
        )
        total = (await db.execute(count_stmt)).scalar() or 0

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
        items = [self._serialize_thread_summary(thread) for thread in threads]

        return items, total

    async def get_session(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: str,
    ) -> tuple[dict[str, Any], bool]:
        resolved_conversation_id = parse_conversation_id(conversation_id)
        thread = await self._support.get_local_session_by_id(
            db,
            user_id=user_id,
            local_session_id=resolved_conversation_id,
        )
        if thread is None:
            raise ValueError("session_not_found")
        return self._serialize_thread_summary(thread), False

    async def list_messages(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: str,
        before: str | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any], bool]:
        resolved_conversation_id = parse_conversation_id(conversation_id)

        cursor: MessagesBeforeCursor | None = (
            parse_messages_before_cursor(before) if before else None
        )
        sender_priority = case(
            (AgentMessage.sender.in_(["user", "automation"]), 0),
            else_=1,
        )
        interrupt_phase = AgentMessage.message_metadata.op("->")("interrupt").op("->>")(
            "phase"
        )
        stmt = select(AgentMessage).where(
            and_(
                AgentMessage.user_id == user_id,
                AgentMessage.conversation_id == resolved_conversation_id,
                or_(
                    AgentMessage.sender != "system",
                    interrupt_phase.is_(None),
                    interrupt_phase.not_in(("asked", "resolved")),
                ),
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

        message_ids = [cast(UUID, message.id) for message in messages]
        blocks_by_message_id: dict[UUID, list[AgentMessageBlock]] = {}
        if message_ids:
            blocks = await block_store.list_blocks_by_message_ids(
                db,
                user_id=user_id,
                message_ids=message_ids,
            )
            for block in blocks:
                block_message_id = cast(UUID, block.message_id)
                blocks_by_message_id.setdefault(block_message_id, []).append(block)

        items: list[dict[str, Any]] = []
        next_before_cursor: str | None = None
        for message in messages:
            items.append(
                self._serialize_message_item(
                    message=message,
                    blocks_by_message_id=blocks_by_message_id,
                )
            )

        if has_more_before and items:
            oldest = items[0]
            role_priority = sender_priority_for_role(str(oldest.get("role") or ""))
            try:
                oldest_created_at = ensure_utc(oldest["created_at"])
                oldest_id = UUID(str(oldest["id"]))
                next_before_cursor = encode_messages_before_cursor(
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

    async def get_message_items(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: str,
        message_ids: list[UUID],
    ) -> tuple[list[dict[str, Any]], bool]:
        resolved_conversation_id = parse_conversation_id(conversation_id)
        ordered_ids = dedupe_uuid_list_keep_order(message_ids)
        if not ordered_ids:
            return [], False

        stmt = select(AgentMessage).where(
            and_(
                AgentMessage.user_id == user_id,
                AgentMessage.conversation_id == resolved_conversation_id,
                AgentMessage.id.in_(ordered_ids),
            )
        )
        messages = list((await db.scalars(stmt)).all())
        messages_by_id = {cast(UUID, message.id): message for message in messages}
        if any(message_id not in messages_by_id for message_id in ordered_ids):
            raise ValueError("message_not_found")

        blocks = await block_store.list_blocks_by_message_ids(
            db,
            user_id=user_id,
            message_ids=ordered_ids,
        )
        blocks_by_message_id: dict[UUID, list[AgentMessageBlock]] = {}
        for block in blocks:
            block_message_id = cast(UUID, block.message_id)
            blocks_by_message_id.setdefault(block_message_id, []).append(block)

        items = [
            self._serialize_message_item(
                message=messages_by_id[message_id],
                blocks_by_message_id=blocks_by_message_id,
            )
            for message_id in ordered_ids
        ]
        return items, False

    async def list_message_blocks(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: str,
        block_ids: list[UUID],
    ) -> tuple[list[dict[str, Any]], bool]:
        resolved_conversation_id = parse_conversation_id(conversation_id)
        ordered_ids = dedupe_uuid_list_keep_order(block_ids)
        if not ordered_ids:
            return [], False

        stmt = (
            select(AgentMessageBlock, AgentMessage.status)
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
        rows = list((await db.execute(stmt)).all())
        by_id = {
            cast(UUID, block.id): (
                block,
                cast(str | None, status),
            )
            for block, status in rows
        }
        if any(block_id not in by_id for block_id in ordered_ids):
            raise ValueError("block_not_found")

        items = [
            render_block_detail_item(
                by_id[block_id][0],
                message_status=by_id[block_id][1],
            )
            for block_id in ordered_ids
        ]
        return items, False

    async def continue_session(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: str,
    ) -> tuple[dict[str, Any], bool]:
        resolved_conversation_id = parse_conversation_id(conversation_id)
        target: ResolvedConversationTarget | None = (
            await self._support.resolve_conversation_target(
                db,
                user_id=user_id,
                conversation_id=resolved_conversation_id,
            )
        )
        session = target.thread if target else None
        provider = normalize_provider(session.external_provider if session else None)
        external_session_id = normalize_non_empty_text(
            session.external_session_id if session else None
        )
        context_id = normalize_non_empty_text(session.context_id if session else None)
        working_directory = await self._resolve_working_directory(
            db,
            user_id=user_id,
            conversation_id=resolved_conversation_id,
        )

        if target is None:
            return (
                build_continue_response(
                    conversation_id=resolved_conversation_id,
                    source="manual",
                    metadata=merge_preferred_session_binding_metadata(
                        {"contextId": context_id} if context_id is not None else {},
                        provider=provider,
                        external_session_id=external_session_id,
                        include_legacy_root=True,
                    ),
                    working_directory=working_directory,
                ),
                False,
            )

        resolved_provider = provider
        resolved_external_session_id = external_session_id
        session_source = cast(str | None, session.source) if session else None
        session_agent_source = (
            cast(str | None, session.agent_source) if session else None
        )
        session_agent_id = cast(UUID | None, session.agent_id) if session else None
        session_title = cast(str, session.title) if session else "Session"

        resolved_source = resolve_session_source(
            thread_source=session_source,
            fallback_source=target.source,
        )
        resolved_conversation = resolved_conversation_id
        db_mutated = False
        if resolved_provider and resolved_external_session_id:
            resolved_agent_source: Literal["personal", "shared"] | None = None
            target_agent_source = cast(str | None, target.thread.agent_source)
            if target_agent_source in {"personal", "shared"}:
                resolved_agent_source = cast(
                    Literal["personal", "shared"], target_agent_source
                )
            elif session_agent_source in {"personal", "shared"}:
                resolved_agent_source = cast(
                    Literal["personal", "shared"], session_agent_source
                )
            bind_result = (
                await conversation_identity_service.bind_external_session_with_state(
                    db,
                    user_id=user_id,
                    conversation_id=resolved_conversation,
                    source=resolved_source,
                    provider=resolved_provider,
                    external_session_id=resolved_external_session_id,
                    agent_id=(
                        cast(UUID | None, target.thread.agent_id) or session_agent_id
                    ),
                    agent_source=resolved_agent_source,
                    context_id=context_id,
                    title=session_title or "Session",
                )
            )
            resolved_conversation = bind_result.conversation_id
            db_mutated = bind_result.mutated
        return (
            build_continue_response(
                conversation_id=resolved_conversation or resolved_conversation_id,
                source=resolved_source,
                metadata=merge_preferred_session_binding_metadata(
                    {"contextId": context_id} if context_id is not None else {},
                    provider=resolved_provider,
                    external_session_id=resolved_external_session_id,
                    include_legacy_root=True,
                ),
                working_directory=working_directory,
            ),
            db_mutated,
        )
