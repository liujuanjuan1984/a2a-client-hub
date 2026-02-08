"""Service helpers for writing user activity audit records."""

from __future__ import annotations

from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.user_activity import UserActivity
from app.db.transaction import commit_safely

logger = get_logger(__name__)


async def log_activity(
    db: AsyncSession,
    *,
    user_id: Optional[UUID],
    event_type: str,
    status: str,
    metadata: Optional[Dict[str, Any]] = None,
    commit: bool = False,
) -> UserActivity:
    """Persist a user activity entry using an AsyncSession."""

    activity = UserActivity(
        user_id=user_id,
        event_type=event_type,
        status=status,
        payload=metadata or None,
    )
    db.add(activity)

    if commit:
        try:
            await commit_safely(db)
        except Exception:
            logger.exception(
                "Failed to commit user activity event %s (status=%s)",
                event_type,
                status,
            )
            raise

    return activity


__all__ = ["log_activity"]
