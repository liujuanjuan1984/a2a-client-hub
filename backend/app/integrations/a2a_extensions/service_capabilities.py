"""Capability resolution and wire-contract helpers for A2A extension services."""

from __future__ import annotations

import asyncio
from typing import Literal, Protocol

from a2a.types import AgentCard

from app.features.agents.personal.runtime import A2ARuntime
from app.integrations.a2a_extensions import capability_snapshot_builder
from app.integrations.a2a_extensions.capability_snapshot import (
    CapabilitySnapshotCacheEntry,
    DeclaredMethodCapabilitySnapshot,
    DeclaredMethodCollectionCapabilitySnapshot,
    InterruptCallbackCapabilitySnapshot,
    InterruptRecoveryCapabilitySnapshot,
    ProviderDiscoveryCapabilitySnapshot,
    ResolvedCapabilitySnapshot,
    SessionQueryCapabilitySnapshot,
    WireContractCapabilitySnapshot,
)
from app.integrations.a2a_extensions.contract_utils import resolve_jsonrpc_interface
from app.integrations.a2a_extensions.errors import (
    A2AExtensionContractError,
    A2AExtensionNotSupportedError,
    A2AExtensionUpstreamError,
)
from app.integrations.a2a_extensions.service_common import ExtensionCallResult
from app.integrations.a2a_extensions.session_query_runtime_selection import (
    ResolvedSessionQueryRuntimeCapability,
)
from app.integrations.a2a_extensions.shared_support import A2AExtensionSupport
from app.integrations.a2a_extensions.types import (
    ResolvedConditionalMethodAvailability,
    ResolvedInterruptCallbackExtension,
    ResolvedInterruptRecoveryExtension,
    ResolvedProviderDiscoveryExtension,
    ResolvedWireContractExtension,
)

UPSTREAM_DISCOVERY_METHODS = {
    "skillsList": "codex.discovery.skills.list",
    "appsList": "codex.discovery.apps.list",
    "pluginsList": "codex.discovery.plugins.list",
    "pluginsRead": "codex.discovery.plugins.read",
    "watch": "codex.discovery.watch",
}
UPSTREAM_TURN_METHODS = {
    "steer": "codex.turns.steer",
}
UPSTREAM_TURN_CONTROL_EXTENSION_URI = "urn:codex-a2a:codex-turn-control/v1"
UPSTREAM_TURN_CONTROL_BUSINESS_CODE_MAP = {
    -32007: "authorization_forbidden",
    -32012: "turn_not_steerable",
    -32013: "turn_forbidden",
}
CAPABILITY_SNAPSHOT_CACHE_TTL_SECONDS = 300.0


class Clock(Protocol):
    """Minimal clock interface for cache TTL calculations."""

    def monotonic(self) -> float: ...


