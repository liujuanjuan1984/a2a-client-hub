"""Server-side refresh session lifecycle management."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.auth_legacy_refresh_revocation import AuthLegacyRefreshRevocation
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


class LegacyRefreshTokenRevokedError(RefreshSessionError):
    """Raised when a legacy stateless refresh token has been revoked."""


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


async def consume_legacy_refresh_token(
    db: AsyncSession,
    *,
    user_id: UUID,
    token_jti: str | None,
    expires_at: datetime | None,
) -> None:
    """Atomically mark one legacy refresh token as consumed for session bootstrap."""

    if not token_jti:
        raise LegacyRefreshTokenRevokedError(
            "Legacy refresh token cannot be upgraded without jti"
        )

    statement = (
        pg_insert(AuthLegacyRefreshRevocation)
        .values(
            user_id=user_id,
            token_jti=token_jti,
            expires_at=expires_at or _new_refresh_expiry(),
            revoked_at=utc_now(),
            revoke_reason="session_bootstrap",
        )
        .on_conflict_do_nothing(index_elements=["token_jti"])
        .returning(AuthLegacyRefreshRevocation.id)
    )
    inserted = (await db.execute(statement)).scalar_one_or_none()
    if inserted is None:
        raise LegacyRefreshTokenRevokedError("Legacy refresh token is revoked")


async def ensure_legacy_refresh_token_is_not_revoked(
    db: AsyncSession,
    *,
    user_id: UUID,
    token_jti: str | None,
) -> None:
    """Reject legacy refresh tokens that were previously revoked by jti."""

    if not token_jti:
        return

    result = await db.execute(
        select(AuthLegacyRefreshRevocation)
        .where(
            AuthLegacyRefreshRevocation.user_id == user_id,
            AuthLegacyRefreshRevocation.token_jti == token_jti,
        )
        .limit(1)
    )
    if result.scalar_one_or_none() is not None:
        raise LegacyRefreshTokenRevokedError("Legacy refresh token is revoked")


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


async def revoke_legacy_refresh_token(
    db: AsyncSession,
    *,
    user_id: UUID,
    token_jti: str | None,
    expires_at: datetime | None,
    reason: str,
) -> AuthLegacyRefreshRevocation | None:
    """Revoke one legacy refresh token by jti when it can be identified."""

    if not token_jti:
        return None

    result = await db.execute(
        select(AuthLegacyRefreshRevocation)
        .where(
            AuthLegacyRefreshRevocation.user_id == user_id,
            AuthLegacyRefreshRevocation.token_jti == token_jti,
        )
        .with_for_update()
    )
    revocation = result.scalar_one_or_none()
    if revocation is not None:
        return revocation

    revocation = AuthLegacyRefreshRevocation(
        user_id=user_id,
        token_jti=token_jti,
        expires_at=expires_at or _new_refresh_expiry(),
        revoked_at=utc_now(),
        revoke_reason=reason,
    )
    db.add(revocation)
    await db.flush()
    return revocation


__all__ = [
    "consume_legacy_refresh_token",
    "LegacyRefreshTokenRevokedError",
    "RefreshSessionError",
    "RefreshSessionNotFoundError",
    "RefreshSessionReplayError",
    "RefreshSessionRevokedError",
    "RefreshSessionRotation",
    "bootstrap_legacy_refresh_session",
    "create_refresh_session",
    "ensure_legacy_refresh_token_is_not_revoked",
    "revoke_all_refresh_sessions_for_user",
    "revoke_legacy_refresh_token",
    "revoke_refresh_session",
    "rotate_refresh_session",
]
