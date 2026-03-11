"""Helpers for cancellation-safe async cleanup operations."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from contextlib import suppress
from typing import TypeVar

_ResultT = TypeVar("_ResultT")


async def await_cancel_safe(awaitable: Awaitable[_ResultT]) -> _ResultT:
    """Finish cleanup even if the current task is cancelled."""

    task: asyncio.Future[_ResultT] = asyncio.ensure_future(awaitable)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


async def await_cancel_safe_suppressed(awaitable: Awaitable[object]) -> None:
    """Finish cleanup and suppress any secondary cleanup failure."""

    with suppress(Exception, asyncio.CancelledError):
        await await_cancel_safe(awaitable)


__all__ = ["await_cancel_safe", "await_cancel_safe_suppressed"]
