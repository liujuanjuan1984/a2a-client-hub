"""Shared self-management session services for self-owned conversation threads."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation_thread import ConversationThread
from app.db.models.user import User
from app.db.transaction import commit_safely
from app.features.self_management_shared.capability_catalog import (
    SELF_SESSIONS_ARCHIVE,
    SELF_SESSIONS_GET,
    SELF_SESSIONS_LIST,
    SELF_SESSIONS_UNARCHIVE,
    SELF_SESSIONS_UPDATE,
)
from app.features.self_management_shared.tool_gateway import SelfManagementToolGateway
from app.features.sessions.common import SessionSource
from app.utils.timezone_util import utc_now


class SelfManagementSessionsService:
    """Shared session operations for REST, CLI, and built-in agent entry points."""

    def _user_id(self, user: User) -> UUID:
        user_id = cast(UUID | None, user.id)
        if user_id is None:
            raise ValueError("Authenticated user id is required")
        return user_id

    @staticmethod
    def _serialize_thread_summary(thread: ConversationThread) -> dict[str, Any]:
        thread_source = cast(str | None, thread.source)
        resolved_source = "scheduled" if thread_source == "scheduled" else "manual"
        title_fallback = (
            "Scheduled Session" if resolved_source == "scheduled" else "Manual Session"
        )
        raw_title = cast(str, thread.title)
        title = raw_title if raw_title else title_fallback
        if ConversationThread.is_placeholder_title(title):
            title = "Session" if resolved_source == "manual" else title_fallback
        return {
            "conversationId": str(cast(UUID, thread.id)),
            "source": resolved_source,
            "external_provider": cast(str | None, thread.external_provider),
            "external_session_id": cast(str | None, thread.external_session_id),
            "agent_id": (
                str(cast(UUID, thread.agent_id))
                if cast(UUID | None, thread.agent_id) is not None
                else None
            ),
            "agent_source": cast(str | None, thread.agent_source) or "personal",
            "title": title,
            "status": cast(str, thread.status),
            "last_active_at": thread.last_active_at,
            "created_at": thread.created_at,
        }

    @staticmethod
    def _resolve_status_filter(status: str) -> tuple[str, ...]:
        if status == "all":
            return (
                ConversationThread.STATUS_ACTIVE,
                ConversationThread.STATUS_ARCHIVED,
            )
        if status == "archived":
            return (ConversationThread.STATUS_ARCHIVED,)
        return (ConversationThread.STATUS_ACTIVE,)

    async def _get_thread(
        self,
        *,
        db: AsyncSession,
        user_id: UUID,
        conversation_id: UUID,
        allowed_statuses: tuple[str, ...],
        for_update: bool = False,
    ) -> ConversationThread:
        stmt = select(ConversationThread).where(
            and_(
                ConversationThread.id == conversation_id,
                ConversationThread.user_id == user_id,
                ConversationThread.status.in_(allowed_statuses),
                ConversationThread.source.in_(
                    [
                        ConversationThread.SOURCE_MANUAL,
                        ConversationThread.SOURCE_SCHEDULED,
                    ]
                ),
            )
        )
        if for_update:
            stmt = stmt.with_for_update()
        thread = cast(ConversationThread | None, await db.scalar(stmt.limit(1)))
        if thread is None:
            raise ValueError("session_not_found")
        return thread

    async def list_sessions(
        self,
        *,
        db: AsyncSession,
        gateway: SelfManagementToolGateway,
        current_user: User,
        page: int,
        size: int,
        source: SessionSource | None = None,
        status: str = "active",
        agent_id: UUID | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any], bool]:
        allowed_statuses = self._resolve_status_filter(status)

        result = await gateway.execute(
            operation=SELF_SESSIONS_LIST,
            handler=lambda: self._list_sessions_query(
                db=db,
                user_id=self._user_id(current_user),
                page=page,
                size=size,
                source=source,
                status_filter=allowed_statuses,
                agent_id=agent_id,
            ),
        )
        return result.result

    async def get_session(
        self,
        *,
        db: AsyncSession,
        gateway: SelfManagementToolGateway,
        current_user: User,
        conversation_id: str,
    ) -> dict[str, Any]:
        resolved_conversation_id = UUID(conversation_id)
        result = await gateway.execute(
            operation=SELF_SESSIONS_GET,
            resource_id=conversation_id,
            handler=lambda: self._get_thread_query(
                db=db,
                user_id=self._user_id(current_user),
                conversation_id=resolved_conversation_id,
                allowed_statuses=(
                    ConversationThread.STATUS_ACTIVE,
                    ConversationThread.STATUS_ARCHIVED,
                ),
            ),
        )
        return result.result

    async def update_session(
        self,
        *,
        db: AsyncSession,
        gateway: SelfManagementToolGateway,
        current_user: User,
        conversation_id: str,
        title: str,
    ) -> dict[str, Any]:
        resolved_conversation_id = UUID(conversation_id)
        result = await gateway.execute(
            operation=SELF_SESSIONS_UPDATE,
            resource_id=conversation_id,
            handler=lambda: self._update_thread(
                db=db,
                user_id=self._user_id(current_user),
                conversation_id=resolved_conversation_id,
                title=title,
            ),
        )
        return result.result

    async def archive_session(
        self,
        *,
        db: AsyncSession,
        gateway: SelfManagementToolGateway,
        current_user: User,
        conversation_id: str,
    ) -> dict[str, Any]:
        resolved_conversation_id = UUID(conversation_id)
        result = await gateway.execute(
            operation=SELF_SESSIONS_ARCHIVE,
            resource_id=conversation_id,
            handler=lambda: self._set_thread_status(
                db=db,
                user_id=self._user_id(current_user),
                conversation_id=resolved_conversation_id,
                from_status=ConversationThread.STATUS_ACTIVE,
                to_status=ConversationThread.STATUS_ARCHIVED,
            ),
        )
        return result.result

    async def unarchive_session(
        self,
        *,
        db: AsyncSession,
        gateway: SelfManagementToolGateway,
        current_user: User,
        conversation_id: str,
    ) -> dict[str, Any]:
        resolved_conversation_id = UUID(conversation_id)
        result = await gateway.execute(
            operation=SELF_SESSIONS_UNARCHIVE,
            resource_id=conversation_id,
            handler=lambda: self._set_thread_status(
                db=db,
                user_id=self._user_id(current_user),
                conversation_id=resolved_conversation_id,
                from_status=ConversationThread.STATUS_ARCHIVED,
                to_status=ConversationThread.STATUS_ACTIVE,
            ),
        )
        return result.result

    async def _list_sessions_query(
        self,
        *,
        db: AsyncSession,
        user_id: UUID,
        page: int,
        size: int,
        source: SessionSource | None,
        status_filter: tuple[str, ...],
        agent_id: UUID | None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any], bool]:
        offset = (page - 1) * size if page > 0 else 0
        filters: list[Any] = [
            ConversationThread.user_id == user_id,
            ConversationThread.status.in_(status_filter),
            ConversationThread.source.in_(
                [
                    ConversationThread.SOURCE_MANUAL,
                    ConversationThread.SOURCE_SCHEDULED,
                ]
            ),
        ]
        if source is not None:
            filters.append(ConversationThread.source == source)
        if agent_id is not None:
            filters.append(ConversationThread.agent_id == agent_id)

        total = int(
            cast(
                int | None,
                await db.scalar(
                    select(func.count())
                    .select_from(ConversationThread)
                    .where(and_(*filters))
                ),
            )
            or 0
        )
        stmt = (
            select(ConversationThread)
            .where(and_(*filters))
            .order_by(
                ConversationThread.last_active_at.desc(),
                ConversationThread.created_at.desc(),
            )
            .offset(offset)
            .limit(size)
        )
        threads = list((await db.execute(stmt)).scalars().all())
        pages = (total + size - 1) // size if size else 0
        return (
            [self._serialize_thread_summary(thread) for thread in threads],
            {
                "pagination": {
                    "page": page,
                    "size": size,
                    "total": total,
                    "pages": pages,
                }
            },
            False,
        )

    async def _get_thread_query(
        self,
        *,
        db: AsyncSession,
        user_id: UUID,
        conversation_id: UUID,
        allowed_statuses: tuple[str, ...],
    ) -> dict[str, Any]:
        thread = await self._get_thread(
            db=db,
            user_id=user_id,
            conversation_id=conversation_id,
            allowed_statuses=allowed_statuses,
        )
        return self._serialize_thread_summary(thread)

    async def _update_thread(
        self,
        *,
        db: AsyncSession,
        user_id: UUID,
        conversation_id: UUID,
        title: str,
    ) -> dict[str, Any]:
        thread = await self._get_thread(
            db=db,
            user_id=user_id,
            conversation_id=conversation_id,
            allowed_statuses=(
                ConversationThread.STATUS_ACTIVE,
                ConversationThread.STATUS_ARCHIVED,
            ),
            for_update=True,
        )
        setattr(thread, "title", ConversationThread.normalize_title(title))
        await commit_safely(db)
        await db.refresh(thread)
        return self._serialize_thread_summary(thread)

    async def _set_thread_status(
        self,
        *,
        db: AsyncSession,
        user_id: UUID,
        conversation_id: UUID,
        from_status: str,
        to_status: str,
    ) -> dict[str, Any]:
        thread = await self._get_thread(
            db=db,
            user_id=user_id,
            conversation_id=conversation_id,
            allowed_statuses=(from_status,),
            for_update=True,
        )
        setattr(thread, "status", to_status)
        setattr(thread, "last_active_at", utc_now())
        await commit_safely(db)
        await db.refresh(thread)
        return self._serialize_thread_summary(thread)


self_management_sessions_service = SelfManagementSessionsService()


__all__ = [
    "SelfManagementSessionsService",
    "self_management_sessions_service",
]
