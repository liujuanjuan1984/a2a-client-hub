"""Lightweight transaction helpers for SQLAlchemy AsyncSession."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.async_cleanup import await_cancel_safe, await_cancel_safe_suppressed

T = TypeVar("T")


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


async def run_with_new_session(
    operation: Callable[[AsyncSession], Awaitable[T]],
    *,
    session_factory: Callable[[], AsyncSession],
) -> T:
    """Run one short-lived async DB unit of work in a fresh session."""

    async with session_factory() as db:
        return await operation(db)


__all__ = [
    "commit_safely",
    "rollback_safely",
    "run_with_new_session",
]
