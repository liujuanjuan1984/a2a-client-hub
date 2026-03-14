"""Query-side services for the unified session domain."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_message import AgentMessage
from app.db.models.agent_message_block import AgentMessageBlock
from app.db.models.conversation_thread import ConversationThread
from app.handlers import agent_message_block as agent_message_block_handler
from app.services.a2a_shared_metadata import merge_preferred_session_binding_metadata
from app.services.conversation_identity import conversation_identity_service
from app.services.session_hub_common import (
    MessagesBeforeCursor,
    ResolvedConversationTarget,
    SessionSource,
    build_continue_response,
    dedupe_uuid_list_keep_order,
    encode_messages_before_cursor,
    parse_conversation_id,
    parse_messages_before_cursor,
    render_block_detail_item,
    render_blocks,
    resolve_session_source,
    sender_priority_for_role,
    sender_to_role,
)
from app.services.session_hub_support import SessionHubSupport
from app.utils.session_identity import normalize_non_empty_text, normalize_provider
from app.utils.timezone_util import ensure_utc


class SessionQueryService:
    """Read-model queries and continue-session resolution."""

    def __init__(self, *, support: SessionHubSupport) -> None:
        self._support = support

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
        items: list[dict[str, Any]] = []

        for thread in threads:
            resolved_source = resolve_session_source(
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
        resolved_conversation_id = parse_conversation_id(conversation_id)

        cursor: MessagesBeforeCursor | None = (
            parse_messages_before_cursor(before) if before else None
        )
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
            role = sender_to_role(getattr(message, "sender", ""))
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
                    "blocks": render_blocks(raw_blocks),
                }
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

        items = [render_block_detail_item(by_id[block_id]) for block_id in ordered_ids]
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
                ),
                False,
            )

        resolved_provider = provider
        resolved_external_session_id = external_session_id

        resolved_source = resolve_session_source(
            thread_source=session.source if session else None,
            fallback_source=target.source,
        )
        resolved_conversation = resolved_conversation_id
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
                    conversation_id=resolved_conversation,
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
            ),
            db_mutated,
        )
