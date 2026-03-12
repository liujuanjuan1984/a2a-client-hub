"""Types for A2A extension discovery and invocation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional


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
class ResolvedExtension:
    uri: str
    required: bool
    provider: str
    jsonrpc: JsonRpcInterface
    methods: Mapping[str, Optional[str]]
    pagination: PageSizePagination
    business_code_map: Mapping[int, str]
    result_envelope: Optional[Mapping[str, Any]]


@dataclass(frozen=True, slots=True)
class ResolvedInterruptCallbackExtension:
    uri: str
    required: bool
    provider: str
    jsonrpc: JsonRpcInterface
    methods: Mapping[str, Optional[str]]
    business_code_map: Mapping[int, str]


__all__ = [
    "JsonRpcInterface",
    "PageSizePagination",
    "ResolvedExtension",
    "ResolvedInterruptCallbackExtension",
]
