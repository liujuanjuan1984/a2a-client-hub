"""Fallback diagnostics for upstream discovery declaration hints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from a2a.types import AgentCard

from app.integrations.a2a_extensions.contract_utils import as_dict
from app.integrations.a2a_extensions.shared_contract import (
    SUPPORTED_WIRE_CONTRACT_URIS,
    is_supported_extension_uri,
)

_UPSTREAM_DISCOVERY_METHOD_PREFIX = "codex.discovery."


@dataclass(frozen=True, slots=True)
class UpstreamDiscoveryDeclarationFallback:
    declared: bool
    source: Literal[
        "none",
        "wire_contract",
        "wire_contract_fallback",
        "extension_method_hint",
        "extension_uri_hint",
    ]
    confidence: Literal["none", "fallback", "authoritative"]
    negotiation_state: Literal["supported", "missing", "invalid", "unsupported"]
    method_names: tuple[str, ...] = ()
    note: str | None = None


def _iter_extensions(card: AgentCard) -> list[Any]:
    capabilities = getattr(card, "capabilities", None)
    extensions = getattr(capabilities, "extensions", None) if capabilities else None
    return list(extensions or [])


def _normalize_string_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()

    items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        normalized = item.strip()
        if normalized and normalized not in items:
            items.append(normalized)
    return tuple(items)


def _extract_declared_method_hints(ext: Any) -> tuple[str, ...]:
    params = as_dict(getattr(ext, "params", None))
    methods = as_dict(params.get("methods"))
    extensions_params = as_dict(params.get("extensions"))

    candidates: list[str] = []
    candidates.extend(_normalize_string_list(params.get("all_jsonrpc_methods")))
    candidates.extend(_normalize_string_list(params.get("jsonrpc_methods")))
    candidates.extend(_normalize_string_list(extensions_params.get("jsonrpc_methods")))

    for value in methods.values():
        if isinstance(value, str):
            normalized = value.strip()
            if normalized:
                candidates.append(normalized)

    resolved: list[str] = []
    for candidate in candidates:
        if (
            candidate.startswith(_UPSTREAM_DISCOVERY_METHOD_PREFIX)
            and candidate not in resolved
        ):
            resolved.append(candidate)
    return tuple(resolved)


def _has_extension_uri_hint(ext: Any) -> bool:
    uri = str(getattr(ext, "uri", "") or "").strip().lower()
    return bool(uri and "codex" in uri and "discovery" in uri)


def diagnose_upstream_discovery_fallback(
    card: AgentCard,
    *,
    wire_contract_status: Literal["supported", "unsupported", "invalid"],
) -> UpstreamDiscoveryDeclarationFallback:
    if wire_contract_status == "supported":
        return UpstreamDiscoveryDeclarationFallback(
            declared=False,
            source="wire_contract",
            confidence="authoritative",
            negotiation_state="supported",
        )

    extensions = _iter_extensions(card)

    for ext in extensions:
        if is_supported_extension_uri(
            getattr(ext, "uri", None), SUPPORTED_WIRE_CONTRACT_URIS
        ):
            method_names = _extract_declared_method_hints(ext)
            if method_names:
                return UpstreamDiscoveryDeclarationFallback(
                    declared=True,
                    source="wire_contract_fallback",
                    confidence="fallback",
                    negotiation_state=(
                        "invalid" if wire_contract_status == "invalid" else "missing"
                    ),
                    method_names=method_names,
                    note=(
                        "Upstream discovery methods were inferred from raw wire-contract "
                        "params because the authoritative wire-contract snapshot is "
                        "not available."
                    ),
                )

    for ext in extensions:
        if is_supported_extension_uri(
            getattr(ext, "uri", None), SUPPORTED_WIRE_CONTRACT_URIS
        ):
            continue
        method_names = _extract_declared_method_hints(ext)
        if method_names:
            return UpstreamDiscoveryDeclarationFallback(
                declared=True,
                source="extension_method_hint",
                confidence="fallback",
                negotiation_state=(
                    "invalid" if wire_contract_status == "invalid" else "missing"
                ),
                method_names=method_names,
                note=(
                    "Upstream discovery methods were inferred from non-wire-contract "
                    "extension params and are treated as weak declaration signals."
                ),
            )

    for ext in extensions:
        if _has_extension_uri_hint(ext):
            return UpstreamDiscoveryDeclarationFallback(
                declared=True,
                source="extension_uri_hint",
                confidence="fallback",
                negotiation_state=(
                    "invalid" if wire_contract_status == "invalid" else "missing"
                ),
                note=(
                    "An upstream discovery-like extension URI was declared, but no "
                    "method matrix was available."
                ),
            )

    return UpstreamDiscoveryDeclarationFallback(
        declared=False,
        source="none",
        confidence="none",
        negotiation_state=(
            "invalid" if wire_contract_status == "invalid" else "unsupported"
        ),
        note=(
            "Wire-contract is invalid and no upstream discovery fallback hints were found."
            if wire_contract_status == "invalid"
            else None
        ),
    )
