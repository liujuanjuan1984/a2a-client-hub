"""Service facade for A2A Agent Card extensions."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.core.logging import get_logger
from app.integrations.a2a_extensions.errors import A2AExtensionUpstreamError
from app.integrations.a2a_extensions.interrupt_extension_service import (
    InterruptExtensionService,
)
from app.integrations.a2a_extensions.opencode_discovery_service import (
    OpencodeDiscoveryService,
)
from app.integrations.a2a_extensions.service_common import ExtensionCallResult
from app.integrations.a2a_extensions.session_binding import resolve_session_binding
from app.integrations.a2a_extensions.session_extension_service import (
    SessionExtensionService,
)
from app.integrations.a2a_extensions.shared_support import (
    A2AExtensionSupport,
)
from app.integrations.a2a_extensions.types import ResolvedSessionBindingExtension
from app.services.a2a_runtime import A2ARuntime

logger = get_logger(__name__)
_SESSION_BINDING_CACHE_TTL_SECONDS = 300.0


@dataclass(slots=True)
class _SessionBindingCacheEntry:
    resolved: ResolvedSessionBindingExtension
    expires_at: float


class A2AExtensionsService:
    def __init__(self) -> None:
        self._support = A2AExtensionSupport()
        self._session_extensions = SessionExtensionService(self._support)
        self._interrupt_extensions = InterruptExtensionService(self._support)
        self._opencode_discovery = OpencodeDiscoveryService(self._support)
        self._session_binding_cache_lock = asyncio.Lock()
        self._session_binding_cache: dict[
            tuple[str, tuple[tuple[str, str], ...]],
            _SessionBindingCacheEntry,
        ] = {}

    async def shutdown(self) -> None:
        await self._support.shutdown()
        async with self._session_binding_cache_lock:
            self._session_binding_cache.clear()

    @staticmethod
    def _session_binding_cache_key(
        runtime: A2ARuntime,
    ) -> tuple[str, tuple[tuple[str, str], ...]]:
        resolved_headers = getattr(runtime.resolved, "headers", {}) or {}
        headers = tuple(sorted(resolved_headers.items()))
        return runtime.resolved.url, headers

    async def resolve_session_binding(
        self,
        *,
        runtime: A2ARuntime,
    ) -> ResolvedSessionBindingExtension:
        cache_key = self._session_binding_cache_key(runtime)
        now = time.monotonic()
        async with self._session_binding_cache_lock:
            cached = self._session_binding_cache.get(cache_key)
            if cached and cached.expires_at > now:
                return cached.resolved

        card = await self._support.fetch_card(runtime)
        resolved = resolve_session_binding(card)
        async with self._session_binding_cache_lock:
            self._session_binding_cache[cache_key] = _SessionBindingCacheEntry(
                resolved=resolved,
                expires_at=now + _SESSION_BINDING_CACHE_TTL_SECONDS,
            )
        return resolved

    async def list_sessions(
        self,
        *,
        runtime: A2ARuntime,
        page: int,
        size: Optional[int],
        query: Optional[Dict[str, Any]],
        include_raw: bool = False,
    ) -> ExtensionCallResult:
        return await self._session_extensions.list_sessions(
            runtime=runtime,
            page=page,
            size=size,
            query=query,
            include_raw=include_raw,
        )

    async def get_session_messages(
        self,
        *,
        runtime: A2ARuntime,
        session_id: str,
        page: int,
        size: Optional[int],
        query: Optional[Dict[str, Any]],
        include_raw: bool = False,
    ) -> ExtensionCallResult:
        return await self._session_extensions.get_session_messages(
            runtime=runtime,
            session_id=session_id,
            page=page,
            size=size,
            query=query,
            include_raw=include_raw,
        )

    async def continue_session(
        self,
        *,
        runtime: A2ARuntime,
        session_id: str,
    ) -> ExtensionCallResult:
        return await self._session_extensions.continue_session(
            runtime=runtime,
            session_id=session_id,
        )

    async def prompt_session_async(
        self,
        *,
        runtime: A2ARuntime,
        session_id: str,
        request_payload: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        return await self._session_extensions.prompt_session_async(
            runtime=runtime,
            session_id=session_id,
            request_payload=request_payload,
            metadata=metadata,
        )

    async def list_opencode_providers(
        self,
        *,
        runtime: A2ARuntime,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        return await self._opencode_discovery.list_opencode_providers(
            runtime=runtime,
            metadata=metadata,
        )

    async def list_model_providers(
        self,
        *,
        runtime: A2ARuntime,
        session_metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        return await self._opencode_discovery.list_model_providers(
            runtime=runtime,
            session_metadata=session_metadata,
        )

    async def list_opencode_models(
        self,
        *,
        runtime: A2ARuntime,
        provider_id: str | None = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        return await self._opencode_discovery.list_opencode_models(
            runtime=runtime,
            provider_id=provider_id,
            metadata=metadata,
        )

    async def list_models(
        self,
        *,
        runtime: A2ARuntime,
        provider_id: str | None = None,
        session_metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        return await self._opencode_discovery.list_models(
            runtime=runtime,
            provider_id=provider_id,
            session_metadata=session_metadata,
        )

    async def reply_permission_interrupt(
        self,
        *,
        runtime: A2ARuntime,
        request_id: str,
        reply: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        return await self._interrupt_extensions.reply_permission_interrupt(
            runtime=runtime,
            request_id=request_id,
            reply=reply,
            metadata=metadata,
        )

    async def reply_question_interrupt(
        self,
        *,
        runtime: A2ARuntime,
        request_id: str,
        answers: list[list[str]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        return await self._interrupt_extensions.reply_question_interrupt(
            runtime=runtime,
            request_id=request_id,
            answers=answers,
            metadata=metadata,
        )

    async def reject_question_interrupt(
        self,
        *,
        runtime: A2ARuntime,
        request_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        return await self._interrupt_extensions.reject_question_interrupt(
            runtime=runtime,
            request_id=request_id,
            metadata=metadata,
        )


_service_instance: Optional[A2AExtensionsService] = None


def get_a2a_extensions_service() -> A2AExtensionsService:
    global _service_instance
    if _service_instance is None:
        _service_instance = A2AExtensionsService()
        logger.info("A2A extensions service initialised")
    return _service_instance


async def shutdown_a2a_extensions_service() -> None:
    global _service_instance
    if _service_instance is None:
        return
    await _service_instance.shutdown()
    _service_instance = None


__all__ = [
    "A2AExtensionsService",
    "ExtensionCallResult",
    "get_a2a_extensions_service",
    "shutdown_a2a_extensions_service",
    "A2AExtensionUpstreamError",
]
