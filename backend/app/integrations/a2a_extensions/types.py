"""Types for A2A extension discovery and invocation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional


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
class ResolvedExtension:
    uri: str
    required: bool
    provider: str
    jsonrpc: JsonRpcInterface
    methods: Mapping[str, Optional[str]]
    pagination: PageSizePagination
    business_code_map: Mapping[int, str]
    result_envelope: Optional[ResultEnvelopeMapping]


@dataclass(frozen=True, slots=True)
class ResolvedInterruptCallbackExtension:
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
    "PageSizePagination",
    "ResultEnvelopeMapping",
    "ResolvedProviderDiscoveryExtension",
    "ResolvedExtension",
    "ResolvedInterruptCallbackExtension",
    "ResolvedSessionBindingExtension",
    "ResolvedStreamHintsExtension",
]
