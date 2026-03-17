"""Lifecycle helpers and snapshots for A2A client resources."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable

from app.core.logging import get_logger
from app.utils.async_cleanup import await_cancel_safe

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class AsyncResourceReaperSnapshot:
    """Observable state for background resource draining tasks."""

    pending_tasks: int


@dataclass(frozen=True, slots=True)
class SharedSDKTransportBucketSnapshot:
    """Observable state for one shared SDK transport timeout bucket."""

    timeout_key: tuple[float | None, ...]
    current_generation: int | None
    tracked_generations: int
    invalidated_generations: int
    draining_generations: int
    active_users: int


@dataclass(frozen=True, slots=True)
class AdapterLifecycleSnapshot:
    """Lifecycle state for one cached adapter instance."""

    dialect: str
    active_operations: int
    retired: bool
    closed: bool
    transport_stale: bool = False


@dataclass(frozen=True, slots=True)
class A2AClientLifecycleSnapshot:
    """Lifecycle state for one A2AClient facade."""

    active_requests: int
    busy: bool
    cached_adapter_count: int
    adapter_snapshots: tuple[AdapterLifecycleSnapshot, ...]
    shared_transport: SharedSDKTransportBucketSnapshot | None


@dataclass(frozen=True, slots=True)
class A2AGatewayLifecycleSnapshot:
    """Lifecycle state for one gateway cache and its background reaper."""

    cached_clients: int
    busy_clients: int
    reaper: AsyncResourceReaperSnapshot
    client_snapshots: tuple[A2AClientLifecycleSnapshot, ...]


class AsyncResourceReaper:
    """Track background close/drain tasks behind a small stable interface."""

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[None]] = set()

    def schedule(
        self,
        awaitable: Awaitable[None],
        *,
        failure_log: str,
        success_log: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        task = asyncio.create_task(
            self._run(
                awaitable,
                failure_log=failure_log,
                success_log=success_log,
                extra=extra,
            )
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        tasks = list(self._tasks)
        self._tasks.clear()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def snapshot(self) -> AsyncResourceReaperSnapshot:
        return AsyncResourceReaperSnapshot(pending_tasks=len(self._tasks))

    @staticmethod
    async def _run(
        awaitable: Awaitable[None],
        *,
        failure_log: str,
        success_log: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        try:
            await await_cancel_safe(awaitable)
        except Exception:  # pragma: no cover - defensive cleanup
            logger.debug(failure_log, exc_info=True)
        else:
            logger.info(success_log, extra=extra)
