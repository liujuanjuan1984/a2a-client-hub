"""Lightweight transaction helpers for SQLAlchemy AsyncSession."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.async_cleanup import await_cancel_safe, await_cancel_safe_suppressed


async def commit_safely(db: AsyncSession) -> None:
    """Commit the session and rollback on failure."""

    try:
        await await_cancel_safe(db.commit())
    except Exception:
        await rollback_safely(db)
        raise


async def rollback_safely(db: AsyncSession) -> None:
    """Rollback the session, swallowing secondary rollback errors."""

    await await_cancel_safe_suppressed(db.rollback())


__all__ = [
    "commit_safely",
    "rollback_safely",
]
