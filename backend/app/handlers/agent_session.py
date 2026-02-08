"""Async implementations for session handler operations."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cardbox.service import cardbox_service
from app.core.logging import get_logger, log_exception
from app.db.models.agent_session import AgentSession
from app.db.transaction import commit_safely, rollback_safely
from app.handlers import agent_message as agent_message_handler
from app.utils.timezone_util import utc_now

if TYPE_CHECKING:
    from app.cardbox.data_sync import CardBoxDataSyncService

logger = get_logger(__name__)


class SessionHandlerError(Exception):
    """Base exception for session handler errors."""


async def create_session(
    db: AsyncSession,
    *,
    user_id: UUID,
    name: str,
    sync_cardbox: bool = False,
    module_key: Optional[str] = None,
    session_type: Optional[str] = None,
) -> AgentSession:
    """Create a new session asynchronously."""
    session_type = session_type or AgentSession.TYPE_CHAT
    now = utc_now()

    session = AgentSession(
        id=uuid4(),
        user_id=user_id,
        name=name,
        last_activity_at=now,
        module_key=module_key,
        session_type=session_type,
    )
    db.add(session)

    try:
        await db.flush()
        cardbox_service.ensure_session_box(session)
        if sync_cardbox:
            try:
                await db.run_sync(
                    lambda sync_db: cardbox_data_sync_service.sync_all(
                        sync_db, user_id=user_id
                    )
                )
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.warning(
                    "Cardbox data sync skipped during async session creation: %s",
                    exc,
                    exc_info=True,
                )

        logger.info(
            "Created new async session %s for user %s cardbox=%s",
            session.id,
            user_id,
            session.cardbox_name,
        )
        await commit_safely(db)
        await db.refresh(session)
        return session
    except Exception as exc:
        await rollback_safely(db)
        log_exception(
            logger, f"Error creating session asynchronously: {exc}", sys.exc_info()
        )
        raise SessionHandlerError(f"Failed to create session: {exc}") from exc


async def soft_delete_sessions_for_user(
    db: AsyncSession,
    *,
    user_id: UUID,
) -> int:
    """Soft delete all active sessions for the given user."""

    sessions = await list_active_sessions(db, user_id=user_id)
    for session in sessions:
        session.soft_delete()

    await db.flush()
    return len(sessions)


async def create_session_with_id(
    db: AsyncSession,
    *,
    user_id: UUID,
    session_id: UUID,
    name: str,
    sync_cardbox: bool = False,
    module_key: Optional[str] = None,
    description: Optional[str] = None,
    session_type: Optional[str] = None,
) -> AgentSession:
    """Create a session with explicit id asynchronously."""
    session_type = session_type or AgentSession.TYPE_CHAT
    now = utc_now()

    session = AgentSession(
        id=session_id,
        user_id=user_id,
        name=name,
        last_activity_at=now,
        module_key=module_key,
        description=description,
        session_type=session_type,
    )
    db.add(session)

    try:
        await db.flush()
        cardbox_service.ensure_session_box(session)
        if sync_cardbox:
            try:
                await db.run_sync(
                    lambda sync_db: cardbox_data_sync_service.sync_all(
                        sync_db, user_id=user_id
                    )
                )
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.warning(
                    "Cardbox data sync skipped during async session creation: %s",
                    exc,
                    exc_info=True,
                )

        logger.info(
            "Created async session with ID %s for user %s cardbox=%s",
            session_id,
            user_id,
            session.cardbox_name,
        )
        await commit_safely(db)
        await db.refresh(session)
        return session
    except Exception as exc:
        await rollback_safely(db)
        log_exception(
            logger,
            f"Error creating session with ID asynchronously: {exc}",
            sys.exc_info(),
        )
        raise SessionHandlerError(f"Failed to create session with ID: {exc}") from exc


async def get_session(
    db: AsyncSession,
    *,
    session_id: UUID,
    user_id: UUID,
) -> Optional[AgentSession]:
    """Fetch a session for the given user."""
    stmt = (
        select(AgentSession)
        .where(
            AgentSession.id == session_id,
            AgentSession.user_id == user_id,
            AgentSession.deleted_at.is_(None),
        )
        .limit(1)
    )
    result = await db.execute(stmt)
    session = result.scalars().first()
    if session:
        cardbox_service.ensure_session_box(session)
    return session


def _build_user_sessions_query(*, user_id: UUID):
    return (
        select(AgentSession)
        .where(
            AgentSession.user_id == user_id,
            AgentSession.deleted_at.is_(None),
        )
        .order_by(
            AgentSession.last_activity_at.desc(),
            AgentSession.created_at.desc(),
        )
    )


async def _prepend_system_session(
    db: AsyncSession,
    *,
    user_id: UUID,
    sessions: List[AgentSession],
    limit: int,
    offset: int,
) -> List[AgentSession]:
    if offset > 0:
        return sessions

    stmt = (
        select(AgentSession)
        .where(
            AgentSession.user_id == user_id,
            AgentSession.session_type == AgentSession.TYPE_SYSTEM,
            AgentSession.deleted_at.is_(None),
        )
        .order_by(AgentSession.created_at.asc())
        .limit(1)
    )
    result = await db.execute(stmt)
    system_session = result.scalars().first()
    if not system_session:
        return sessions
    if any(session.id == system_session.id for session in sessions):
        return sessions

    cardbox_service.ensure_session_box(system_session)
    merged = [system_session, *sessions]
    if limit > 0 and len(merged) > limit:
        merged = merged[:limit]
    return merged


async def get_user_sessions(
    db: AsyncSession,
    *,
    user_id: UUID,
    limit: int = 20,
    offset: int = 0,
) -> List[AgentSession]:
    """Return paginated sessions with message counts."""

    try:
        stmt = _build_user_sessions_query(user_id=user_id).offset(offset).limit(limit)
        result = await db.execute(stmt)
        sessions = list(result.scalars().all())
        sessions = await _prepend_system_session(
            db,
            user_id=user_id,
            sessions=sessions,
            limit=limit,
            offset=offset,
        )

        for session in sessions:
            session.message_count = await agent_message_handler.count_agent_messages(
                db, user_id=user_id, session_id=session.id
            )

        return sessions
    except Exception as exc:
        log_exception(
            logger, f"Error getting user sessions asynchronously: {exc}", sys.exc_info()
        )
        raise SessionHandlerError(f"Failed to get user sessions: {exc}") from exc


async def get_user_sessions_with_total(
    db: AsyncSession,
    *,
    user_id: UUID,
    limit: int = 20,
    offset: int = 0,
) -> tuple[List[AgentSession], int]:
    try:
        base_stmt = _build_user_sessions_query(user_id=user_id)
        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        stmt = base_stmt.offset(offset).limit(limit)
        result = await db.execute(stmt)
        sessions = list(result.scalars().all())
        sessions = await _prepend_system_session(
            db,
            user_id=user_id,
            sessions=sessions,
            limit=limit,
            offset=offset,
        )

        for session in sessions:
            session.message_count = await agent_message_handler.count_agent_messages(
                db, user_id=user_id, session_id=session.id
            )

        total = await db.scalar(count_stmt)
        return sessions, int(total or 0)
    except Exception as exc:
        log_exception(
            logger,
            f"Error getting user sessions with total asynchronously: {exc}",
            sys.exc_info(),
        )
        raise SessionHandlerError(
            f"Failed to get user sessions with total: {exc}"
        ) from exc


async def list_active_sessions(
    db: AsyncSession,
    *,
    user_id: UUID,
) -> List[AgentSession]:
    """Return all active sessions for a user ordered by last activity."""

    stmt = (
        select(AgentSession)
        .where(
            AgentSession.user_id == user_id,
            AgentSession.deleted_at.is_(None),
        )
        .order_by(
            AgentSession.last_activity_at.desc(),
            AgentSession.created_at.desc(),
        )
    )
    result = await db.execute(stmt)
    sessions = list(result.scalars().all())
    for session in sessions:
        cardbox_service.ensure_session_box(session)
    return sessions


async def delete_session(
    db: AsyncSession,
    *,
    session_id: UUID,
    user_id: UUID,
) -> bool:
    """Soft delete a session for the given user."""

    try:
        session = await get_session(db, session_id=session_id, user_id=user_id)
        if not session:
            return False

        session.soft_delete()
        await db.flush()
        await commit_safely(db)

        logger.info("Deleted session %s for user %s", session_id, user_id)
        return True
    except Exception as exc:
        await rollback_safely(db)
        log_exception(
            logger, f"Error deleting session asynchronously: {exc}", sys.exc_info()
        )
        raise SessionHandlerError(f"Failed to delete session: {exc}") from exc


async def ensure_session(
    db: AsyncSession,
    *,
    user_id: UUID,
    session_id: Optional[UUID] = None,
    name: Optional[str] = None,
    sync_cardbox_on_create: bool = False,
    agent_name: Optional[str] = None,
    session_type: str = AgentSession.TYPE_CHAT,
) -> AgentSession:
    """Fetch existing session or create a new one for the user."""
    try:
        now = utc_now()
        if session_id:
            session = await get_session(db, session_id=session_id, user_id=user_id)
        else:
            session = None

        if session is None:
            if not session_id:
                session_id = uuid4()
            session_name = name or now.strftime("Session %Y-%m-%d %H:%M")
            return await create_session_with_id(
                db=db,
                user_id=user_id,
                session_id=session_id,
                name=session_name,
                sync_cardbox=sync_cardbox_on_create,
                module_key=agent_name,
                session_type=session_type,
            )

        session_name = name or session.name or now.strftime("Session %Y-%m-%d %H:%M")

        current_agent = getattr(session, "module_key", None)
        if agent_name and current_agent and current_agent != agent_name:
            message_count = await agent_message_handler.count_agent_messages(
                db, user_id=user_id, session_id=session.id
            )
            if message_count > 0:
                raise SessionHandlerError("Session belongs to a different agent")
            logger.info(
                "Reassigning agent for session %s from '%s' to '%s' (no history)",
                session.id,
                current_agent,
                agent_name,
            )
            session.module_key = agent_name
        elif agent_name and current_agent is None:
            session.module_key = agent_name

        if session_type and session.session_type != session_type:
            logger.warning(
                "Session %s has type '%s', requested '%s'; creating new session",
                session.id,
                session.session_type,
                session_type,
            )
            return await create_session(
                db=db,
                user_id=user_id,
                name=session_name,
                module_key=agent_name,
                sync_cardbox=sync_cardbox_on_create,
                session_type=session_type,
            )

        session.last_activity_at = now
        if session.deleted_at is not None:
            session.deleted_at = None
        if not session.name:
            session.name = session_name
        cardbox_service.ensure_session_box(session)
        await db.flush()
        await commit_safely(db)
        return session
    except Exception as exc:
        await rollback_safely(db)
        log_exception(
            logger, f"Error ensuring session asynchronously: {exc}", sys.exc_info()
        )
        raise SessionHandlerError(f"Failed to ensure session: {exc}") from exc


async def apply_session_overview(
    db: AsyncSession,
    *,
    session: AgentSession,
    title: Optional[str],
    summary: Optional[str],
) -> None:
    """Update session overview fields asynchronously."""
    updated = False
    now = utc_now()

    try:
        if title:
            trimmed = title.strip()
            if trimmed and session.name != trimmed:
                session.name = trimmed
                updated = True
        if summary:
            trimmed_summary = summary.strip()
            if session.summary != trimmed_summary:
                session.summary = trimmed_summary
                updated = True

        if updated:
            session.updated_at = now
            await db.flush()
            await commit_safely(db)
    except Exception as exc:  # pragma: no cover - defensive
        await rollback_safely(db)
        log_exception(
            logger,
            f"Failed to apply session overview asynchronously: {exc}",
            sys.exc_info(),
        )
        raise SessionHandlerError(f"Failed to apply session overview: {exc}") from exc


async def update_session(
    db: AsyncSession,
    *,
    session_id: UUID,
    user_id: UUID,
    name: Optional[str] = None,
    agent_name: Optional[str] = None,
) -> Optional[AgentSession]:
    """Async equivalent of SessionHandler.update_session."""

    try:
        session = await get_session(db, session_id=session_id, user_id=user_id)
        if not session:
            return None

        if name is not None:
            session.name = name

        if agent_name is not None:
            current_agent = getattr(session, "module_key", None)
            if current_agent and current_agent != agent_name:
                message_count = await agent_message_handler.count_agent_messages(
                    db, user_id=user_id, session_id=session.id
                )
                if message_count > 0:
                    raise SessionHandlerError("Session belongs to a different agent")
                logger.info(
                    "Reassigning agent for session %s from '%s' to '%s' (no history)",
                    session.id,
                    current_agent,
                    agent_name,
                )
                session.module_key = agent_name
            elif current_agent is None:
                session.module_key = agent_name

        session.updated_at = utc_now()
        await db.flush()
        await commit_safely(db)
        return session
    except Exception as exc:
        await rollback_safely(db)
        log_exception(
            logger, f"Error updating session asynchronously: {exc}", sys.exc_info()
        )
        raise SessionHandlerError(f"Failed to update session: {exc}") from exc


__all__ = [
    "SessionHandlerError",
    "cardbox_data_sync_service",
    "apply_session_overview",
    "create_session",
    "create_session_with_id",
    "delete_session",
    "ensure_session",
    "get_session",
    "get_user_sessions",
    "list_active_sessions",
    "soft_delete_sessions_for_user",
    "update_session",
]


def _get_cardbox_sync_service() -> "CardBoxDataSyncService":
    from app.cardbox.data_sync import cardbox_data_sync_service as _service

    return _service


class _CardboxSyncServiceProxy:
    """Lazy proxy for cardbox data sync service."""

    @staticmethod
    def _resolve() -> "CardBoxDataSyncService":
        return _get_cardbox_sync_service()

    def __getattr__(self, name: str):
        return getattr(self._resolve(), name)

    def __setattr__(self, name: str, value) -> None:
        setattr(self._resolve(), name, value)


cardbox_data_sync_service = _CardboxSyncServiceProxy()
