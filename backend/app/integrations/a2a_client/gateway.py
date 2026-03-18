"""Unified gateway that manages A2A client lifecycle and retries."""

from __future__ import annotations

import asyncio
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, Optional

import httpx
from a2a.client import ClientCallInterceptor

from app.core.logging import get_logger
from app.integrations.a2a_client.client import A2AClient, StaticHeaderInterceptor
from app.integrations.a2a_client.config import A2ASettings
from app.integrations.a2a_client.controls import summarize_query
from app.integrations.a2a_client.errors import (
    A2AAgentUnavailableError,
    A2AClientResetRequiredError,
    A2AOutboundNotAllowedError,
)
from app.integrations.a2a_client.lifecycle import (
    A2AGatewayLifecycleSnapshot,
    AsyncResourceReaper,
)
from app.integrations.a2a_client.metrics import a2a_metrics
from app.utils.async_cleanup import await_cancel_safe
from app.utils.logging_redaction import (
    redact_headers_for_logging,
    redact_url_for_logging,
)

if TYPE_CHECKING:  # pragma: no cover - import for typing only
    from a2a.types import AgentCard

    from .service import ResolvedAgent

logger = get_logger(__name__)


@dataclass
class CachedClientEntry:
    client: A2AClient
    last_used: float


class A2AGateway:
    """Centralized coordinator for A2A HTTP clients and retries."""

    def __init__(self, settings: A2ASettings) -> None:
        self.settings = settings
        self._clients: Dict[
            tuple[str, tuple[tuple[str, str], ...]], CachedClientEntry
        ] = {}
        self._client_lock = asyncio.Lock()
        self._close_reaper = AsyncResourceReaper()
        self._maintenance_lock = asyncio.Lock()
        self._maintenance_task: asyncio.Task[None] | None = None

    async def invoke(
        self,
        *,
        resolved: "ResolvedAgent",
        query: str,
        context_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        timeout_seconds = float(max(timeout or self.settings.default_timeout, 1.0))
        client = await self._get_client(resolved)
        start_time = time.monotonic()

        query_meta = summarize_query(query)

        logger.info(
            "A2A invoke",
            extra={
                "agent_name": resolved.name,
                "agent_url": redact_url_for_logging(resolved.url),
                "query_meta": query_meta,
                "timeout_seconds": timeout_seconds,
            },
        )

        call_task = asyncio.create_task(
            client.call_agent(
                query,
                context_id=context_id,
                metadata=metadata,
            )
        )
        watchdog_task: Optional[asyncio.Task[Any]] = None
        if self.settings.invoke_watchdog_interval > 0:
            watchdog_task = asyncio.create_task(
                self._watch_pending_invoke(
                    resolved=resolved,
                    payload={
                        "query_meta": query_meta,
                        "timeout_seconds": timeout_seconds,
                    },
                    start_time=start_time,
                )
            )

        try:
            result = await asyncio.wait_for(call_task, timeout=timeout_seconds)
        except asyncio.CancelledError:
            elapsed = time.monotonic() - start_time
            logger.warning(
                "A2A invoke cancelled",
                extra={
                    "agent_name": resolved.name,
                    "elapsed_seconds": round(elapsed, 3),
                    "query_meta": query_meta,
                },
            )
            call_task.cancel()
            raise
        except A2AClientResetRequiredError as exc:
            await self._invalidate_client(resolved)
            elapsed = time.monotonic() - start_time
            logger.error(
                "A2A client reset required",
                extra={
                    "agent_name": resolved.name,
                    "elapsed_seconds": round(elapsed, 3),
                    "error": str(exc),
                },
            )
            a2a_metrics.record_call(
                resolved.name,
                success=False,
                error_code="client_reset",
            )
            return {
                "success": False,
                "agent_name": resolved.name,
                "agent_url": resolved.url,
                "error": str(exc),
                "error_code": "client_reset",
            }
        except A2AOutboundNotAllowedError as exc:
            elapsed = time.monotonic() - start_time
            logger.error(
                "A2A outbound target blocked",
                extra={
                    "agent_name": resolved.name,
                    "elapsed_seconds": round(elapsed, 3),
                    "error": str(exc),
                },
            )
            a2a_metrics.record_call(
                resolved.name,
                success=False,
                error_code="outbound_not_allowed",
            )
            return {
                "success": False,
                "agent_name": resolved.name,
                "agent_url": resolved.url,
                "error": "Outbound A2A URL is not allowed",
                "error_code": "outbound_not_allowed",
            }
        except A2AAgentUnavailableError as exc:
            elapsed = time.monotonic() - start_time
            logger.error(
                "A2A unavailable",
                extra={
                    "agent_name": resolved.name,
                    "elapsed_seconds": round(elapsed, 3),
                    "error": str(exc),
                },
            )
            a2a_metrics.record_call(
                resolved.name,
                success=False,
                error_code="agent_unavailable",
            )
            return {
                "success": False,
                "agent_name": resolved.name,
                "agent_url": resolved.url,
                "error": str(exc),
                "error_code": "agent_unavailable",
            }
        except asyncio.TimeoutError:
            elapsed = time.monotonic() - start_time
            call_task.cancel()
            with suppress(asyncio.CancelledError):
                await call_task
            logger.error(
                "A2A timeout",
                extra={
                    "agent_name": resolved.name,
                    "timeout_seconds": timeout_seconds,
                    "elapsed_seconds": round(elapsed, 3),
                    "query_meta": query_meta,
                },
            )
            a2a_metrics.record_call(
                resolved.name,
                success=False,
                error_code="timeout",
            )
            return {
                "success": False,
                "agent_name": resolved.name,
                "agent_url": resolved.url,
                "error": f"A2A agent timed out after {elapsed:.1f}s",
                "error_code": "timeout",
            }
        finally:
            if watchdog_task:
                watchdog_task.cancel()
                with suppress(asyncio.CancelledError):
                    await watchdog_task

        elapsed = time.monotonic() - start_time
        success = bool(result.get("success"))
        a2a_metrics.record_call(
            resolved.name,
            success=success,
            error_code=None if success else result.get("error_code"),
        )
        logger.info(
            "A2A invoke finished",
            extra={
                "agent_name": resolved.name,
                "success": success,
                "elapsed_seconds": round(elapsed, 3),
                "error_code": result.get("error_code"),
            },
        )
        return result

    async def stream(
        self,
        *,
        resolved: "ResolvedAgent",
        query: str,
        context_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        logger.info(
            "A2A stream",
            extra={
                "agent_name": resolved.name,
                "agent_url": redact_url_for_logging(resolved.url),
                "query_meta": summarize_query(query),
            },
        )

        client = await self._get_client(resolved)
        async for payload in client.stream_agent(
            query,
            context_id=context_id,
            metadata=metadata,
        ):
            yield payload

    async def cancel_task(
        self,
        *,
        resolved: "ResolvedAgent",
        task_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        normalized_task_id = task_id.strip() if isinstance(task_id, str) else ""
        if not normalized_task_id:
            return {
                "success": False,
                "agent_name": resolved.name,
                "agent_url": resolved.url,
                "task_id": normalized_task_id,
                "error": "Task id is required.",
                "error_code": "invalid_task_id",
            }

        client = await self._get_client(resolved)
        start_time = time.monotonic()
        logger.info(
            "A2A task cancel",
            extra={
                "agent_name": resolved.name,
                "agent_url": redact_url_for_logging(resolved.url),
                "task_id": normalized_task_id,
            },
        )
        try:
            result = await client.cancel_task(
                normalized_task_id,
                metadata=metadata,
            )
        except A2AClientResetRequiredError as exc:
            await self._invalidate_client(resolved)
            elapsed = time.monotonic() - start_time
            logger.error(
                "A2A task cancel requires client reset",
                extra={
                    "agent_name": resolved.name,
                    "elapsed_seconds": round(elapsed, 3),
                    "task_id": normalized_task_id,
                    "error": str(exc),
                },
            )
            a2a_metrics.record_call(
                resolved.name,
                success=False,
                error_code="client_reset",
            )
            return {
                "success": False,
                "agent_name": resolved.name,
                "agent_url": resolved.url,
                "task_id": normalized_task_id,
                "error": str(exc),
                "error_code": "client_reset",
            }
        except A2AOutboundNotAllowedError as exc:
            elapsed = time.monotonic() - start_time
            logger.error(
                "A2A task cancel blocked by allowlist",
                extra={
                    "agent_name": resolved.name,
                    "elapsed_seconds": round(elapsed, 3),
                    "task_id": normalized_task_id,
                    "error": str(exc),
                },
            )
            a2a_metrics.record_call(
                resolved.name,
                success=False,
                error_code="outbound_not_allowed",
            )
            return {
                "success": False,
                "agent_name": resolved.name,
                "agent_url": resolved.url,
                "task_id": normalized_task_id,
                "error": "Outbound A2A URL is not allowed",
                "error_code": "outbound_not_allowed",
            }
        except A2AAgentUnavailableError as exc:
            elapsed = time.monotonic() - start_time
            logger.error(
                "A2A task cancel unavailable",
                extra={
                    "agent_name": resolved.name,
                    "elapsed_seconds": round(elapsed, 3),
                    "task_id": normalized_task_id,
                    "error": str(exc),
                },
            )
            a2a_metrics.record_call(
                resolved.name,
                success=False,
                error_code="agent_unavailable",
            )
            return {
                "success": False,
                "agent_name": resolved.name,
                "agent_url": resolved.url,
                "task_id": normalized_task_id,
                "error": str(exc),
                "error_code": "agent_unavailable",
            }
        except Exception as exc:  # noqa: BLE001
            elapsed = time.monotonic() - start_time
            logger.error(
                "A2A task cancel failed unexpectedly",
                exc_info=True,
                extra={
                    "agent_name": resolved.name,
                    "elapsed_seconds": round(elapsed, 3),
                    "task_id": normalized_task_id,
                },
            )
            a2a_metrics.record_call(
                resolved.name,
                success=False,
                error_code="upstream_error",
            )
            return {
                "success": False,
                "agent_name": resolved.name,
                "agent_url": resolved.url,
                "task_id": normalized_task_id,
                "error": str(exc),
                "error_code": "upstream_error",
            }

        elapsed = time.monotonic() - start_time
        success = bool(result.get("success"))
        error_code = (
            None if success else str(result.get("error_code") or "upstream_error")
        )
        a2a_metrics.record_call(
            resolved.name,
            success=success,
            error_code=error_code,
        )
        logger.info(
            "A2A task cancel finished",
            extra={
                "agent_name": resolved.name,
                "success": success,
                "elapsed_seconds": round(elapsed, 3),
                "task_id": normalized_task_id,
                "error_code": error_code,
            },
        )
        return {
            "success": success,
            "agent_name": resolved.name,
            "agent_url": resolved.url,
            "task_id": normalized_task_id,
            "error": result.get("error"),
            "error_code": error_code,
            "task": result.get("task"),
        }

    async def _watch_pending_invoke(
        self,
        *,
        resolved: "ResolvedAgent",
        payload: Dict[str, Any],
        start_time: float,
    ) -> None:
        interval = max(self.settings.invoke_watchdog_interval, 0.0)
        if interval <= 0:
            return
        try:
            while True:
                await asyncio.sleep(interval)
                elapsed = time.monotonic() - start_time
                logger.info(
                    "A2A invoke still pending",
                    extra={
                        "agent_name": resolved.name,
                        "elapsed_seconds": round(elapsed, 3),
                        "payload": payload,
                    },
                )
        except asyncio.CancelledError:
            raise

    async def fetch_agent_card_detail(
        self,
        *,
        resolved: "ResolvedAgent",
        client: Optional[A2AClient] = None,
        raise_on_failure: bool = False,
        use_temporary_client: bool = False,
        card_fetch_timeout: float | None = None,
    ) -> Optional["AgentCard"]:
        owns_client = False
        if client is not None:
            client_instance = client
        elif use_temporary_client:
            client_instance = self._create_client(
                resolved,
                card_fetch_timeout=card_fetch_timeout,
            )
            owns_client = True
        else:
            client_instance = await self._get_client(resolved)
        start_time = time.monotonic()
        try:
            card = await client_instance.get_agent_card()
        except A2AOutboundNotAllowedError as exc:
            elapsed = time.monotonic() - start_time
            logger.warning(
                "A2A card fetch blocked by allowlist",
                extra={
                    "agent_name": resolved.name,
                    "error": str(exc),
                    "elapsed_seconds": round(elapsed, 3),
                },
            )
            if raise_on_failure:
                raise
            return None
        except A2AClientResetRequiredError as exc:
            if not owns_client:
                await self._invalidate_client(resolved)
            elapsed = time.monotonic() - start_time
            logger.warning(
                "A2A card fetch requires client reset",
                extra={
                    "agent_name": resolved.name,
                    "error": str(exc),
                    "elapsed_seconds": round(elapsed, 3),
                },
            )
            if raise_on_failure:
                raise
            return None
        except A2AAgentUnavailableError as exc:
            elapsed = time.monotonic() - start_time
            logger.warning(
                "A2A card fetch failed",
                extra={
                    "agent_name": resolved.name,
                    "error": str(exc),
                    "elapsed_seconds": round(elapsed, 3),
                },
            )
            if raise_on_failure:
                raise
            return None
        else:
            elapsed = time.monotonic() - start_time
            logger.info(
                "Fetched A2A agent card detail",
                extra={
                    "agent_name": resolved.name,
                    "card_name": getattr(card, "name", None),
                    "elapsed_seconds": round(elapsed, 3),
                },
            )
            return card
        finally:
            if owns_client:
                await await_cancel_safe(client_instance.close())

    def _create_client(
        self,
        resolved: "ResolvedAgent",
        *,
        card_fetch_timeout: float | None = None,
    ) -> A2AClient:
        timeout = httpx.Timeout(self.settings.default_timeout)
        return A2AClient(
            resolved.url,
            timeout=timeout,
            use_client_preference=self.settings.use_client_preference,
            interceptors=self._build_interceptors(resolved),
            default_headers=resolved.headers,
            card_fetch_timeout=(
                self.settings.card_fetch_timeout
                if card_fetch_timeout is None
                else card_fetch_timeout
            ),
        )

    async def shutdown(self) -> None:
        await self.stop_maintenance()
        async with self._client_lock:
            entries = list(self._clients.values())
            self._clients.clear()
        for entry in entries:
            try:
                await await_cancel_safe(entry.client.close())
            except Exception:  # pragma: no cover - defensive cleanup
                logger.debug(
                    "Failed to close A2A client during shutdown", exc_info=True
                )
        await self._close_reaper.drain()

    async def _get_client(self, resolved: "ResolvedAgent") -> A2AClient:
        await self.start_maintenance()
        cache_key = self._build_cache_key(resolved)
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

            client = self._create_client(resolved)
            self._clients[cache_key] = CachedClientEntry(
                client=client, last_used=time.monotonic()
            )
            logger.info(
                "Created new A2A client",
                extra={
                    "agent_name": resolved.name,
                    "headers": redact_headers_for_logging(resolved.headers),
                },
            )
            return client

    async def _cleanup_idle_clients(self) -> None:
        idle_timeout = max(self.settings.client_idle_timeout, 0.0)
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

    async def _invalidate_client(self, resolved: "ResolvedAgent") -> None:
        cache_key = self._build_cache_key(resolved)
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

    def _build_interceptors(
        self, resolved: "ResolvedAgent"
    ) -> list[ClientCallInterceptor]:
        if not resolved.headers:
            return []
        return [StaticHeaderInterceptor(resolved.headers)]

    @staticmethod
    def _build_cache_key(
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
        extra: dict[str, Any] | None = None,
    ) -> None:
        self._close_reaper.schedule(
            client.close(),
            failure_log=failure_log,
            success_log=success_log,
            extra=extra,
        )

    def get_lifecycle_snapshot(self) -> A2AGatewayLifecycleSnapshot:
        client_snapshots = tuple(
            entry.client.get_lifecycle_snapshot() for entry in self._clients.values()
        )
        busy_clients = sum(1 for snapshot in client_snapshots if snapshot.busy)
        return A2AGatewayLifecycleSnapshot(
            cached_clients=len(self._clients),
            busy_clients=busy_clients,
            reaper=self._close_reaper.snapshot(),
            client_snapshots=client_snapshots,
        )

    async def start_maintenance(self) -> None:
        interval = self._resolve_maintenance_interval()
        if interval is None:
            return
        async with self._maintenance_lock:
            if self._maintenance_task is not None and not self._maintenance_task.done():
                return
            self._maintenance_task = asyncio.create_task(
                self._run_maintenance_loop(interval)
            )

    async def stop_maintenance(self) -> None:
        async with self._maintenance_lock:
            task = self._maintenance_task
            self._maintenance_task = None
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def _run_maintenance_loop(self, interval: float) -> None:
        try:
            while True:
                await asyncio.sleep(interval)
                await self._cleanup_idle_clients()
        except asyncio.CancelledError:  # pragma: no cover - cooperative shutdown
            raise
        except Exception:  # pragma: no cover - defensive background task
            logger.exception("A2A gateway maintenance loop failed")
            async with self._maintenance_lock:
                if self._maintenance_task is asyncio.current_task():
                    self._maintenance_task = None
            raise

    def _resolve_maintenance_interval(self) -> float | None:
        idle_timeout = max(self.settings.client_idle_timeout, 0.0)
        if idle_timeout <= 0:
            return None
        configured_interval = self.settings.client_maintenance_interval
        if configured_interval > 0:
            return configured_interval
        return min(max(idle_timeout / 2, 1.0), 60.0)


__all__ = ["A2AGateway"]
