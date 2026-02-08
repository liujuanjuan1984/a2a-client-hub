"""Notification service built on top of agent messaging."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable, Optional, Sequence, Tuple
from uuid import UUID

from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_message import AgentMessage
from app.db.models.agent_message_receipt import AgentMessageReceipt
from app.db.models.agent_session import AgentSession
from app.db.transaction import commit_safely
from app.handlers import agent_message as agent_message_handler
from app.handlers import agent_session as session_handler
from app.handlers.agent_session import SessionHandlerError
from app.utils.timezone_util import utc_now

logger = logging.getLogger(__name__)

_SYSTEM_SESSION_NAME = "系统通知"


class NotificationServiceError(Exception):
    """Base exception raised by the notification service."""


async def get_system_session(db: AsyncSession, *, user_id: UUID) -> AgentSession | None:
    """Return the existing system notification session if available."""

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
    return result.scalars().first()


async def _ensure_system_session(db: AsyncSession, *, user_id: UUID) -> AgentSession:
    """Fetch or create the dedicated system notification session for a user."""

    session = await get_system_session(db, user_id=user_id)
    if session:
        return session

    try:
        logger.info("Creating system notification session for user %s", user_id)
        return await session_handler.create_session(
            db,
            user_id=user_id,
            name=_SYSTEM_SESSION_NAME,
            module_key="system",
            session_type=AgentSession.TYPE_SYSTEM,
        )
    except SessionHandlerError as exc:  # pragma: no cover - defensive logging
        logger.exception("Failed to create system session for user %s", user_id)
        raise NotificationServiceError(str(exc)) from exc


async def send_notification(
    db: AsyncSession,
    *,
    user_ids: Sequence[UUID],
    body: str,
    title: str | None = None,
    severity: str = AgentMessage.SEVERITY_INFO,
    metadata: dict | None = None,
    sync_cardbox: bool = False,
) -> list[UUID]:
    """Send a system notification message to one or more users."""

    if not user_ids:
        return []

    created_messages: list[UUID] = []
    now = utc_now()

    for user_id in user_ids:
        session = await _ensure_system_session(db, user_id=user_id)

        message_metadata = {
            "title": title,
            "severity": severity,
            "payload": metadata or {},
        }

        message = await agent_message_handler.create_agent_message(
            db,
            user_id=user_id,
            content=body,
            sender="system",
            session_id=session.id,
            session=session,
            message_type=AgentMessage.TYPE_NOTIFICATION,
            severity=severity,
            metadata=message_metadata,
            sync_to_cardbox=sync_cardbox,
        )
        created_messages.append(message.id)

        session.last_activity_at = now
        session.updated_at = now

        receipt = AgentMessageReceipt(
            user_id=user_id,
            message_id=message.id,
            delivered_at=now,
        )
        db.add(receipt)

    await commit_safely(db)

    logger.info(
        "Sent notification '%s' to %d recipients",
        title or body[:32],
        len(created_messages),
    )
    return created_messages


async def mark_notifications_read(
    db: AsyncSession, *, user_id: UUID, message_ids: Iterable[UUID]
) -> int:
    """Mark the provided notifications as read for a user."""

    ids = [mid for mid in message_ids]
    if not ids:
        return 0

    stmt = (
        update(AgentMessageReceipt)
        .where(
            AgentMessageReceipt.user_id == user_id,
            AgentMessageReceipt.message_id.in_(ids),
            AgentMessageReceipt.read_at.is_(None),
        )
        .values(read_at=utc_now())
        .execution_options(synchronize_session=False)
    )
    result = await db.execute(stmt)
    updated = int(result.rowcount or 0)
    if updated:
        await commit_safely(db)
    return updated


def _base_notification_query(
    user_id: UUID, session_id: Optional[UUID]
) -> Select[Tuple[AgentMessage, datetime | None, datetime | None]]:
    stmt = (
        select(
            AgentMessage,
            AgentMessageReceipt.read_at,
            AgentMessageReceipt.delivered_at,
        )
        .join(
            AgentMessageReceipt,
            AgentMessageReceipt.message_id == AgentMessage.id,
        )
        .where(
            AgentMessageReceipt.user_id == user_id,
            AgentMessage.message_type == AgentMessage.TYPE_NOTIFICATION,
        )
    )
    if session_id:
        stmt = stmt.where(AgentMessage.session_id == session_id)
    return stmt


async def list_system_notifications(
    db: AsyncSession,
    *,
    user_id: UUID,
    session_id: Optional[UUID] = None,
    limit: int = 50,
    offset: int = 0,
) -> Tuple[int, list[Tuple[AgentMessage, Optional[datetime]]]]:
    """Return paginated system notifications with their read timestamps."""

    base_stmt = _base_notification_query(user_id, session_id)

    count_stmt = select(func.count()).select_from(base_stmt.subquery())
    total = int((await db.execute(count_stmt)).scalar_one())

    rows_stmt = (
        base_stmt.order_by(
            AgentMessageReceipt.delivered_at.desc(),
            AgentMessage.created_at.desc(),
            AgentMessage.id.desc(),
        )
        .offset(offset)
        .limit(limit)
    )
    rows = (await db.execute(rows_stmt)).all()
    return total, [(message, read_at) for message, read_at, _ in rows]


async def count_unread_system_notifications(
    db: AsyncSession, *, user_id: UUID, session_id: Optional[UUID] = None
) -> int:
    """Return the number of unread system notifications for the user."""

    stmt = (
        select(func.count())
        .select_from(AgentMessageReceipt)
        .join(AgentMessage, AgentMessage.id == AgentMessageReceipt.message_id)
        .where(
            AgentMessageReceipt.user_id == user_id,
            AgentMessageReceipt.read_at.is_(None),
            AgentMessage.message_type == AgentMessage.TYPE_NOTIFICATION,
        )
    )

    if session_id:
        stmt = stmt.where(AgentMessage.session_id == session_id)

    return int((await db.execute(stmt)).scalar_one())


async def mark_all_notifications_read(
    db: AsyncSession, *, user_id: UUID, session_id: Optional[UUID] = None
) -> int:
    """Mark all system notifications as read for the user."""

    message_ids_stmt = select(AgentMessage.id).where(
        AgentMessage.user_id == user_id,
        AgentMessage.message_type == AgentMessage.TYPE_NOTIFICATION,
    )
    if session_id:
        message_ids_stmt = message_ids_stmt.where(AgentMessage.session_id == session_id)

    stmt = (
        update(AgentMessageReceipt)
        .where(
            AgentMessageReceipt.user_id == user_id,
            AgentMessageReceipt.read_at.is_(None),
            AgentMessageReceipt.message_id.in_(message_ids_stmt),
        )
        .values(read_at=utc_now())
        .execution_options(synchronize_session=False)
    )
    result = await db.execute(stmt)
    updated = int(result.rowcount or 0)
    if updated:
        await commit_safely(db)
    return updated


__all__ = [
    "NotificationServiceError",
    "count_unread_system_notifications",
    "get_system_session",
    "list_system_notifications",
    "mark_all_notifications_read",
    "mark_notifications_read",
    "send_notification",
]
