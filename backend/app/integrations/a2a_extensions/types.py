"""Types for A2A extension discovery and invocation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping, Optional


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
    result_envelope: Optional[ResultEnvelopeMapping]
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
    legacy_uri_used: bool = False


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


__all__ = [
    "JsonRpcInterface",
    "MessageCursorPaginationContract",
    "PageSizePagination",
    "ResultEnvelopeMapping",
    "ResolvedModelSelectionExtension",
    "ResolvedProviderDiscoveryExtension",
    "ResolvedSessionControlMethodCapability",
    "ResolvedExtension",
    "ResolvedInterruptCallbackExtension",
    "ResolvedInterruptRecoveryExtension",
    "ResolvedSessionBindingExtension",
    "ResolvedStreamHintsExtension",
    "SessionListFilterFieldContract",
    "SessionListFiltersContract",
]
