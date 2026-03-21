"""Service facade for A2A Agent Card extensions."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional

from app.core.logging import get_logger
from app.features.personal_agents.runtime import A2ARuntime
from app.integrations.a2a_extensions.errors import (
    A2AExtensionContractError,
    A2AExtensionNotSupportedError,
    A2AExtensionUpstreamError,
)
from app.integrations.a2a_extensions.interrupt_callback import (
    resolve_interrupt_callback,
)
from app.integrations.a2a_extensions.interrupt_extension_service import (
    InterruptExtensionService,
)
from app.integrations.a2a_extensions.opencode_discovery_service import (
    OpencodeDiscoveryService,
)
from app.integrations.a2a_extensions.opencode_provider_discovery import (
    resolve_opencode_provider_discovery,
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
from app.integrations.a2a_extensions.stream_hints import resolve_stream_hints
from app.integrations.a2a_extensions.types import (
    ResolvedInterruptCallbackExtension,
    ResolvedProviderDiscoveryExtension,
    ResolvedSessionBindingExtension,
    ResolvedStreamHintsExtension,
)

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
class InterruptCallbackCapabilitySnapshot:
    status: Literal["supported", "unsupported", "invalid"]
    ext: ResolvedInterruptCallbackExtension | None = None
    jsonrpc_url: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderDiscoveryCapabilitySnapshot:
    status: Literal["supported", "unsupported", "invalid"]
    ext: ResolvedProviderDiscoveryExtension | None = None
    jsonrpc_url: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class StreamHintsCapabilitySnapshot:
    status: Literal["supported", "unsupported", "invalid"]
    ext: ResolvedStreamHintsExtension | None = None
    error: str | None = None
    meta: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ResolvedCapabilitySnapshot:
    session_query: SessionQueryCapabilitySnapshot
    session_binding: SessionBindingCapabilitySnapshot
    interrupt_callback: InterruptCallbackCapabilitySnapshot
    provider_discovery: ProviderDiscoveryCapabilitySnapshot
    stream_hints: StreamHintsCapabilitySnapshot


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

    def _build_interrupt_callback_snapshot(
        self, card: Any
    ) -> InterruptCallbackCapabilitySnapshot:
        try:
            ext = resolve_interrupt_callback(card)
        except A2AExtensionNotSupportedError as exc:
            return InterruptCallbackCapabilitySnapshot(
                status="unsupported",
                error=str(exc),
            )
        except A2AExtensionContractError as exc:
            return InterruptCallbackCapabilitySnapshot(
                status="invalid",
                error=str(exc),
            )

        return InterruptCallbackCapabilitySnapshot(
            status="supported",
            ext=ext,
            jsonrpc_url=self._support.ensure_outbound_allowed(
                ext.jsonrpc.url, purpose="JSON-RPC interface URL"
            ),
        )

    def _build_provider_discovery_snapshot(
        self, card: Any
    ) -> ProviderDiscoveryCapabilitySnapshot:
        try:
            ext = resolve_opencode_provider_discovery(card)
        except A2AExtensionNotSupportedError as exc:
            return ProviderDiscoveryCapabilitySnapshot(
                status="unsupported",
                error=str(exc),
            )
        except A2AExtensionContractError as exc:
            return ProviderDiscoveryCapabilitySnapshot(
                status="invalid",
                error=str(exc),
            )

        return ProviderDiscoveryCapabilitySnapshot(
            status="supported",
            ext=ext,
            jsonrpc_url=self._support.ensure_outbound_allowed(
                ext.jsonrpc.url, purpose="JSON-RPC interface URL"
            ),
        )

    @staticmethod
    def _build_stream_hints_snapshot(card: Any) -> StreamHintsCapabilitySnapshot:
        try:
            ext = resolve_stream_hints(card)
        except A2AExtensionNotSupportedError as exc:
            return StreamHintsCapabilitySnapshot(
                status="unsupported",
                error=str(exc),
                meta={
                    "stream_hints_declared": False,
                    "stream_hints_mode": "compat_fallback",
                    "stream_hints_fallback_used": True,
                },
            )
        except A2AExtensionContractError as exc:
            return StreamHintsCapabilitySnapshot(
                status="invalid",
                error=str(exc),
                meta={
                    "stream_hints_declared": True,
                    "stream_hints_mode": "compat_fallback",
                    "stream_hints_fallback_used": True,
                    "stream_hints_contract_error": str(exc),
                },
            )

        return StreamHintsCapabilitySnapshot(
            status="supported",
            ext=ext,
            meta={
                "stream_hints_declared": True,
                "stream_hints_uri": ext.uri,
                "stream_hints_mode": "declared_contract",
                "stream_hints_fallback_used": False,
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
            interrupt_callback=self._build_interrupt_callback_snapshot(card),
            provider_discovery=self._build_provider_discovery_snapshot(card),
            stream_hints=self._build_stream_hints_snapshot(card),
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

    @staticmethod
    def _require_interrupt_callback_capability(
        snapshot: InterruptCallbackCapabilitySnapshot,
    ) -> tuple[ResolvedInterruptCallbackExtension, str]:
        if snapshot.ext is not None and snapshot.jsonrpc_url is not None:
            return snapshot.ext, snapshot.jsonrpc_url
        if snapshot.status == "invalid":
            raise A2AExtensionContractError(
                snapshot.error or "Shared interrupt callback contract is invalid"
            )
        raise A2AExtensionNotSupportedError(
            snapshot.error or "Shared interrupt callback extension not found"
        )

    @staticmethod
    def _require_provider_discovery_capability(
        snapshot: ProviderDiscoveryCapabilitySnapshot,
    ) -> tuple[ResolvedProviderDiscoveryExtension, str]:
        if snapshot.ext is not None and snapshot.jsonrpc_url is not None:
            return snapshot.ext, snapshot.jsonrpc_url
        if snapshot.status == "invalid":
            raise A2AExtensionContractError(
                snapshot.error or "Provider discovery contract is invalid"
            )
        raise A2AExtensionNotSupportedError(
            snapshot.error or "Provider discovery extension not found"
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
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        ext, jsonrpc_url = self._require_provider_discovery_capability(
            snapshot.provider_discovery
        )
        return await self._opencode_discovery.list_model_providers(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            session_metadata=session_metadata,
        )

    async def list_models(
        self,
        *,
        runtime: A2ARuntime,
        provider_id: str | None = None,
        session_metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        ext, jsonrpc_url = self._require_provider_discovery_capability(
            snapshot.provider_discovery
        )
        return await self._opencode_discovery.list_models(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
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
        (
            resolved_request_id,
            resolved_reply,
            normalized_metadata,
        ) = self._interrupt_extensions.prepare_reply_permission_interrupt(
            request_id=request_id,
            reply=reply,
            metadata=metadata,
        )
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        ext, jsonrpc_url = self._require_interrupt_callback_capability(
            snapshot.interrupt_callback
        )
        return await self._interrupt_extensions.reply_permission_interrupt(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            request_id=resolved_request_id,
            reply=resolved_reply,
            metadata=normalized_metadata,
        )

    async def reply_question_interrupt(
        self,
        *,
        runtime: A2ARuntime,
        request_id: str,
        answers: list[list[str]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        (
            resolved_request_id,
            resolved_answers,
            normalized_metadata,
        ) = self._interrupt_extensions.prepare_reply_question_interrupt(
            request_id=request_id,
            answers=answers,
            metadata=metadata,
        )
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        ext, jsonrpc_url = self._require_interrupt_callback_capability(
            snapshot.interrupt_callback
        )
        return await self._interrupt_extensions.reply_question_interrupt(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            request_id=resolved_request_id,
            answers=resolved_answers,
            metadata=normalized_metadata,
        )

    async def reject_question_interrupt(
        self,
        *,
        runtime: A2ARuntime,
        request_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        (
            resolved_request_id,
            normalized_metadata,
        ) = self._interrupt_extensions.prepare_reject_question_interrupt(
            request_id=request_id,
            metadata=metadata,
        )
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        ext, jsonrpc_url = self._require_interrupt_callback_capability(
            snapshot.interrupt_callback
        )
        return await self._interrupt_extensions.reject_question_interrupt(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            request_id=resolved_request_id,
            metadata=normalized_metadata,
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
    "InterruptCallbackCapabilitySnapshot",
    "ProviderDiscoveryCapabilitySnapshot",
    "ResolvedCapabilitySnapshot",
    "SessionBindingCapabilitySnapshot",
    "SessionQueryCapabilitySnapshot",
    "get_a2a_extensions_service",
    "shutdown_a2a_extensions_service",
    "A2AExtensionUpstreamError",
]
