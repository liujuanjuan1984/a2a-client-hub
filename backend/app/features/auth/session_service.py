"""Server-side refresh session lifecycle management."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.auth_refresh_session import AuthRefreshSession
from app.utils.timezone_util import utc_now


class RefreshSessionError(RuntimeError):
    """Base error for refresh session state transitions."""


class RefreshSessionNotFoundError(RefreshSessionError):
    """Raised when a referenced refresh session does not exist."""


class RefreshSessionRevokedError(RefreshSessionError):
    """Raised when a refresh session is no longer active."""


class RefreshSessionReplayError(RefreshSessionError):
    """Raised when a rotated refresh JWT is replayed."""


@dataclass(frozen=True)
class RefreshSessionRotation:
    """Session row plus the next refresh JWT id to mint."""

    session: AuthRefreshSession
    next_jti: str
    was_legacy_bootstrap: bool = False


def _new_refresh_expiry() -> datetime:
    return utc_now() + timedelta(seconds=settings.jwt_refresh_token_ttl_seconds)


def _new_jti() -> str:
    return uuid4().hex


def _active_session_stmt(
    *, session_id: UUID, user_id: UUID
) -> Select[tuple[AuthRefreshSession]]:
    return (
        select(AuthRefreshSession)
        .where(
            AuthRefreshSession.id == session_id,
            AuthRefreshSession.user_id == user_id,
        )
        .with_for_update()
    )


async def create_refresh_session(
    db: AsyncSession,
    *,
    user_id: UUID,
    client_ip: str | None,
    user_agent: str | None,
) -> RefreshSessionRotation:
    """Create a fresh persisted refresh session and return its first jti."""

    next_jti = _new_jti()
    now = utc_now()
    session = AuthRefreshSession(
        user_id=user_id,
        current_jti=next_jti,
        expires_at=_new_refresh_expiry(),
        last_rotated_at=now,
        last_used_at=now,
        created_ip=client_ip,
        created_user_agent=user_agent,
        last_seen_ip=client_ip,
        last_seen_user_agent=user_agent,
    )
    db.add(session)
    await db.flush()
    return RefreshSessionRotation(session=session, next_jti=next_jti)


async def bootstrap_legacy_refresh_session(
    db: AsyncSession,
    *,
    user_id: UUID,
    client_ip: str | None,
    user_agent: str | None,
) -> RefreshSessionRotation:
    """Upgrade a legacy stateless refresh token into a persisted session."""

    rotation = await create_refresh_session(
        db,
        user_id=user_id,
        client_ip=client_ip,
        user_agent=user_agent,
    )
    return RefreshSessionRotation(
        session=rotation.session,
        next_jti=rotation.next_jti,
        was_legacy_bootstrap=True,
    )


async def rotate_refresh_session(
    db: AsyncSession,
    *,
    user_id: UUID,
    session_id: UUID,
    presented_jti: str | None,
    client_ip: str | None,
    user_agent: str | None,
) -> RefreshSessionRotation:
    """Rotate one active refresh session and detect replay of stale tokens."""

    result = await db.execute(
        _active_session_stmt(session_id=session_id, user_id=user_id)
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise RefreshSessionNotFoundError("Refresh session not found")

    now = utc_now()
    revoked_at = cast(datetime | None, session.revoked_at)
    expires_at = cast(datetime, session.expires_at)
    current_jti = cast(str, session.current_jti)
    if revoked_at is not None or expires_at <= now:
        raise RefreshSessionRevokedError("Refresh session is no longer active")

    if not presented_jti or current_jti != presented_jti:
        setattr(session, "revoked_at", now)
        setattr(session, "revoke_reason", "replayed_token")
        setattr(session, "last_used_at", now)
        setattr(session, "last_seen_ip", client_ip)
        setattr(session, "last_seen_user_agent", user_agent)
        db.add(session)
        raise RefreshSessionReplayError("Refresh session token replay detected")

    next_jti = _new_jti()
    setattr(session, "current_jti", next_jti)
    setattr(session, "expires_at", _new_refresh_expiry())
    setattr(session, "last_rotated_at", now)
    setattr(session, "last_used_at", now)
    setattr(session, "last_seen_ip", client_ip)
    setattr(session, "last_seen_user_agent", user_agent)
    db.add(session)
    await db.flush()
    return RefreshSessionRotation(session=session, next_jti=next_jti)


async def revoke_refresh_session(
    db: AsyncSession,
    *,
    session_id: UUID,
    user_id: UUID,
    reason: str,
    client_ip: str | None = None,
    user_agent: str | None = None,
) -> AuthRefreshSession | None:
    """Revoke one refresh session if it exists and is still active."""

    result = await db.execute(
        _active_session_stmt(session_id=session_id, user_id=user_id)
    )
    session = result.scalar_one_or_none()
    if session is None:
        return None
    if cast(datetime | None, session.revoked_at) is None:
        now = utc_now()
        setattr(session, "revoked_at", now)
        setattr(session, "revoke_reason", reason)
        setattr(session, "last_used_at", now)
        setattr(session, "last_seen_ip", client_ip)
        setattr(session, "last_seen_user_agent", user_agent)
        db.add(session)
    return session


async def revoke_all_refresh_sessions_for_user(
    db: AsyncSession,
    *,
    user_id: UUID,
    reason: str,
    client_ip: str | None = None,
    user_agent: str | None = None,
) -> int:
    """Revoke all active refresh sessions for one user."""

    result = await db.execute(
        select(AuthRefreshSession)
        .where(
            AuthRefreshSession.user_id == user_id,
            AuthRefreshSession.revoked_at.is_(None),
        )
        .with_for_update()
    )
    sessions = list(result.scalars())
    now = utc_now()
    for session in sessions:
        setattr(session, "revoked_at", now)
        setattr(session, "revoke_reason", reason)
        setattr(session, "last_used_at", now)
        setattr(session, "last_seen_ip", client_ip)
        setattr(session, "last_seen_user_agent", user_agent)
        db.add(session)
    if sessions:
        await db.flush()
    return len(sessions)


__all__ = [
    "RefreshSessionError",
    "RefreshSessionNotFoundError",
    "RefreshSessionReplayError",
    "RefreshSessionRevokedError",
    "RefreshSessionRotation",
    "bootstrap_legacy_refresh_session",
    "create_refresh_session",
    "revoke_all_refresh_sessions_for_user",
    "revoke_refresh_session",
    "rotate_refresh_session",
]
