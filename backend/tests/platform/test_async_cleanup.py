from __future__ import annotations

import asyncio

import pytest

from app.utils.async_cleanup import await_cancel_safe, await_cancel_safe_suppressed


@pytest.mark.asyncio
async def test_await_cancel_safe_finishes_cleanup_before_propagating_cancellation() -> (
    None
):
    started = asyncio.Event()
    released = asyncio.Event()
    finished = asyncio.Event()

    async def _cleanup() -> str:
        started.set()
        await released.wait()
        finished.set()
        return "done"

    task = asyncio.create_task(await_cancel_safe(_cleanup()))
    await asyncio.wait_for(started.wait(), timeout=1.0)
    task.cancel()

    released.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert finished.is_set() is True


@pytest.mark.asyncio
async def test_await_cancel_safe_suppressed_swallow_secondary_cleanup_cancellation() -> (
    None
):
    started = asyncio.Event()
    released = asyncio.Event()
    finished = asyncio.Event()

    async def _cleanup() -> None:
        started.set()
        await released.wait()
        finished.set()

    task = asyncio.create_task(await_cancel_safe_suppressed(_cleanup()))
    await asyncio.wait_for(started.wait(), timeout=1.0)
    task.cancel()

    released.set()
    await asyncio.wait_for(task, timeout=1.0)

    assert finished.is_set() is True
