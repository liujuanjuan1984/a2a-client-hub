"""Shared capability snapshot models for A2A extension inspection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.integrations.a2a_extensions.session_query_runtime_selection import (
    ResolvedSessionQueryRuntimeCapability,
)
from app.integrations.a2a_extensions.types import (
    ResolvedCompatibilityProfileExtension,
    ResolvedInterruptCallbackExtension,
    ResolvedInterruptRecoveryExtension,
    ResolvedInvokeMetadataExtension,
    ResolvedModelSelectionExtension,
    ResolvedProviderDiscoveryExtension,
    ResolvedSessionBindingExtension,
    ResolvedStreamHintsExtension,
    ResolvedWireContractExtension,
)


@dataclass(frozen=True, slots=True)
class DeclaredMethodCapabilitySnapshot:
    declared: bool
    consumed_by_hub: bool
    method: str | None = None
    availability: Literal["always", "enabled", "disabled", "unsupported"] = (
        "unsupported"
    )
    config_key: str | None = None
    reason: str | None = None
    retention: str | None = None


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
class RequestExecutionOptionsCapabilitySnapshot:
    status: Literal["unsupported", "declared_not_consumed", "invalid"]
    declared: bool
    consumed_by_hub: bool
    metadata_field: str | None = None
    fields: tuple[str, ...] = ()
    persists_for_thread: bool | None = None
    source_extensions: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    error: str | None = None


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
    request_execution_options: RequestExecutionOptionsCapabilitySnapshot
    interrupt_callback: InterruptCallbackCapabilitySnapshot
    interrupt_recovery: InterruptRecoveryCapabilitySnapshot
    model_selection: ModelSelectionCapabilitySnapshot
    provider_discovery: ProviderDiscoveryCapabilitySnapshot
    stream_hints: StreamHintsCapabilitySnapshot
    wire_contract: WireContractCapabilitySnapshot
    compatibility_profile: CompatibilityProfileCapabilitySnapshot
    codex_discovery: DeclaredMethodCollectionCapabilitySnapshot
    codex_threads: DeclaredMethodCollectionCapabilitySnapshot
    codex_turns: DeclaredMethodCollectionCapabilitySnapshot
    codex_review: DeclaredMethodCollectionCapabilitySnapshot
    codex_thread_watch: DeclaredSingleMethodCapabilitySnapshot
    codex_exec: DeclaredMethodCollectionCapabilitySnapshot


@dataclass(slots=True)
class CapabilitySnapshotCacheEntry:
    snapshot: ResolvedCapabilitySnapshot
    expires_at: float
