"""Service facade for A2A Agent Card extensions."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional

from app.core.logging import get_logger
from app.integrations.a2a_extensions.errors import (
    A2AExtensionContractError,
    A2AExtensionNotSupportedError,
    A2AExtensionUpstreamError,
)
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
from app.integrations.a2a_extensions.session_query_runtime_selection import (
    ResolvedSessionQueryRuntimeCapability,
    resolve_runtime_session_query,
)
from app.integrations.a2a_extensions.shared_support import (
    A2AExtensionSupport,
)
from app.integrations.a2a_extensions.types import ResolvedSessionBindingExtension
from app.services.a2a_runtime import A2ARuntime

logger = get_logger(__name__)
_CAPABILITY_SNAPSHOT_CACHE_TTL_SECONDS = 300.0


@dataclass(frozen=True, slots=True)
class SessionQueryCapabilitySnapshot:
    status: Literal["supported", "unsupported", "invalid"]
    capability: ResolvedSessionQueryRuntimeCapability | None = None
    error: str | None = None

    @property
    def selection_meta(self) -> dict[str, Any]:
        if self.capability is None:
            return {}
        return {
            "session_query_contract_mode": self.capability.contract_mode,
            "session_query_selection_mode": self.capability.selection_mode,
        }


@dataclass(frozen=True, slots=True)
class SessionBindingCapabilitySnapshot:
    status: Literal["supported", "unsupported", "invalid"]
    ext: ResolvedSessionBindingExtension | None = None
    error: str | None = None
    meta: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ResolvedCapabilitySnapshot:
    session_query: SessionQueryCapabilitySnapshot
    session_binding: SessionBindingCapabilitySnapshot


@dataclass(slots=True)
class _CapabilitySnapshotCacheEntry:
    snapshot: ResolvedCapabilitySnapshot
    expires_at: float


class A2AExtensionsService:
    def __init__(self) -> None:
        self._support = A2AExtensionSupport()
        self._session_extensions = SessionExtensionService(self._support)
        self._interrupt_extensions = InterruptExtensionService(self._support)
        self._opencode_discovery = OpencodeDiscoveryService(self._support)
        self._capability_snapshot_cache_lock = asyncio.Lock()
        self._capability_snapshot_cache: dict[
            tuple[str, tuple[tuple[str, str], ...]],
            _CapabilitySnapshotCacheEntry,
        ] = {}

    async def shutdown(self) -> None:
        await self._support.shutdown()
        async with self._capability_snapshot_cache_lock:
            self._capability_snapshot_cache.clear()

    @staticmethod
    def _capability_snapshot_cache_key(
        runtime: A2ARuntime,
    ) -> tuple[str, tuple[tuple[str, str], ...]]:
        resolved_headers = getattr(runtime.resolved, "headers", {}) or {}
        headers = tuple(sorted(resolved_headers.items()))
        return runtime.resolved.url, headers

    @staticmethod
    def _build_session_query_snapshot(card: Any) -> SessionQueryCapabilitySnapshot:
        try:
            capability = resolve_runtime_session_query(card)
        except A2AExtensionNotSupportedError as exc:
            return SessionQueryCapabilitySnapshot(
                status="unsupported",
                error=str(exc),
            )
        except A2AExtensionContractError as exc:
            return SessionQueryCapabilitySnapshot(
                status="invalid",
                error=str(exc),
            )

        return SessionQueryCapabilitySnapshot(
            status="supported",
            capability=capability,
        )

    @staticmethod
    def _build_session_binding_snapshot(card: Any) -> SessionBindingCapabilitySnapshot:
        try:
            ext = resolve_session_binding(card)
        except A2AExtensionNotSupportedError as exc:
            return SessionBindingCapabilitySnapshot(
                status="unsupported",
                error=str(exc),
                meta={
                    "session_binding_declared": False,
                    "session_binding_mode": "compat_fallback",
                    "session_binding_fallback_used": True,
                },
            )
        except A2AExtensionContractError as exc:
            return SessionBindingCapabilitySnapshot(
                status="invalid",
                error=str(exc),
                meta={
                    "session_binding_declared": True,
                    "session_binding_mode": "compat_fallback",
                    "session_binding_fallback_used": True,
                    "session_binding_contract_error": str(exc),
                },
            )

        return SessionBindingCapabilitySnapshot(
            status="supported",
            ext=ext,
            meta={
                "session_binding_declared": True,
                "session_binding_uri": ext.uri,
                "session_binding_mode": (
                    "compat_fallback" if ext.legacy_uri_used else "declared_contract"
                ),
                "session_binding_fallback_used": ext.legacy_uri_used,
            },
        )

    async def resolve_capability_snapshot(
        self,
        *,
        runtime: A2ARuntime,
    ) -> ResolvedCapabilitySnapshot:
        cache_key = self._capability_snapshot_cache_key(runtime)
        now = time.monotonic()
        async with self._capability_snapshot_cache_lock:
            cached = self._capability_snapshot_cache.get(cache_key)
            if cached and cached.expires_at > now:
                return cached.snapshot

        card = await self._support.fetch_card(runtime)
        snapshot = ResolvedCapabilitySnapshot(
            session_query=self._build_session_query_snapshot(card),
            session_binding=self._build_session_binding_snapshot(card),
        )
        async with self._capability_snapshot_cache_lock:
            self._capability_snapshot_cache[cache_key] = _CapabilitySnapshotCacheEntry(
                snapshot=snapshot,
                expires_at=now + _CAPABILITY_SNAPSHOT_CACHE_TTL_SECONDS,
            )
        return snapshot

    @staticmethod
    def _require_session_query_capability(
        snapshot: SessionQueryCapabilitySnapshot,
    ) -> ResolvedSessionQueryRuntimeCapability:
        if snapshot.capability is not None:
            return snapshot.capability
        if snapshot.status == "invalid":
            raise A2AExtensionContractError(
                snapshot.error or "Shared session query contract is invalid"
            )
        raise A2AExtensionNotSupportedError(
            snapshot.error or "Shared session query extension not supported by Hub"
        )

    async def resolve_session_binding(
        self,
        *,
        runtime: A2ARuntime,
    ) -> ResolvedSessionBindingExtension:
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        if snapshot.session_binding.ext is not None:
            return snapshot.session_binding.ext
        if snapshot.session_binding.status == "invalid":
            raise A2AExtensionContractError(
                snapshot.session_binding.error
                or "Shared session binding contract is invalid"
            )
        raise A2AExtensionNotSupportedError(
            snapshot.session_binding.error
            or "Shared session binding extension not found"
        )

    async def list_sessions(
        self,
        *,
        runtime: A2ARuntime,
        page: int,
        size: Optional[int],
        query: Optional[Dict[str, Any]],
        include_raw: bool = False,
    ) -> ExtensionCallResult:
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        capability = self._require_session_query_capability(snapshot.session_query)
        return await self._session_extensions.list_sessions(
            runtime=runtime,
            ext=capability.ext,
            selection_meta=snapshot.session_query.selection_meta,
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
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        capability = self._require_session_query_capability(snapshot.session_query)
        return await self._session_extensions.get_session_messages(
            runtime=runtime,
            ext=capability.ext,
            selection_meta=snapshot.session_query.selection_meta,
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
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        capability = self._require_session_query_capability(snapshot.session_query)
        return await self._session_extensions.continue_session(
            runtime=runtime,
            ext=capability.ext,
            selection_meta=snapshot.session_query.selection_meta,
            binding_meta=dict(snapshot.session_binding.meta or {}),
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
        self._session_extensions.prepare_prompt_session_async(
            session_id=session_id,
            request_payload=request_payload,
            metadata=metadata,
        )
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        capability = self._require_session_query_capability(snapshot.session_query)
        return await self._session_extensions.prompt_session_async(
            runtime=runtime,
            ext=capability.ext,
            selection_meta=snapshot.session_query.selection_meta,
            session_id=session_id,
            request_payload=request_payload,
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
    "ResolvedCapabilitySnapshot",
    "SessionBindingCapabilitySnapshot",
    "SessionQueryCapabilitySnapshot",
    "get_a2a_extensions_service",
    "shutdown_a2a_extensions_service",
    "A2AExtensionUpstreamError",
]
