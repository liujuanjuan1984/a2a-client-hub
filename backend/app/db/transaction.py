"""Lightweight transaction helpers for SQLAlchemy AsyncSession."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


async def commit_safely(db: AsyncSession) -> None:
    """Commit the session and rollback on failure."""

    try:
        await db.commit()
    except Exception:
        await rollback_safely(db)
        raise


async def rollback_safely(db: AsyncSession) -> None:
    """Rollback the session, swallowing secondary rollback errors."""

    try:
        await db.rollback()
    except Exception:
        # Secondary rollback failures should not shadow the original issue.
        pass


__all__ = [
    "commit_safely",
    "rollback_safely",
]
