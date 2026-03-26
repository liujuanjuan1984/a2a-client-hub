"""Unified gateway facade for A2A invokes and session orchestration."""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, Optional

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
from app.integrations.a2a_client.invoke_session import (
    A2AInvokeSession,
    AgentResolutionPolicy,
)
from app.integrations.a2a_client.lifecycle import (
    A2AGatewayLifecycleSnapshot,
    AsyncResourceReaper,
)
from app.integrations.a2a_client.metrics import a2a_metrics
from app.integrations.a2a_client.registry import A2AClientRegistry
from app.integrations.a2a_client.resolution import A2AResolutionService
from app.integrations.a2a_client.session_factory import A2AInvokeSessionFactory
from app.utils.logging_redaction import (
    redact_url_for_logging,
)

if TYPE_CHECKING:  # pragma: no cover - import for typing only
    from a2a.types import AgentCard

    from .types import ResolvedAgent

logger = get_logger(__name__)


class A2AGateway:
    """Facade that coordinates A2A invokes on top of smaller collaborators."""

    def __init__(self, settings: A2ASettings) -> None:
        self.settings = settings
        self._close_reaper = AsyncResourceReaper()
        self._client_registry = A2AClientRegistry(
            settings=settings,
            close_reaper=self._close_reaper,
            client_builder=self._create_client,
        )
        self._resolution_service = A2AResolutionService()
        self._session_factory = A2AInvokeSessionFactory(
            resolution_service=self._resolution_service,
            shared_client_getter=lambda resolved: self._get_client(resolved),
            shared_client_invalidator=lambda resolved: self._invalidate_client(
                resolved
            ),
            ephemeral_client_builder=lambda resolved, **kwargs: self._create_client(
                resolved,
                **kwargs,
            ),
        )
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

        async with self.open_invoke_session(
            resolved=resolved,
            policy=AgentResolutionPolicy.CACHED_SHARED,
        ) as session:
            call_task = asyncio.create_task(
                session.client.call_agent(
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
                await self._handle_client_reset(resolved=resolved, session=session)
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
                error_code = getattr(exc, "error_code", "agent_unavailable")
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
                    error_code=error_code,
                )
                return {
                    "success": False,
                    "agent_name": resolved.name,
                    "agent_url": resolved.url,
                    "error": str(exc),
                    "error_code": error_code,
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
        session: Optional[A2AInvokeSession] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        logger.info(
            "A2A stream",
            extra={
                "agent_name": resolved.name,
                "agent_url": redact_url_for_logging(resolved.url),
                "query_meta": summarize_query(query),
            },
        )

        if session is not None:
            async for payload in session.client.stream_agent(
                query,
                context_id=context_id,
                metadata=metadata,
            ):
                yield payload
            return

        async with self.open_invoke_session(
            resolved=resolved,
            policy=AgentResolutionPolicy.CACHED_SHARED,
        ) as shared_session:
            try:
                async for payload in shared_session.client.stream_agent(
                    query,
                    context_id=context_id,
                    metadata=metadata,
                ):
                    yield payload
            except A2AClientResetRequiredError:
                await self._handle_client_reset(
                    resolved=resolved, session=shared_session
                )
                raise

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
            async with self.open_invoke_session(
                resolved=resolved,
                policy=AgentResolutionPolicy.CACHED_SHARED,
            ) as session:
                result = await session.client.cancel_task(
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
            error_code = getattr(exc, "error_code", "agent_unavailable")
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
                error_code=error_code,
            )
            return {
                "success": False,
                "agent_name": resolved.name,
                "agent_url": resolved.url,
                "task_id": normalized_task_id,
                "error": str(exc),
                "error_code": error_code,
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

    async def get_task(
        self,
        *,
        resolved: "ResolvedAgent",
        task_id: str,
        history_length: int | None = None,
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

        start_time = time.monotonic()
        logger.info(
            "A2A task get",
            extra={
                "agent_name": resolved.name,
                "agent_url": redact_url_for_logging(resolved.url),
                "task_id": normalized_task_id,
                "history_length": history_length,
            },
        )
        try:
            async with self.open_invoke_session(
                resolved=resolved,
                policy=AgentResolutionPolicy.CACHED_SHARED,
            ) as session:
                result = await session.client.get_task(
                    normalized_task_id,
                    history_length=history_length,
                    metadata=metadata,
                )
        except A2AClientResetRequiredError as exc:
            await self._invalidate_client(resolved)
            elapsed = time.monotonic() - start_time
            logger.error(
                "A2A task get requires client reset",
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
                "A2A task get blocked by allowlist",
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
            error_code = getattr(exc, "error_code", "agent_unavailable")
            elapsed = time.monotonic() - start_time
            logger.error(
                "A2A task get unavailable",
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
                error_code=error_code,
            )
            return {
                "success": False,
                "agent_name": resolved.name,
                "agent_url": resolved.url,
                "task_id": normalized_task_id,
                "error": str(exc),
                "error_code": error_code,
            }
        except Exception as exc:  # noqa: BLE001
            elapsed = time.monotonic() - start_time
            logger.error(
                "A2A task get failed unexpectedly",
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
            "A2A task get finished",
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

    @asynccontextmanager
    async def open_invoke_session(
        self,
        *,
        resolved: "ResolvedAgent",
        policy: AgentResolutionPolicy = AgentResolutionPolicy.CACHED_SHARED,
        card_fetch_timeout: float | None = None,
    ) -> AsyncIterator[A2AInvokeSession]:
        """Open an invoke session with explicit shared or ephemeral semantics."""

        async with self._session_factory.open_session(
            resolved=resolved,
            policy=policy,
            card_fetch_timeout=card_fetch_timeout,
        ) as session:
            try:
                yield session
            except A2AClientResetRequiredError:
                await self._session_factory.handle_client_reset(
                    resolved=resolved,
                    session=session,
                )
                raise

    async def fetch_agent_card_detail(
        self,
        *,
        resolved: "ResolvedAgent",
        raise_on_failure: bool = False,
        policy: AgentResolutionPolicy = AgentResolutionPolicy.CACHED_SHARED,
        card_fetch_timeout: float | None = None,
    ) -> Optional["AgentCard"]:
        start_time = time.monotonic()
        try:
            async with self.open_invoke_session(
                resolved=resolved,
                policy=policy,
                card_fetch_timeout=card_fetch_timeout,
            ) as session:
                card = session.snapshot.agent_card
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

    async def _handle_client_reset(
        self,
        *,
        resolved: "ResolvedAgent",
        session: A2AInvokeSession,
    ) -> None:
        await self._session_factory.handle_client_reset(
            resolved=resolved,
            session=session,
        )

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
        await self._client_registry.shutdown()
        await self._close_reaper.drain()

    async def _get_client(self, resolved: "ResolvedAgent") -> A2AClient:
        await self.start_maintenance()
        return await self._client_registry.get_client(resolved)

    async def _cleanup_idle_clients(self) -> None:
        await self._client_registry.cleanup_idle_clients()

    async def _invalidate_client(self, resolved: "ResolvedAgent") -> None:
        await self._client_registry.invalidate_client(resolved)

    def _build_interceptors(
        self, resolved: "ResolvedAgent"
    ) -> list[ClientCallInterceptor]:
        if not resolved.headers:
            return []
        return [StaticHeaderInterceptor(resolved.headers)]

    def get_lifecycle_snapshot(self) -> A2AGatewayLifecycleSnapshot:
        clients = self._client_registry.clients
        client_snapshots = tuple(
            entry.client.get_lifecycle_snapshot() for entry in clients.values()
        )
        busy_clients = sum(1 for snapshot in client_snapshots if snapshot.busy)
        return A2AGatewayLifecycleSnapshot(
            cached_clients=len(clients),
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
