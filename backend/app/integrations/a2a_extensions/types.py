"""Types for A2A extension discovery and invocation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, Optional


@dataclass(frozen=True, slots=True)
class PageSizePagination:
    mode: str
    default_size: int
    max_size: int
    params: tuple[str, ...] = ()
    supports_offset: bool = False


@dataclass(frozen=True, slots=True)
class JsonRpcInterface:
    url: str
    fallback_used: bool


@dataclass(frozen=True, slots=True)
class ResultEnvelopeMapping:
    items: str = "items"
    pagination: str = "pagination"
    raw: str = "raw"


@dataclass(frozen=True, slots=True)
class MessageCursorPaginationContract:
    cursor_param: str | None = None
    result_cursor_field: str | None = None


@dataclass(frozen=True, slots=True)
class SessionListFilterFieldContract:
    top_level_param: str | None = None
    query_param: str | None = None


@dataclass(frozen=True, slots=True)
class SessionListFiltersContract:
    directory: SessionListFilterFieldContract = SessionListFilterFieldContract()
    roots: SessionListFilterFieldContract = SessionListFilterFieldContract()
    start: SessionListFilterFieldContract = SessionListFilterFieldContract()
    search: SessionListFilterFieldContract = SessionListFilterFieldContract()


@dataclass(frozen=True, slots=True)
class ResolvedExtension:
    uri: str
    required: bool
    provider: str
    jsonrpc: JsonRpcInterface
    methods: Mapping[str, Optional[str]]
    pagination: PageSizePagination
    business_code_map: Mapping[int, str]
    result_envelope: ResultEnvelopeMapping
    message_cursor_pagination: MessageCursorPaginationContract = (
        MessageCursorPaginationContract()
    )
    session_list_filters: SessionListFiltersContract = SessionListFiltersContract()


@dataclass(frozen=True, slots=True)
class ResolvedSessionControlMethodCapability:
    method: Optional[str]
    declared: bool
    availability: Literal["always", "conditional", "unsupported"]
    enabled_by_default: bool | None = None
    config_key: str | None = None


@dataclass(frozen=True, slots=True)
class CompatibilityRetentionEntry:
    surface: str
    availability: str
    retention: str
    extension_uri: str | None = None
    toggle: str | None = None
    implementation_scope: str | None = None
    identity_scope: str | None = None
    upstream_stability: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedInvokeMetadataField:
    name: str
    required: bool
    description: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedInterruptCallbackExtension:
    uri: str
    required: bool
    provider: str
    jsonrpc: JsonRpcInterface
    methods: Mapping[str, Optional[str]]
    business_code_map: Mapping[int, str]


@dataclass(frozen=True, slots=True)
class ResolvedInterruptRecoveryExtension:
    uri: str
    required: bool
    provider: str
    jsonrpc: JsonRpcInterface
    methods: Mapping[str, Optional[str]]
    business_code_map: Mapping[int, str]
    recovery_data_source: str | None = None
    identity_scope: str | None = None
    implementation_scope: str | None = None
    empty_result_when_identity_unavailable: bool | None = None


@dataclass(frozen=True, slots=True)
class ResolvedSessionBindingExtension:
    uri: str
    required: bool
    provider: str
    metadata_field: str
    behavior: str
    supported_metadata: tuple[str, ...]
    provider_private_metadata: tuple[str, ...]
    shared_workspace_across_consumers: bool | None
    tenant_isolation: str | None


@dataclass(frozen=True, slots=True)
class ResolvedInvokeMetadataExtension:
    uri: str
    required: bool
    provider: str
    metadata_field: str
    behavior: str
    applies_to_methods: tuple[str, ...]
    fields: tuple[ResolvedInvokeMetadataField, ...]
    supported_metadata: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResolvedProviderDiscoveryExtension:
    uri: str
    required: bool
    provider: str
    metadata_namespace: str
    jsonrpc: JsonRpcInterface
    methods: Mapping[str, Optional[str]]
    business_code_map: Mapping[int, str]


@dataclass(frozen=True, slots=True)
class ResolvedModelSelectionExtension:
    uri: str
    required: bool
    provider: str
    metadata_field: str
    behavior: str
    applies_to_methods: tuple[str, ...]
    supported_metadata: tuple[str, ...]
    provider_private_metadata: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResolvedStreamHintsExtension:
    uri: str
    required: bool
    provider: str
    stream_field: str
    usage_field: str
    interrupt_field: str
    session_field: str


@dataclass(frozen=True, slots=True)
class ResolvedCompatibilityProfileExtension:
    uri: str
    required: bool
    extension_retention: Mapping[str, CompatibilityRetentionEntry]
    method_retention: Mapping[str, CompatibilityRetentionEntry]
    service_behaviors: Mapping[str, object]
    consumer_guidance: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResolvedConditionalMethodAvailability:
    reason: str
    toggle: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedUnsupportedMethodErrorContract:
    code: int
    type: str
    data_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResolvedWireContractExtension:
    uri: str
    required: bool
    protocol_version: str
    preferred_transport: str
    additional_transports: tuple[str, ...]
    core_jsonrpc_methods: tuple[str, ...]
    core_http_endpoints: tuple[str, ...]
    extension_jsonrpc_methods: tuple[str, ...]
    conditionally_available_methods: Mapping[str, ResolvedConditionalMethodAvailability]
    extension_uris: tuple[str, ...]
    all_jsonrpc_methods: tuple[str, ...]
    service_behaviors: Mapping[str, Any]
    unsupported_method_error: ResolvedUnsupportedMethodErrorContract