class A2AExtensionCapabilityService:
    """Resolves extension capability snapshots and wire-contract requirements."""

    def __init__(
        self,
        *,
        support: A2AExtensionSupport,
        time_module: Clock,
    ) -> None:
        self._support = support
        self._time = time_module
        self._capability_snapshot_cache_lock = asyncio.Lock()
        self._capability_snapshot_cache: dict[
            tuple[str, tuple[tuple[str, str], ...]],
            CapabilitySnapshotCacheEntry,
        ] = {}

    async def shutdown(self) -> None:
        async with self._capability_snapshot_cache_lock:
            self._capability_snapshot_cache.clear()

    @staticmethod
    def capability_snapshot_cache_key(
        runtime: A2ARuntime,
    ) -> tuple[str, tuple[tuple[str, str], ...]]:
        resolved_headers = getattr(runtime.resolved, "headers", {}) or {}
        headers = tuple(sorted(resolved_headers.items()))
        return runtime.resolved.url, headers

    async def resolve_capability_snapshot(
        self,
        *,
        runtime: A2ARuntime,
    ) -> ResolvedCapabilitySnapshot:
        cache_key = self.capability_snapshot_cache_key(runtime)
        now = self._time.monotonic()
        async with self._capability_snapshot_cache_lock:
            cached = self._capability_snapshot_cache.get(cache_key)
            if cached and cached.expires_at > now:
                return cached.snapshot

        card = await self._support.fetch_card(runtime)
        snapshot = self.build_capability_snapshot_from_card(card=card)
        async with self._capability_snapshot_cache_lock:
            self._capability_snapshot_cache[cache_key] = CapabilitySnapshotCacheEntry(
                snapshot=snapshot,
                expires_at=now + CAPABILITY_SNAPSHOT_CACHE_TTL_SECONDS,
            )
        return snapshot

    def build_capability_snapshot_from_card(
        self,
        *,
        card: AgentCard,
    ) -> ResolvedCapabilitySnapshot:
        wire_contract = capability_snapshot_builder.build_wire_contract_snapshot(card)
        jsonrpc_url = None
        try:
            jsonrpc_url = self._support.ensure_outbound_allowed(
                resolve_jsonrpc_interface(card).url,
                purpose="JSON-RPC interface URL",
            )
        except (A2AExtensionContractError, A2AExtensionUpstreamError):
            jsonrpc_url = None
        compatibility_profile = (
            capability_snapshot_builder.build_compatibility_profile_snapshot(card)
        )
        snapshot = ResolvedCapabilitySnapshot(
            session_query=capability_snapshot_builder.build_session_query_snapshot(
                card
            ),
            session_binding=capability_snapshot_builder.build_session_binding_snapshot(
                card
            ),
            invoke_metadata=capability_snapshot_builder.build_invoke_metadata_snapshot(
                card
            ),
            request_execution_options=capability_snapshot_builder.build_request_execution_options_snapshot(
                card
            ),
            interrupt_callback=capability_snapshot_builder.build_interrupt_callback_snapshot(
                self._support,
                card,
            ),
            interrupt_recovery=capability_snapshot_builder.build_interrupt_recovery_snapshot(
                self._support,
                card,
            ),
            model_selection=capability_snapshot_builder.build_model_selection_snapshot(
                card
            ),
            provider_discovery=capability_snapshot_builder.build_provider_discovery_snapshot(
                self._support,
                card,
            ),
            stream_hints=capability_snapshot_builder.build_stream_hints_snapshot(card),
            wire_contract=wire_contract,
            compatibility_profile=compatibility_profile,
            codex_discovery=capability_snapshot_builder.build_codex_discovery_snapshot(
                card,
                wire_contract,
                compatibility_profile,
                jsonrpc_url=jsonrpc_url,
            ),
            codex_threads=capability_snapshot_builder.build_codex_threads_snapshot(
                wire_contract,
                compatibility_profile,
                jsonrpc_url=jsonrpc_url,
            ),
            codex_turns=capability_snapshot_builder.build_codex_turns_snapshot(
                wire_contract,
                compatibility_profile,
                jsonrpc_url=jsonrpc_url,
            ),
            codex_review=capability_snapshot_builder.build_codex_review_snapshot(
                wire_contract,
                compatibility_profile,
                jsonrpc_url=jsonrpc_url,
            ),
            codex_thread_watch=capability_snapshot_builder.build_codex_thread_watch_snapshot(
                wire_contract, jsonrpc_url=jsonrpc_url
            ),
            codex_exec=capability_snapshot_builder.build_codex_exec_snapshot(
                wire_contract,
                compatibility_profile,
                jsonrpc_url=jsonrpc_url,
            ),
        )
        return snapshot

    @staticmethod
    def resolve_upstream_method_family(
        snapshot: ResolvedCapabilitySnapshot,
        family_name: str,
    ) -> DeclaredMethodCollectionCapabilitySnapshot:
        family = snapshot.upstream_method_families.get(family_name)
        if family is None:
            raise A2AExtensionNotSupportedError(
                f"Upstream method family {family_name} is not available"
            )
        return family

    @staticmethod
    def require_session_query_capability(
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
    def require_interrupt_callback_capability(
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
    def require_interrupt_recovery_capability(
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
    def require_provider_discovery_capability(
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
    def require_declared_method_collection_capability(
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
    def require_declared_method_capability(
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
    def build_wire_contract_preflight_error(
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
    def preflight_wire_contract_method(
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
            return cls.build_wire_contract_preflight_error(
                error_code="method_disabled",
                extension_uri=extension_uri,
                method_name=method_name,
                wire_contract=wire_contract,
                conditional=conditional,
            )

        return cls.build_wire_contract_preflight_error(
            error_code="method_not_supported",
            extension_uri=extension_uri,
            method_name=method_name,
            wire_contract=wire_contract,
        )
