"""Service facade for A2A Agent Card extensions."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional

from app.core.logging import get_logger
from app.features.personal_agents.runtime import A2ARuntime
from app.integrations.a2a_extensions.codex_declaration_diagnostics import (
    diagnose_codex_discovery_fallback,
)
from app.integrations.a2a_extensions.codex_discovery_service import (
    CodexDiscoveryService,
)
from app.integrations.a2a_extensions.compatibility_profile import (
    resolve_compatibility_profile,
)
from app.integrations.a2a_extensions.contract_utils import resolve_jsonrpc_interface
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
from app.integrations.a2a_extensions.interrupt_recovery import (
    resolve_interrupt_recovery,
)
from app.integrations.a2a_extensions.interrupt_recovery_service import (
    InterruptRecoveryService,
)
from app.integrations.a2a_extensions.invoke_metadata import resolve_invoke_metadata
from app.integrations.a2a_extensions.model_selection import resolve_model_selection
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
    ResolvedCompatibilityProfileExtension,
    ResolvedConditionalMethodAvailability,
    ResolvedInterruptCallbackExtension,
    ResolvedInterruptRecoveryExtension,
    ResolvedInvokeMetadataExtension,
    ResolvedModelSelectionExtension,
    ResolvedProviderDiscoveryExtension,
    ResolvedSessionBindingExtension,
    ResolvedStreamHintsExtension,
    ResolvedWireContractExtension,
)
from app.integrations.a2a_extensions.wire_contract import resolve_wire_contract

logger = get_logger(__name__)
_CAPABILITY_SNAPSHOT_CACHE_TTL_SECONDS = 300.0
_CODEX_DISCOVERY_METHODS = {
    "skillsList": "codex.discovery.skills.list",
    "appsList": "codex.discovery.apps.list",
    "pluginsList": "codex.discovery.plugins.list",
    "pluginsRead": "codex.discovery.plugins.read",
    "watch": "codex.discovery.watch",
}
_CODEX_DISCOVERY_HUB_CONSUMPTION = {
    "skillsList": True,
    "appsList": True,
    "pluginsList": True,
    "pluginsRead": True,
    "watch": False,
}
_CODEX_EXEC_METHODS = {
    "start": "codex.exec.start",
    "write": "codex.exec.write",
    "resize": "codex.exec.resize",
    "terminate": "codex.exec.terminate",
}
_CODEX_THREAD_WATCH_METHOD = "codex.threads.watch"


@dataclass(frozen=True, slots=True)
class DeclaredMethodCapabilitySnapshot:
    declared: bool
    consumed_by_hub: bool
    method: str | None = None


@dataclass(frozen=True, slots=True)
class DeclaredMethodCollectionCapabilitySnapshot:
    declared: bool
    consumed_by_hub: bool
    status: Literal[
        "unsupported",
        "declared_not_consumed",
        "partially_consumed",
        "supported",
        "unsupported_by_design",
    ]
    methods: dict[str, DeclaredMethodCapabilitySnapshot]
    jsonrpc_url: str | None = None
    declaration_source: (
        Literal[
            "none",
            "wire_contract",
            "wire_contract_fallback",
            "extension_method_hint",
            "extension_uri_hint",
        ]
        | None
    ) = None
    declaration_confidence: Literal["none", "fallback", "authoritative"] | None = None
    negotiation_state: (
        Literal["supported", "missing", "invalid", "unsupported"] | None
    ) = None
    diagnostic_note: str | None = None


@dataclass(frozen=True, slots=True)
class DeclaredSingleMethodCapabilitySnapshot:
    declared: bool
    consumed_by_hub: bool
    status: Literal["unsupported", "unsupported_by_design"]
    method: str | None = None
    jsonrpc_url: str | None = None


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
            "session_query_declared_contract_family": (
                self.capability.declared_contract_family
            ),
            "session_query_normalized_contract_family": (
                self.capability.normalized_contract_family
            ),
            "session_query_selection_mode": self.capability.selection_mode,
        }


@dataclass(frozen=True, slots=True)
class SessionBindingCapabilitySnapshot:
    status: Literal["supported", "unsupported", "invalid"]
    ext: ResolvedSessionBindingExtension | None = None
    error: str | None = None
    meta: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class InvokeMetadataCapabilitySnapshot:
    status: Literal["supported", "unsupported", "invalid"]
    ext: ResolvedInvokeMetadataExtension | None = None
    error: str | None = None
    meta: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class InterruptCallbackCapabilitySnapshot:
    status: Literal["supported", "unsupported", "invalid"]
    ext: ResolvedInterruptCallbackExtension | None = None
    jsonrpc_url: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class InterruptRecoveryCapabilitySnapshot:
    status: Literal["supported", "unsupported", "invalid"]
    ext: ResolvedInterruptRecoveryExtension | None = None
    jsonrpc_url: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderDiscoveryCapabilitySnapshot:
    status: Literal["supported", "unsupported", "invalid"]
    ext: ResolvedProviderDiscoveryExtension | None = None
    jsonrpc_url: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ModelSelectionCapabilitySnapshot:
    status: Literal["supported", "unsupported", "invalid"]
    ext: ResolvedModelSelectionExtension | None = None
    error: str | None = None
    meta: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class StreamHintsCapabilitySnapshot:
    status: Literal["supported", "unsupported", "invalid"]
    ext: ResolvedStreamHintsExtension | None = None
    error: str | None = None
    meta: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class CompatibilityProfileCapabilitySnapshot:
    status: Literal["supported", "unsupported", "invalid"]
    ext: ResolvedCompatibilityProfileExtension | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class WireContractCapabilitySnapshot:
    status: Literal["supported", "unsupported", "invalid"]
    ext: ResolvedWireContractExtension | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedCapabilitySnapshot:
    session_query: SessionQueryCapabilitySnapshot
    session_binding: SessionBindingCapabilitySnapshot
    invoke_metadata: InvokeMetadataCapabilitySnapshot
    interrupt_callback: InterruptCallbackCapabilitySnapshot
    interrupt_recovery: InterruptRecoveryCapabilitySnapshot
    model_selection: ModelSelectionCapabilitySnapshot
    provider_discovery: ProviderDiscoveryCapabilitySnapshot
    stream_hints: StreamHintsCapabilitySnapshot
    wire_contract: WireContractCapabilitySnapshot
    compatibility_profile: CompatibilityProfileCapabilitySnapshot
    codex_discovery: DeclaredMethodCollectionCapabilitySnapshot
    codex_thread_watch: DeclaredSingleMethodCapabilitySnapshot
    codex_exec: DeclaredMethodCollectionCapabilitySnapshot


@dataclass(slots=True)
class _CapabilitySnapshotCacheEntry:
    snapshot: ResolvedCapabilitySnapshot
    expires_at: float


class A2AExtensionsService:
    def __init__(self) -> None:
        self._support = A2AExtensionSupport()
        self._session_extensions = SessionExtensionService(self._support)
        self._interrupt_extensions = InterruptExtensionService(self._support)
        self._interrupt_recovery = InterruptRecoveryService(self._support)
        self._opencode_discovery = OpencodeDiscoveryService(self._support)
        self._codex_discovery = CodexDiscoveryService(self._support)
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

    @staticmethod
    def _build_invoke_metadata_snapshot(card: Any) -> InvokeMetadataCapabilitySnapshot:
        try:
            ext = resolve_invoke_metadata(card)
        except A2AExtensionNotSupportedError as exc:
            return InvokeMetadataCapabilitySnapshot(
                status="unsupported",
                error=str(exc),
                meta={
                    "invoke_metadata_declared": False,
                    "invoke_metadata_consumed_by_hub": True,
                },
            )
        except A2AExtensionContractError as exc:
            return InvokeMetadataCapabilitySnapshot(
                status="invalid",
                error=str(exc),
                meta={
                    "invoke_metadata_declared": True,
                    "invoke_metadata_consumed_by_hub": True,
                    "invoke_metadata_contract_error": str(exc),
                },
            )

        return InvokeMetadataCapabilitySnapshot(
            status="supported",
            ext=ext,
            meta={
                "invoke_metadata_declared": True,
                "invoke_metadata_consumed_by_hub": True,
                "invoke_metadata_uri": ext.uri,
                "invoke_metadata_field_count": len(ext.fields),
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

    def _build_interrupt_recovery_snapshot(
        self, card: Any
    ) -> InterruptRecoveryCapabilitySnapshot:
        try:
            ext = resolve_interrupt_recovery(card)
        except A2AExtensionNotSupportedError as exc:
            return InterruptRecoveryCapabilitySnapshot(
                status="unsupported",
                error=str(exc),
            )
        except A2AExtensionContractError as exc:
            return InterruptRecoveryCapabilitySnapshot(
                status="invalid",
                error=str(exc),
            )

        return InterruptRecoveryCapabilitySnapshot(
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
    def _build_model_selection_snapshot(card: Any) -> ModelSelectionCapabilitySnapshot:
        try:
            ext = resolve_model_selection(card)
        except A2AExtensionNotSupportedError as exc:
            return ModelSelectionCapabilitySnapshot(
                status="unsupported",
                error=str(exc),
                meta={
                    "model_selection_declared": False,
                    "model_selection_applies_to_main_chat": False,
                },
            )
        except A2AExtensionContractError as exc:
            return ModelSelectionCapabilitySnapshot(
                status="invalid",
                error=str(exc),
                meta={
                    "model_selection_declared": True,
                    "model_selection_applies_to_main_chat": False,
                    "model_selection_contract_error": str(exc),
                },
            )

        applies_to_main_chat = bool(
            {"message/send", "message/stream"} & set(ext.applies_to_methods)
        )
        return ModelSelectionCapabilitySnapshot(
            status="supported",
            ext=ext,
            meta={
                "model_selection_declared": True,
                "model_selection_applies_to_main_chat": applies_to_main_chat,
                "model_selection_metadata_field": ext.metadata_field,
            },
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

    @staticmethod
    def _build_compatibility_profile_snapshot(
        card: Any,
    ) -> CompatibilityProfileCapabilitySnapshot:
        try:
            ext = resolve_compatibility_profile(card)
        except A2AExtensionNotSupportedError as exc:
            return CompatibilityProfileCapabilitySnapshot(
                status="unsupported",
                error=str(exc),
            )
        except A2AExtensionContractError as exc:
            return CompatibilityProfileCapabilitySnapshot(
                status="invalid",
                error=str(exc),
            )

        return CompatibilityProfileCapabilitySnapshot(
            status="supported",
            ext=ext,
        )

    @staticmethod
    def _build_wire_contract_snapshot(
        card: Any,
    ) -> WireContractCapabilitySnapshot:
        try:
            ext = resolve_wire_contract(card)
        except A2AExtensionNotSupportedError as exc:
            return WireContractCapabilitySnapshot(
                status="unsupported",
                error=str(exc),
            )
        except A2AExtensionContractError as exc:
            return WireContractCapabilitySnapshot(
                status="invalid",
                error=str(exc),
            )

        return WireContractCapabilitySnapshot(
            status="supported",
            ext=ext,
        )

    @staticmethod
    def _declared_wire_contract_methods(
        snapshot: WireContractCapabilitySnapshot,
    ) -> frozenset[str]:
        if snapshot.status != "supported" or snapshot.ext is None:
            return frozenset()
        return frozenset(snapshot.ext.all_jsonrpc_methods)

    @classmethod
    def _build_declared_method_collection_snapshot(
        cls,
        *,
        wire_contract: WireContractCapabilitySnapshot,
        method_map: dict[str, str],
        hub_consumption: dict[str, bool],
        unsupported_status_when_declared: Literal[
            "declared_not_consumed", "unsupported_by_design"
        ],
        jsonrpc_url: str | None,
        declaration_source: (
            Literal[
                "none",
                "wire_contract",
                "wire_contract_fallback",
                "extension_method_hint",
                "extension_uri_hint",
            ]
            | None
        ) = None,
        declaration_confidence: (
            Literal["none", "fallback", "authoritative"] | None
        ) = None,
        negotiation_state: (
            Literal["supported", "missing", "invalid", "unsupported"] | None
        ) = None,
        diagnostic_note: str | None = None,
    ) -> DeclaredMethodCollectionCapabilitySnapshot:
        declared_methods = cls._declared_wire_contract_methods(wire_contract)
        methods = {
            key: DeclaredMethodCapabilitySnapshot(
                declared=method_name in declared_methods,
                consumed_by_hub=bool(hub_consumption.get(key, False))
                and method_name in declared_methods,
                method=method_name if method_name in declared_methods else None,
            )
            for key, method_name in method_map.items()
        }
        declared = any(item.declared for item in methods.values())
        consumed = any(
            item.declared and item.consumed_by_hub for item in methods.values()
        )
        unconsumed = any(
            item.declared and not item.consumed_by_hub for item in methods.values()
        )
        if not declared:
            status: Literal[
                "unsupported",
                "declared_not_consumed",
                "partially_consumed",
                "supported",
                "unsupported_by_design",
            ] = "unsupported"
        elif consumed and unconsumed:
            status = "partially_consumed"
        elif consumed:
            status = "supported"
        else:
            status = unsupported_status_when_declared
        return DeclaredMethodCollectionCapabilitySnapshot(
            declared=declared,
            consumed_by_hub=consumed,
            status=status,
            methods=methods,
            jsonrpc_url=jsonrpc_url,
            declaration_source=declaration_source,
            declaration_confidence=declaration_confidence,
            negotiation_state=negotiation_state,
            diagnostic_note=diagnostic_note,
        )

    @classmethod
    def _build_codex_discovery_snapshot(
        cls,
        card: Any,
        wire_contract: WireContractCapabilitySnapshot,
        *,
        jsonrpc_url: str | None,
    ) -> DeclaredMethodCollectionCapabilitySnapshot:
        if wire_contract.status == "supported":
            return cls._build_declared_method_collection_snapshot(
                wire_contract=wire_contract,
                method_map=_CODEX_DISCOVERY_METHODS,
                hub_consumption=_CODEX_DISCOVERY_HUB_CONSUMPTION,
                unsupported_status_when_declared="declared_not_consumed",
                jsonrpc_url=jsonrpc_url,
                declaration_source="wire_contract",
                declaration_confidence="authoritative",
                negotiation_state="supported",
            )

        fallback = diagnose_codex_discovery_fallback(
            card,
            wire_contract_status=wire_contract.status,
        )
        if fallback.declared:
            methods = {
                key: DeclaredMethodCapabilitySnapshot(
                    declared=method_name in fallback.method_names,
                    consumed_by_hub=False,
                    method=(
                        method_name if method_name in fallback.method_names else None
                    ),
                )
                for key, method_name in _CODEX_DISCOVERY_METHODS.items()
            }
            return DeclaredMethodCollectionCapabilitySnapshot(
                declared=True,
                consumed_by_hub=False,
                status="unsupported",
                methods=methods,
                jsonrpc_url=None,
                declaration_source=fallback.source,
                declaration_confidence=fallback.confidence,
                negotiation_state=fallback.negotiation_state,
                diagnostic_note=fallback.note,
            )

        return cls._build_declared_method_collection_snapshot(
            wire_contract=wire_contract,
            method_map=_CODEX_DISCOVERY_METHODS,
            hub_consumption=_CODEX_DISCOVERY_HUB_CONSUMPTION,
            unsupported_status_when_declared="declared_not_consumed",
            jsonrpc_url=None,
            declaration_source=fallback.source,
            declaration_confidence=fallback.confidence,
            negotiation_state=fallback.negotiation_state,
            diagnostic_note=fallback.note,
        )

    @classmethod
    def _build_codex_exec_snapshot(
        cls,
        wire_contract: WireContractCapabilitySnapshot,
        *,
        jsonrpc_url: str | None,
    ) -> DeclaredMethodCollectionCapabilitySnapshot:
        return cls._build_declared_method_collection_snapshot(
            wire_contract=wire_contract,
            method_map=_CODEX_EXEC_METHODS,
            hub_consumption={},
            unsupported_status_when_declared="unsupported_by_design",
            jsonrpc_url=jsonrpc_url,
        )

    @classmethod
    def _build_codex_thread_watch_snapshot(
        cls,
        wire_contract: WireContractCapabilitySnapshot,
        *,
        jsonrpc_url: str | None,
    ) -> DeclaredSingleMethodCapabilitySnapshot:
        declared_methods = cls._declared_wire_contract_methods(wire_contract)
        declared = _CODEX_THREAD_WATCH_METHOD in declared_methods
        return DeclaredSingleMethodCapabilitySnapshot(
            declared=declared,
            consumed_by_hub=False,
            status="unsupported_by_design" if declared else "unsupported",
            method=_CODEX_THREAD_WATCH_METHOD if declared else None,
            jsonrpc_url=jsonrpc_url,
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
        wire_contract = self._build_wire_contract_snapshot(card)
        jsonrpc_url = None
        try:
            jsonrpc_url = self._support.ensure_outbound_allowed(
                resolve_jsonrpc_interface(card).url,
                purpose="JSON-RPC interface URL",
            )
        except (A2AExtensionContractError, A2AExtensionUpstreamError):
            jsonrpc_url = None
        snapshot = ResolvedCapabilitySnapshot(
            session_query=self._build_session_query_snapshot(card),
            session_binding=self._build_session_binding_snapshot(card),
            invoke_metadata=self._build_invoke_metadata_snapshot(card),
            interrupt_callback=self._build_interrupt_callback_snapshot(card),
            interrupt_recovery=self._build_interrupt_recovery_snapshot(card),
            model_selection=self._build_model_selection_snapshot(card),
            provider_discovery=self._build_provider_discovery_snapshot(card),
            stream_hints=self._build_stream_hints_snapshot(card),
            wire_contract=wire_contract,
            compatibility_profile=self._build_compatibility_profile_snapshot(card),
            codex_discovery=self._build_codex_discovery_snapshot(
                card, wire_contract, jsonrpc_url=jsonrpc_url
            ),
            codex_thread_watch=self._build_codex_thread_watch_snapshot(
                wire_contract, jsonrpc_url=jsonrpc_url
            ),
            codex_exec=self._build_codex_exec_snapshot(
                wire_contract, jsonrpc_url=jsonrpc_url
            ),
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
    def _require_interrupt_recovery_capability(
        snapshot: InterruptRecoveryCapabilitySnapshot,
    ) -> tuple[ResolvedInterruptRecoveryExtension, str]:
        if snapshot.ext is not None and snapshot.jsonrpc_url is not None:
            return snapshot.ext, snapshot.jsonrpc_url
        if snapshot.status == "invalid":
            raise A2AExtensionContractError(
                snapshot.error or "Interrupt recovery contract is invalid"
            )
        raise A2AExtensionNotSupportedError(
            snapshot.error or "Interrupt recovery extension not found"
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

    @staticmethod
    def _require_declared_method_collection_capability(
        snapshot: DeclaredMethodCollectionCapabilitySnapshot,
        *,
        capability_name: str,
    ) -> tuple[DeclaredMethodCollectionCapabilitySnapshot, str]:
        if snapshot.declared and snapshot.jsonrpc_url:
            return snapshot, snapshot.jsonrpc_url
        if snapshot.declared:
            raise A2AExtensionContractError(
                f"{capability_name} is declared but no JSON-RPC interface URL is available"
            )
        raise A2AExtensionNotSupportedError(f"{capability_name} methods not declared")

    @staticmethod
    def _require_declared_method_capability(
        snapshot: DeclaredMethodCollectionCapabilitySnapshot,
        *,
        method_key: str,
        capability_name: str,
    ) -> DeclaredMethodCapabilitySnapshot:
        method = snapshot.methods[method_key]
        if method.declared and method.consumed_by_hub:
            return method
        if method.declared:
            raise A2AExtensionNotSupportedError(
                f"{capability_name} method {method_key} is declared but not consumed by Hub"
            )
        raise A2AExtensionNotSupportedError(
            f"{capability_name} method {method_key} is not declared"
        )

    @staticmethod
    def _build_wire_contract_preflight_error(
        *,
        error_code: Literal["method_disabled", "method_not_supported"],
        extension_uri: str,
        method_name: str,
        wire_contract: ResolvedWireContractExtension,
        conditional: ResolvedConditionalMethodAvailability | None = None,
    ) -> ExtensionCallResult:
        if conditional is not None:
            message = f"Method {method_name} is disabled by upstream deployment"
            upstream_error = {
                "message": message,
                "type": "METHOD_DISABLED",
                "method": method_name,
                "reason": conditional.reason,
            }
            if conditional.toggle:
                upstream_error["toggle"] = conditional.toggle
            return ExtensionCallResult(
                success=False,
                error_code=error_code,
                source="wire_contract",
                upstream_error=upstream_error,
                meta={
                    "extension_uri": extension_uri,
                    "wire_contract_uri": wire_contract.uri,
                    "wire_contract_preflight": "conditionally_available",
                    "method_name": method_name,
                },
            )

        unsupported = wire_contract.unsupported_method_error
        supported_methods = list(wire_contract.all_jsonrpc_methods)
        message = f"Unsupported method: {method_name}"
        return ExtensionCallResult(
            success=False,
            error_code=error_code,
            source="wire_contract",
            jsonrpc_code=unsupported.code,
            upstream_error={
                "message": message,
                "type": unsupported.type,
                "method": method_name,
                "supported_methods": supported_methods,
                "protocol_version": wire_contract.protocol_version,
            },
            meta={
                "extension_uri": extension_uri,
                "wire_contract_uri": wire_contract.uri,
                "wire_contract_preflight": "unsupported_method",
                "method_name": method_name,
            },
        )

    @classmethod
    def _preflight_wire_contract_method(
        cls,
        *,
        snapshot: WireContractCapabilitySnapshot,
        extension_uri: str,
        method_name: str | None,
    ) -> ExtensionCallResult | None:
        if not method_name or snapshot.ext is None or snapshot.status != "supported":
            return None

        wire_contract = snapshot.ext
        if method_name in wire_contract.all_jsonrpc_methods:
            return None

        conditional = wire_contract.conditionally_available_methods.get(method_name)
        if conditional is not None:
            return cls._build_wire_contract_preflight_error(
                error_code="method_disabled",
                extension_uri=extension_uri,
                method_name=method_name,
                wire_contract=wire_contract,
                conditional=conditional,
            )

        return cls._build_wire_contract_preflight_error(
            error_code="method_not_supported",
            extension_uri=extension_uri,
            method_name=method_name,
            wire_contract=wire_contract,
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

    async def resolve_invoke_metadata(
        self,
        *,
        runtime: A2ARuntime,
    ) -> ResolvedInvokeMetadataExtension:
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        if snapshot.invoke_metadata.ext is not None:
            return snapshot.invoke_metadata.ext
        if snapshot.invoke_metadata.status == "invalid":
            raise A2AExtensionContractError(
                snapshot.invoke_metadata.error or "Invoke metadata contract is invalid"
            )
        raise A2AExtensionNotSupportedError(
            snapshot.invoke_metadata.error or "Invoke metadata extension not found"
        )

    async def list_sessions(
        self,
        *,
        runtime: A2ARuntime,
        page: int,
        size: Optional[int],
        query: Optional[Dict[str, Any]],
        filters: Optional[Dict[str, Any]] = None,
        include_raw: bool = False,
    ) -> ExtensionCallResult:
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        capability = self._require_session_query_capability(snapshot.session_query)
        preflight = self._preflight_wire_contract_method(
            snapshot=snapshot.wire_contract,
            extension_uri=capability.ext.uri,
            method_name=capability.ext.methods.get("list_sessions"),
        )
        if preflight is not None:
            return preflight
        return await self._session_extensions.list_sessions(
            runtime=runtime,
            ext=capability.ext,
            selection_meta=snapshot.session_query.selection_meta,
            page=page,
            size=size,
            query=query,
            filters=filters,
            include_raw=include_raw,
        )

    async def get_session_messages(
        self,
        *,
        runtime: A2ARuntime,
        session_id: str,
        page: int,
        size: Optional[int],
        before: str | None,
        query: Optional[Dict[str, Any]],
        include_raw: bool = False,
    ) -> ExtensionCallResult:
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        capability = self._require_session_query_capability(snapshot.session_query)
        preflight = self._preflight_wire_contract_method(
            snapshot=snapshot.wire_contract,
            extension_uri=capability.ext.uri,
            method_name=capability.ext.methods.get("get_session_messages"),
        )
        if preflight is not None:
            return preflight
        return await self._session_extensions.get_session_messages(
            runtime=runtime,
            ext=capability.ext,
            selection_meta=snapshot.session_query.selection_meta,
            session_id=session_id,
            page=page,
            size=size,
            before=before,
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
        preflight = self._preflight_wire_contract_method(
            snapshot=snapshot.wire_contract,
            extension_uri=capability.ext.uri,
            method_name=capability.ext.methods.get("get_session_messages"),
        )
        if preflight is not None:
            return preflight
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
        preflight = self._preflight_wire_contract_method(
            snapshot=snapshot.wire_contract,
            extension_uri=capability.ext.uri,
            method_name=capability.ext.methods.get("prompt_async"),
        )
        if preflight is not None:
            return preflight
        return await self._session_extensions.prompt_session_async(
            runtime=runtime,
            ext=capability.ext,
            selection_meta=snapshot.session_query.selection_meta,
            session_id=session_id,
            request_payload=request_payload,
            metadata=metadata,
        )

    async def command_session(
        self,
        *,
        runtime: A2ARuntime,
        session_id: str,
        request_payload: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        self._session_extensions.prepare_session_command(
            session_id=session_id,
            request_payload=request_payload,
            metadata=metadata,
        )
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        capability = self._require_session_query_capability(snapshot.session_query)
        preflight = self._preflight_wire_contract_method(
            snapshot=snapshot.wire_contract,
            extension_uri=capability.ext.uri,
            method_name=capability.ext.methods.get("command"),
        )
        if preflight is not None:
            return preflight
        return await self._session_extensions.command_session(
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
        preflight = self._preflight_wire_contract_method(
            snapshot=snapshot.wire_contract,
            extension_uri=ext.uri,
            method_name=ext.methods.get("list_providers"),
        )
        if preflight is not None:
            return preflight
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
        preflight = self._preflight_wire_contract_method(
            snapshot=snapshot.wire_contract,
            extension_uri=ext.uri,
            method_name=ext.methods.get("list_models"),
        )
        if preflight is not None:
            return preflight
        return await self._opencode_discovery.list_models(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            provider_id=provider_id,
            session_metadata=session_metadata,
        )

    async def list_codex_skills(
        self,
        *,
        runtime: A2ARuntime,
    ) -> ExtensionCallResult:
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        capability, jsonrpc_url = self._require_declared_method_collection_capability(
            snapshot.codex_discovery,
            capability_name="Codex discovery",
        )
        method = self._require_declared_method_capability(
            capability,
            method_key="skillsList",
            capability_name="Codex discovery",
        )
        preflight = self._preflight_wire_contract_method(
            snapshot=snapshot.wire_contract,
            extension_uri=(
                snapshot.wire_contract.ext.uri
                if snapshot.wire_contract.ext is not None
                else "wire_contract"
            ),
            method_name=method.method,
        )
        if preflight is not None:
            return preflight
        return await self._codex_discovery.list_items(
            runtime=runtime,
            jsonrpc_url=jsonrpc_url,
            method_name=method.method or _CODEX_DISCOVERY_METHODS["skillsList"],
            kind="skill",
            list_key="skills",
            meta={
                "extension_uri": (
                    snapshot.wire_contract.ext.uri
                    if snapshot.wire_contract.ext is not None
                    else None
                ),
                "capability_area": "codex_discovery",
                "method_name": method.method,
            },
        )

    async def list_codex_apps(
        self,
        *,
        runtime: A2ARuntime,
    ) -> ExtensionCallResult:
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        capability, jsonrpc_url = self._require_declared_method_collection_capability(
            snapshot.codex_discovery,
            capability_name="Codex discovery",
        )
        method = self._require_declared_method_capability(
            capability,
            method_key="appsList",
            capability_name="Codex discovery",
        )
        preflight = self._preflight_wire_contract_method(
            snapshot=snapshot.wire_contract,
            extension_uri=(
                snapshot.wire_contract.ext.uri
                if snapshot.wire_contract.ext is not None
                else "wire_contract"
            ),
            method_name=method.method,
        )
        if preflight is not None:
            return preflight
        return await self._codex_discovery.list_items(
            runtime=runtime,
            jsonrpc_url=jsonrpc_url,
            method_name=method.method or _CODEX_DISCOVERY_METHODS["appsList"],
            kind="app",
            list_key="apps",
            meta={
                "extension_uri": (
                    snapshot.wire_contract.ext.uri
                    if snapshot.wire_contract.ext is not None
                    else None
                ),
                "capability_area": "codex_discovery",
                "method_name": method.method,
            },
        )

    async def list_codex_plugins(
        self,
        *,
        runtime: A2ARuntime,
    ) -> ExtensionCallResult:
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        capability, jsonrpc_url = self._require_declared_method_collection_capability(
            snapshot.codex_discovery,
            capability_name="Codex discovery",
        )
        method = self._require_declared_method_capability(
            capability,
            method_key="pluginsList",
            capability_name="Codex discovery",
        )
        preflight = self._preflight_wire_contract_method(
            snapshot=snapshot.wire_contract,
            extension_uri=(
                snapshot.wire_contract.ext.uri
                if snapshot.wire_contract.ext is not None
                else "wire_contract"
            ),
            method_name=method.method,
        )
        if preflight is not None:
            return preflight
        return await self._codex_discovery.list_items(
            runtime=runtime,
            jsonrpc_url=jsonrpc_url,
            method_name=method.method or _CODEX_DISCOVERY_METHODS["pluginsList"],
            kind="plugin",
            list_key="plugins",
            meta={
                "extension_uri": (
                    snapshot.wire_contract.ext.uri
                    if snapshot.wire_contract.ext is not None
                    else None
                ),
                "capability_area": "codex_discovery",
                "method_name": method.method,
            },
        )

    async def read_codex_plugin(
        self,
        *,
        runtime: A2ARuntime,
        plugin_id: str,
    ) -> ExtensionCallResult:
        resolved_plugin_id = plugin_id.strip()
        if not resolved_plugin_id:
            raise ValueError("plugin_id must be a non-empty string")
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        capability, jsonrpc_url = self._require_declared_method_collection_capability(
            snapshot.codex_discovery,
            capability_name="Codex discovery",
        )
        method = self._require_declared_method_capability(
            capability,
            method_key="pluginsRead",
            capability_name="Codex discovery",
        )
        preflight = self._preflight_wire_contract_method(
            snapshot=snapshot.wire_contract,
            extension_uri=(
                snapshot.wire_contract.ext.uri
                if snapshot.wire_contract.ext is not None
                else "wire_contract"
            ),
            method_name=method.method,
        )
        if preflight is not None:
            return preflight
        return await self._codex_discovery.read_plugin(
            runtime=runtime,
            jsonrpc_url=jsonrpc_url,
            method_name=method.method or _CODEX_DISCOVERY_METHODS["pluginsRead"],
            plugin_id=resolved_plugin_id,
            meta={
                "extension_uri": (
                    snapshot.wire_contract.ext.uri
                    if snapshot.wire_contract.ext is not None
                    else None
                ),
                "capability_area": "codex_discovery",
                "method_name": method.method,
                "plugin_id": resolved_plugin_id,
            },
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

    async def recover_interrupts(
        self,
        *,
        runtime: A2ARuntime,
        session_id: str | None = None,
    ) -> ExtensionCallResult:
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        ext, jsonrpc_url = self._require_interrupt_recovery_capability(
            snapshot.interrupt_recovery
        )
        return await self._interrupt_recovery.recover_interrupts(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            session_id=session_id,
        )

    async def reply_permissions_interrupt(
        self,
        *,
        runtime: A2ARuntime,
        request_id: str,
        permissions: Dict[str, Any],
        scope: str | None = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        (
            resolved_request_id,
            resolved_permissions,
            resolved_scope,
            normalized_metadata,
        ) = self._interrupt_extensions.prepare_reply_permissions_interrupt(
            request_id=request_id,
            permissions=permissions,
            scope=scope,
            metadata=metadata,
        )
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        ext, jsonrpc_url = self._require_interrupt_callback_capability(
            snapshot.interrupt_callback
        )
        return await self._interrupt_extensions.reply_permissions_interrupt(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            request_id=resolved_request_id,
            permissions=resolved_permissions,
            scope=resolved_scope,
            metadata=normalized_metadata,
        )

    async def reply_elicitation_interrupt(
        self,
        *,
        runtime: A2ARuntime,
        request_id: str,
        action: str,
        content: Any = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        (
            resolved_request_id,
            resolved_action,
            resolved_content,
            normalized_metadata,
        ) = self._interrupt_extensions.prepare_reply_elicitation_interrupt(
            request_id=request_id,
            action=action,
            content=content,
            metadata=metadata,
        )
        snapshot = await self.resolve_capability_snapshot(runtime=runtime)
        ext, jsonrpc_url = self._require_interrupt_callback_capability(
            snapshot.interrupt_callback
        )
        return await self._interrupt_extensions.reply_elicitation_interrupt(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            request_id=resolved_request_id,
            action=resolved_action,
            content=resolved_content,
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
    "InterruptRecoveryCapabilitySnapshot",
    "ModelSelectionCapabilitySnapshot",
    "ProviderDiscoveryCapabilitySnapshot",
    "ResolvedCapabilitySnapshot",
    "SessionBindingCapabilitySnapshot",
    "SessionQueryCapabilitySnapshot",
    "get_a2a_extensions_service",
    "shutdown_a2a_extensions_service",
    "A2AExtensionUpstreamError",
]
