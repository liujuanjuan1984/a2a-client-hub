"""Builders for A2A extension capability snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast

from app.integrations.a2a_extensions.capability_snapshot import (
    CompatibilityProfileCapabilitySnapshot,
    DeclaredMethodCapabilitySnapshot,
    DeclaredMethodCollectionCapabilitySnapshot,
    DeclaredSingleMethodCapabilitySnapshot,
    InterruptCallbackCapabilitySnapshot,
    InterruptRecoveryCapabilitySnapshot,
    InvokeMetadataCapabilitySnapshot,
    ModelSelectionCapabilitySnapshot,
    ProviderDiscoveryCapabilitySnapshot,
    RequestExecutionOptionsCapabilitySnapshot,
    SessionBindingCapabilitySnapshot,
    SessionQueryCapabilitySnapshot,
    StreamHintsCapabilitySnapshot,
    WireContractCapabilitySnapshot,
)
from app.integrations.a2a_extensions.codex_declaration_diagnostics import (
    diagnose_codex_discovery_fallback,
)
from app.integrations.a2a_extensions.compatibility_profile import (
    resolve_compatibility_profile,
)
from app.integrations.a2a_extensions.contract_utils import as_dict, require_str
from app.integrations.a2a_extensions.errors import (
    A2AExtensionContractError,
    A2AExtensionNotSupportedError,
)
from app.integrations.a2a_extensions.interrupt_callback import (
    resolve_interrupt_callback,
)
from app.integrations.a2a_extensions.interrupt_recovery import (
    resolve_interrupt_recovery,
)
from app.integrations.a2a_extensions.invoke_metadata import resolve_invoke_metadata
from app.integrations.a2a_extensions.model_selection import resolve_model_selection
from app.integrations.a2a_extensions.opencode_provider_discovery import (
    resolve_provider_discovery,
)
from app.integrations.a2a_extensions.session_binding import resolve_session_binding
from app.integrations.a2a_extensions.session_query_runtime_selection import (
    resolve_runtime_session_query,
)
from app.integrations.a2a_extensions.shared_contract import (
    SUPPORTED_SESSION_BINDING_URIS,
    SUPPORTED_SESSION_QUERY_URIS,
    normalize_known_extension_uri,
)
from app.integrations.a2a_extensions.shared_support import (
    A2AExtensionSupport,
)
from app.integrations.a2a_extensions.stream_hints import resolve_stream_hints
from app.integrations.a2a_extensions.types import (
    CompatibilityRetentionEntry,
    ResolvedConditionalMethodAvailability,
)
from app.integrations.a2a_extensions.wire_contract import resolve_wire_contract


@dataclass(frozen=True, slots=True)
class UpstreamMethodFamilySpec:
    method_map: dict[str, str]
    hub_consumption: dict[str, bool]
    unsupported_status_when_declared: Literal[
        "declared_not_consumed", "unsupported_by_design"
    ]
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
    supports_declaration_fallback: bool = False


UPSTREAM_METHOD_FAMILY_SPECS: dict[str, UpstreamMethodFamilySpec] = {
    "discovery": UpstreamMethodFamilySpec(
        method_map={
            "skillsList": "codex.discovery.skills.list",
            "appsList": "codex.discovery.apps.list",
            "pluginsList": "codex.discovery.plugins.list",
            "pluginsRead": "codex.discovery.plugins.read",
            "watch": "codex.discovery.watch",
        },
        hub_consumption={
            "skillsList": True,
            "appsList": True,
            "pluginsList": True,
            "pluginsRead": True,
            "watch": False,
        },
        unsupported_status_when_declared="declared_not_consumed",
        declaration_source="wire_contract",
        declaration_confidence="authoritative",
        negotiation_state="supported",
        supports_declaration_fallback=True,
    ),
    "threads": UpstreamMethodFamilySpec(
        method_map={
            "fork": "codex.threads.fork",
            "archive": "codex.threads.archive",
            "unarchive": "codex.threads.unarchive",
            "metadataUpdate": "codex.threads.metadata.update",
            "watch": "codex.threads.watch",
        },
        hub_consumption={},
        unsupported_status_when_declared="unsupported_by_design",
    ),
    "turns": UpstreamMethodFamilySpec(
        method_map={
            "steer": "codex.turns.steer",
        },
        hub_consumption={
            "steer": True,
        },
        unsupported_status_when_declared="declared_not_consumed",
    ),
    "review": UpstreamMethodFamilySpec(
        method_map={
            "start": "codex.review.start",
            "watch": "codex.review.watch",
        },
        hub_consumption={},
        unsupported_status_when_declared="unsupported_by_design",
    ),
    "exec": UpstreamMethodFamilySpec(
        method_map={
            "start": "codex.exec.start",
            "write": "codex.exec.write",
            "resize": "codex.exec.resize",
            "terminate": "codex.exec.terminate",
        },
        hub_consumption={},
        unsupported_status_when_declared="unsupported_by_design",
    ),
}
_CODEX_THREAD_WATCH_METHOD = "codex.threads.watch"
_CODEX_REQUEST_EXECUTION_METADATA_FIELD = "metadata.codex.execution"


def build_session_query_snapshot(card: Any) -> SessionQueryCapabilitySnapshot:
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


def build_session_binding_snapshot(card: Any) -> SessionBindingCapabilitySnapshot:
    try:
        ext = resolve_session_binding(card)
    except A2AExtensionNotSupportedError as exc:
        return SessionBindingCapabilitySnapshot(
            status="unsupported",
            error=str(exc),
            meta={
                "session_binding_declared": False,
                "session_binding_mode": "undeclared",
                "session_binding_fallback_used": False,
            },
        )
    except A2AExtensionContractError as exc:
        return SessionBindingCapabilitySnapshot(
            status="invalid",
            error=str(exc),
            meta={
                "session_binding_declared": True,
                "session_binding_mode": "invalid_contract",
                "session_binding_fallback_used": False,
                "session_binding_contract_error": str(exc),
            },
        )

    return SessionBindingCapabilitySnapshot(
        status="supported",
        ext=ext,
        meta={
            "session_binding_declared": True,
            "session_binding_uri": ext.uri,
            "session_binding_mode": "declared_contract",
            "session_binding_fallback_used": False,
        },
    )


def build_invoke_metadata_snapshot(card: Any) -> InvokeMetadataCapabilitySnapshot:
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


def normalize_optional_string_list(
    value: Any,
    *,
    field: str,
) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise A2AExtensionContractError(f"Extension contract missing/invalid '{field}'")
    items: list[str] = []
    for index, item in enumerate(value):
        normalized = require_str(item, field=f"{field}[{index}]")
        if normalized not in items:
            items.append(normalized)
    return tuple(items)


def build_request_execution_options_snapshot(
    card: Any,
) -> RequestExecutionOptionsCapabilitySnapshot:
    capabilities = getattr(card, "capabilities", None)
    extensions = getattr(capabilities, "extensions", None) if capabilities else None
    if not extensions:
        return RequestExecutionOptionsCapabilitySnapshot(
            status="unsupported",
            declared=False,
            consumed_by_hub=False,
        )

    metadata_field: str | None = None
    persists_for_thread: bool | None = None
    fields: list[str] = []
    notes: list[str] = []
    source_extensions: list[str] = []
    found = False
    supported_sources = {
        *SUPPORTED_SESSION_BINDING_URIS,
        *SUPPORTED_SESSION_QUERY_URIS,
    }

    try:
        for ext in extensions:
            raw_uri = getattr(ext, "uri", None)
            if not isinstance(raw_uri, str) or raw_uri.strip() not in supported_sources:
                continue
            params = as_dict(getattr(ext, "params", None))
            if "request_execution_options" not in params:
                continue
            found = True
            contract = as_dict(params.get("request_execution_options"))
            if not contract:
                raise A2AExtensionContractError(
                    "Extension contract missing/invalid "
                    "'params.request_execution_options'"
                )
            current_metadata_field = require_str(
                contract.get("metadata_field"),
                field="params.request_execution_options.metadata_field",
            )
            if current_metadata_field != _CODEX_REQUEST_EXECUTION_METADATA_FIELD:
                raise A2AExtensionContractError(
                    "Extension contract missing/invalid "
                    "'params.request_execution_options.metadata_field'"
                )
            current_fields = normalize_optional_string_list(
                contract.get("fields"),
                field="params.request_execution_options.fields",
            )
            if not current_fields:
                raise A2AExtensionContractError(
                    "Extension contract missing/invalid "
                    "'params.request_execution_options.fields'"
                )
            raw_persists_for_thread = contract.get("persists_for_thread")
            if raw_persists_for_thread is not None and not isinstance(
                raw_persists_for_thread, bool
            ):
                raise A2AExtensionContractError(
                    "Extension contract missing/invalid "
                    "'params.request_execution_options.persists_for_thread'"
                )
            current_notes = normalize_optional_string_list(
                contract.get("notes"),
                field="params.request_execution_options.notes",
            )
            if metadata_field is None:
                metadata_field = current_metadata_field
            elif metadata_field != current_metadata_field:
                raise A2AExtensionContractError(
                    "Extension contract has conflicting "
                    "'params.request_execution_options.metadata_field'"
                )
            if raw_persists_for_thread is not None:
                if persists_for_thread is None:
                    persists_for_thread = raw_persists_for_thread
                elif persists_for_thread != raw_persists_for_thread:
                    raise A2AExtensionContractError(
                        "Extension contract has conflicting "
                        "'params.request_execution_options.persists_for_thread'"
                    )
            for item in current_fields:
                if item not in fields:
                    fields.append(item)
            for item in current_notes:
                if item not in notes:
                    notes.append(item)
            normalized_uri = normalize_known_extension_uri(raw_uri) or raw_uri.strip()
            if normalized_uri not in source_extensions:
                source_extensions.append(normalized_uri)
    except A2AExtensionContractError as exc:
        return RequestExecutionOptionsCapabilitySnapshot(
            status="invalid",
            declared=found,
            consumed_by_hub=False,
            metadata_field=metadata_field,
            fields=tuple(fields),
            persists_for_thread=persists_for_thread,
            source_extensions=tuple(source_extensions),
            notes=tuple(notes),
            error=str(exc),
        )

    if not found:
        return RequestExecutionOptionsCapabilitySnapshot(
            status="unsupported",
            declared=False,
            consumed_by_hub=False,
        )

    return RequestExecutionOptionsCapabilitySnapshot(
        status="supported",
        declared=True,
        consumed_by_hub=True,
        metadata_field=metadata_field,
        fields=tuple(fields),
        persists_for_thread=persists_for_thread,
        source_extensions=tuple(source_extensions),
        notes=tuple(notes),
    )


def build_interrupt_callback_snapshot(
    support: A2AExtensionSupport,
    card: Any,
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
        jsonrpc_url=support.ensure_outbound_allowed(
            ext.jsonrpc.url, purpose="JSON-RPC interface URL"
        ),
    )


def build_interrupt_recovery_snapshot(
    support: A2AExtensionSupport,
    card: Any,
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
        jsonrpc_url=support.ensure_outbound_allowed(
            ext.jsonrpc.url, purpose="JSON-RPC interface URL"
        ),
    )


def build_provider_discovery_snapshot(
    support: A2AExtensionSupport,
    card: Any,
) -> ProviderDiscoveryCapabilitySnapshot:
    try:
        ext = resolve_provider_discovery(card)
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
        jsonrpc_url=support.ensure_outbound_allowed(
            ext.jsonrpc.url, purpose="JSON-RPC interface URL"
        ),
    )


def build_model_selection_snapshot(card: Any) -> ModelSelectionCapabilitySnapshot:
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


def build_stream_hints_snapshot(card: Any) -> StreamHintsCapabilitySnapshot:
    try:
        ext = resolve_stream_hints(card)
    except A2AExtensionNotSupportedError as exc:
        return StreamHintsCapabilitySnapshot(
            status="unsupported",
            error=str(exc),
            meta={
                "stream_hints_declared": False,
                "stream_hints_mode": "undeclared",
                "stream_hints_fallback_used": False,
            },
        )
    except A2AExtensionContractError as exc:
        return StreamHintsCapabilitySnapshot(
            status="invalid",
            error=str(exc),
            meta={
                "stream_hints_declared": True,
                "stream_hints_mode": "invalid_contract",
                "stream_hints_fallback_used": False,
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


def build_compatibility_profile_snapshot(
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


def build_wire_contract_snapshot(
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


def declared_wire_contract_methods(
    snapshot: WireContractCapabilitySnapshot,
) -> frozenset[str]:
    if snapshot.status != "supported" or snapshot.ext is None:
        return frozenset()
    return frozenset(snapshot.ext.all_jsonrpc_methods)


def conditional_wire_contract_methods(
    snapshot: WireContractCapabilitySnapshot,
) -> dict[str, ResolvedConditionalMethodAvailability]:
    if snapshot.status != "supported" or snapshot.ext is None:
        return {}
    return dict(snapshot.ext.conditionally_available_methods)


def compatibility_method_retention(
    snapshot: CompatibilityProfileCapabilitySnapshot,
) -> dict[str, CompatibilityRetentionEntry]:
    if snapshot.status != "supported" or snapshot.ext is None:
        return {}
    return dict(snapshot.ext.method_retention)


def resolve_declared_method_snapshot(
    *,
    wire_contract: WireContractCapabilitySnapshot,
    compatibility_profile: CompatibilityProfileCapabilitySnapshot,
    method_name: str,
    consumed_by_hub: bool,
) -> DeclaredMethodCapabilitySnapshot:
    declared_methods = declared_wire_contract_methods(wire_contract)
    conditional_methods = conditional_wire_contract_methods(wire_contract)
    retention_map = compatibility_method_retention(compatibility_profile)
    conditional = conditional_methods.get(method_name)
    retention = retention_map.get(method_name)

    active_declared = method_name in declared_methods
    deployment_conditional = conditional is not None or (
        retention is not None
        and retention.retention == "deployment-conditional"
        and retention.availability in {"enabled", "disabled"}
    )
    declared = active_declared or deployment_conditional

    if active_declared:
        availability: Literal["always", "enabled", "disabled", "unsupported"] = (
            cast(
                Literal["always", "enabled", "disabled"],
                retention.availability,
            )
            if retention is not None
            and retention.availability in {"always", "enabled", "disabled"}
            else "always"
        )
    elif deployment_conditional:
        availability = (
            cast(Literal["enabled", "disabled"], retention.availability)
            if retention is not None
            and retention.availability in {"enabled", "disabled"}
            else "disabled"
        )
    else:
        availability = "unsupported"

    return DeclaredMethodCapabilitySnapshot(
        declared=declared,
        consumed_by_hub=consumed_by_hub and active_declared,
        method=method_name if declared else None,
        availability=availability,
        config_key=(
            conditional.toggle
            if conditional is not None and conditional.toggle
            else retention.toggle if retention is not None else None
        ),
        reason=conditional.reason if conditional is not None else None,
        retention=retention.retention if retention is not None else None,
    )


def build_declared_method_collection_snapshot(
    *,
    wire_contract: WireContractCapabilitySnapshot,
    compatibility_profile: CompatibilityProfileCapabilitySnapshot,
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
    declaration_confidence: Literal["none", "fallback", "authoritative"] | None = None,
    negotiation_state: (
        Literal["supported", "missing", "invalid", "unsupported"] | None
    ) = None,
    diagnostic_note: str | None = None,
) -> DeclaredMethodCollectionCapabilitySnapshot:
    methods = {
        key: resolve_declared_method_snapshot(
            wire_contract=wire_contract,
            compatibility_profile=compatibility_profile,
            method_name=method_name,
            consumed_by_hub=bool(hub_consumption.get(key, False)),
        )
        for key, method_name in method_map.items()
    }
    declared = any(item.declared for item in methods.values())
    consumed = any(item.declared and item.consumed_by_hub for item in methods.values())
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


def build_codex_discovery_snapshot(
    card: Any,
    wire_contract: WireContractCapabilitySnapshot,
    compatibility_profile: CompatibilityProfileCapabilitySnapshot,
    *,
    jsonrpc_url: str | None,
) -> DeclaredMethodCollectionCapabilitySnapshot:
    spec = UPSTREAM_METHOD_FAMILY_SPECS["discovery"]
    if wire_contract.status == "supported":
        return build_declared_method_collection_snapshot(
            wire_contract=wire_contract,
            compatibility_profile=compatibility_profile,
            method_map=spec.method_map,
            hub_consumption=spec.hub_consumption,
            unsupported_status_when_declared=spec.unsupported_status_when_declared,
            jsonrpc_url=jsonrpc_url,
            declaration_source=spec.declaration_source,
            declaration_confidence=spec.declaration_confidence,
            negotiation_state=spec.negotiation_state,
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
                method=method_name if method_name in fallback.method_names else None,
                availability=(
                    "always" if method_name in fallback.method_names else "unsupported"
                ),
            )
            for key, method_name in spec.method_map.items()
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

    return build_declared_method_collection_snapshot(
        wire_contract=wire_contract,
        compatibility_profile=compatibility_profile,
        method_map=spec.method_map,
        hub_consumption=spec.hub_consumption,
        unsupported_status_when_declared=spec.unsupported_status_when_declared,
        jsonrpc_url=None,
        declaration_source=fallback.source,
        declaration_confidence=fallback.confidence,
        negotiation_state=fallback.negotiation_state,
        diagnostic_note=fallback.note,
    )


def build_codex_exec_snapshot(
    wire_contract: WireContractCapabilitySnapshot,
    compatibility_profile: CompatibilityProfileCapabilitySnapshot,
    *,
    jsonrpc_url: str | None,
) -> DeclaredMethodCollectionCapabilitySnapshot:
    spec = UPSTREAM_METHOD_FAMILY_SPECS["exec"]
    return build_declared_method_collection_snapshot(
        wire_contract=wire_contract,
        compatibility_profile=compatibility_profile,
        method_map=spec.method_map,
        hub_consumption=spec.hub_consumption,
        unsupported_status_when_declared=spec.unsupported_status_when_declared,
        jsonrpc_url=jsonrpc_url,
    )


def build_codex_threads_snapshot(
    wire_contract: WireContractCapabilitySnapshot,
    compatibility_profile: CompatibilityProfileCapabilitySnapshot,
    *,
    jsonrpc_url: str | None,
) -> DeclaredMethodCollectionCapabilitySnapshot:
    spec = UPSTREAM_METHOD_FAMILY_SPECS["threads"]
    return build_declared_method_collection_snapshot(
        wire_contract=wire_contract,
        compatibility_profile=compatibility_profile,
        method_map=spec.method_map,
        hub_consumption=spec.hub_consumption,
        unsupported_status_when_declared=spec.unsupported_status_when_declared,
        jsonrpc_url=jsonrpc_url,
    )


def build_codex_turns_snapshot(
    wire_contract: WireContractCapabilitySnapshot,
    compatibility_profile: CompatibilityProfileCapabilitySnapshot,
    *,
    jsonrpc_url: str | None,
) -> DeclaredMethodCollectionCapabilitySnapshot:
    spec = UPSTREAM_METHOD_FAMILY_SPECS["turns"]
    return build_declared_method_collection_snapshot(
        wire_contract=wire_contract,
        compatibility_profile=compatibility_profile,
        method_map=spec.method_map,
        hub_consumption=spec.hub_consumption,
        unsupported_status_when_declared=spec.unsupported_status_when_declared,
        jsonrpc_url=jsonrpc_url,
    )


def build_codex_review_snapshot(
    wire_contract: WireContractCapabilitySnapshot,
    compatibility_profile: CompatibilityProfileCapabilitySnapshot,
    *,
    jsonrpc_url: str | None,
) -> DeclaredMethodCollectionCapabilitySnapshot:
    spec = UPSTREAM_METHOD_FAMILY_SPECS["review"]
    return build_declared_method_collection_snapshot(
        wire_contract=wire_contract,
        compatibility_profile=compatibility_profile,
        method_map=spec.method_map,
        hub_consumption=spec.hub_consumption,
        unsupported_status_when_declared=spec.unsupported_status_when_declared,
        jsonrpc_url=jsonrpc_url,
    )


def build_codex_thread_watch_snapshot(
    wire_contract: WireContractCapabilitySnapshot,
    *,
    jsonrpc_url: str | None,
) -> DeclaredSingleMethodCapabilitySnapshot:
    declared_methods = declared_wire_contract_methods(wire_contract)
    declared = _CODEX_THREAD_WATCH_METHOD in declared_methods
    return DeclaredSingleMethodCapabilitySnapshot(
        declared=declared,
        consumed_by_hub=False,
        status="unsupported_by_design" if declared else "unsupported",
        method=_CODEX_THREAD_WATCH_METHOD if declared else None,
        jsonrpc_url=jsonrpc_url,
    )
