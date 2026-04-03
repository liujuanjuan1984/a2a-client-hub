"""Lightweight transaction helpers for SQLAlchemy AsyncSession."""

from __future__ import annotations

import inspect
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


async def close_read_only_transaction(db: AsyncSession) -> None:
    """Commit an open read-only transaction without touching pending ORM writes."""

    in_transaction = getattr(db, "in_transaction", None)
    commit = getattr(db, "commit", None)
    if not callable(in_transaction) or not callable(commit):
        return
    if not in_transaction():
        return

    for attribute_name in ("new", "dirty", "deleted"):
        collection = getattr(db, attribute_name, None)
        if collection is None:
            continue
        try:
            if len(collection) > 0:
                return
        except Exception:
            try:
                if bool(collection):
                    return
            except Exception:
                return

    commit_outcome = commit()
    if inspect.isawaitable(commit_outcome):
        await commit_outcome


async def cleanup_session_safely(db: AsyncSession) -> None:
    """Rollback any open transaction and then close the session safely."""

    async def _cleanup() -> None:
        await rollback_safely(db)
        await db.close()

    await await_cancel_safe(_cleanup())


async def run_with_new_session(
    operation: Callable[[AsyncSession], Awaitable[T]],
    *,
    session_factory: Callable[[], AsyncSession],
) -> T:
    """Run one short-lived async DB unit of work in a fresh session."""

    async with session_factory() as db:
        return await operation(db)


__all__ = [
    "close_read_only_transaction",
    "cleanup_session_safely",
    "commit_safely",
    "rollback_safely",
    "run_with_new_session",
]
