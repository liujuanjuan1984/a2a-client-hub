"""Shared client registry for cached A2A downstream sessions."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from app.core.logging import get_logger
from app.integrations.a2a_client.client import A2AClient
from app.integrations.a2a_client.config import A2ASettings
from app.integrations.a2a_client.lifecycle import AsyncResourceReaper
from app.utils.async_cleanup import await_cancel_safe
from app.utils.logging_redaction import redact_headers_for_logging

if TYPE_CHECKING:  # pragma: no cover - import for typing only
    from .service import ResolvedAgent

logger = get_logger(__name__)


@dataclass
class CachedClientEntry:
    client: A2AClient
    last_used: float


class A2AClientRegistry:
    """Manage the lifecycle of shared cached A2A clients."""

    def __init__(
        self,
        *,
        settings: A2ASettings,
        close_reaper: AsyncResourceReaper,
        client_builder: Callable[[ResolvedAgent], A2AClient],
    ) -> None:
        self._settings = settings
        self._close_reaper = close_reaper
        self._client_builder = client_builder
        self._clients: dict[
            tuple[str, tuple[tuple[str, str], ...]],
            CachedClientEntry,
        ] = {}
        self._client_lock = asyncio.Lock()

    @property
    def clients(
        self,
    ) -> dict[tuple[str, tuple[tuple[str, str], ...]], CachedClientEntry]:
        return self._clients

    async def get_client(self, resolved: "ResolvedAgent") -> A2AClient:
        cache_key = self.build_cache_key(resolved)
        async with self._client_lock:
            cached = self._clients.get(cache_key)
            if cached:
                cached.last_used = time.monotonic()
                logger.debug(
                    "Reusing cached A2A client",
                    extra={
                        "agent_name": resolved.name,
                        "headers": redact_headers_for_logging(resolved.headers),
                    },
                )
                return cached.client

            client = self._client_builder(resolved)
            self._clients[cache_key] = CachedClientEntry(
                client=client,
                last_used=time.monotonic(),
            )
            logger.info(
                "Created new A2A client",
                extra={
                    "agent_name": resolved.name,
                    "headers": redact_headers_for_logging(resolved.headers),
                },
            )
            return client

    async def cleanup_idle_clients(self) -> None:
        idle_timeout = max(self._settings.client_idle_timeout, 0.0)
        if idle_timeout <= 0:
            return
        now = time.monotonic()
        to_close: list[A2AClient] = []
        async with self._client_lock:
            stale_keys: list[tuple[str, tuple[tuple[str, str], ...]]] = []
            for key, entry in self._clients.items():
                if now - entry.last_used <= idle_timeout:
                    continue
                if entry.client.is_busy():
                    entry.last_used = now
                    continue
                stale_keys.append(key)
            for key in stale_keys:
                entry = self._clients.pop(key, None)
                if entry:
                    to_close.append(entry.client)
        for client in to_close:
            self._schedule_client_close(
                client,
                failure_log="Failed to close idle A2A client",
                success_log="Evicted idle A2A client",
            )

    async def invalidate_client(self, resolved: "ResolvedAgent") -> None:
        cache_key = self.build_cache_key(resolved)
        async with self._client_lock:
            entry = self._clients.pop(cache_key, None)
        if not entry:
            return
        self._schedule_client_close(
            entry.client,
            failure_log="Failed to close invalidated A2A client",
            success_log="Invalidated A2A client",
            extra={
                "agent_name": resolved.name,
                "headers": redact_headers_for_logging(resolved.headers),
            },
        )

    async def shutdown(self) -> None:
        async with self._client_lock:
            entries = list(self._clients.values())
            self._clients.clear()
        for entry in entries:
            try:
                await await_cancel_safe(entry.client.close())
            except Exception:  # pragma: no cover - defensive cleanup
                logger.debug(
                    "Failed to close A2A client during shutdown",
                    exc_info=True,
                )

    @staticmethod
    def build_cache_key(
        resolved: "ResolvedAgent",
    ) -> tuple[str, tuple[tuple[str, str], ...]]:
        headers_tuple = tuple(sorted(resolved.headers.items()))
        return resolved.url, headers_tuple

    def _schedule_client_close(
        self,
        client: A2AClient,
        *,
        failure_log: str,
        success_log: str,
        extra: dict[str, object] | None = None,
    ) -> None:
        self._close_reaper.schedule(
            client.close(),
            failure_log=failure_log,
            success_log=success_log,
            extra=extra,
        )


__all__ = ["A2AClientRegistry", "CachedClientEntry"]
