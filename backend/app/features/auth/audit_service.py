"""Persistence helpers for auth audit events."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.auth_audit_event import AuthAuditEvent
from app.utils.timezone_util import utc_now


async def record_auth_event(
    db: AsyncSession,
    *,
    event_type: str,
    outcome: str,
    user_id: UUID | None = None,
    session_id: UUID | None = None,
    session_jti: str | None = None,
    email: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Append one auth audit record to the current transaction."""

    db.add(
        AuthAuditEvent(
            user_id=user_id,
            session_id=session_id,
            session_jti=session_jti,
            email=email,
            event_type=event_type,
            outcome=outcome,
            ip_address=ip_address,
            user_agent=user_agent,
            event_metadata=metadata,
            occurred_at=utc_now(),
        )
    )


__all__ = ["record_auth_event"]
