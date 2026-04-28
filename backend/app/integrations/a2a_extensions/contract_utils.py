"""Shared helpers for validating and normalizing A2A extension contracts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Dict, Optional

from a2a.types import AgentCard

from app.integrations.a2a_client.protobuf import to_protojson_like
from app.integrations.a2a_extensions.errors import A2AExtensionContractError
from app.integrations.a2a_extensions.types import JsonRpcInterface


def as_dict(value: Any) -> Dict[str, Any]:
    normalized = to_protojson_like(value)
    if isinstance(normalized, Mapping):
        return {str(key): item for key, item in normalized.items()}
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    return {}


def require_str(value: Any, *, field: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise A2AExtensionContractError(f"Extension contract missing/invalid '{field}'")


def normalize_method_name(value: Any, *, field: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise A2AExtensionContractError(f"'{field}' must be a string if provided")
    normalized = value.strip()
    return normalized or None


def normalize_string_list(
    value: Any,
    *,
    field: str,
    allow_missing: bool = False,
    allow_empty: bool = True,
) -> tuple[str, ...]:
    if value is None:
        if allow_missing:
            return ()
        raise A2AExtensionContractError(f"Extension contract missing/invalid '{field}'")
    if not isinstance(value, list):
        raise A2AExtensionContractError(f"Extension contract missing/invalid '{field}'")

    items: list[str] = []
    for item in value:
        normalized = require_str(item, field=field)
        if normalized not in items:
            items.append(normalized)

    if not allow_empty and not items:
        raise A2AExtensionContractError(f"Extension contract missing/invalid '{field}'")
    return tuple(items)


def require_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool):
        raise A2AExtensionContractError(f"Extension contract missing/invalid '{field}'")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    raise A2AExtensionContractError(f"Extension contract missing/invalid '{field}'")


def normalize_error_token(name: str, *, code_value: int) -> str:
    normalized: list[str] = []
    pending_sep = False
    for ch in name.strip().lower():
        if ch.isalnum():
            if pending_sep and normalized:
                normalized.append("_")
            normalized.append(ch)
            pending_sep = False
            continue
        pending_sep = True
    token = "".join(normalized).strip("_")
    if token:
        return token
    return f"business_code_{abs(code_value)}"


def build_business_code_map(value: Any) -> Dict[int, str]:
    business_codes = as_dict(value)
    code_to_error: Dict[int, str] = {}
    for name, code in business_codes.items():
        try:
            code_value = require_int(code, field="errors.business_codes.*")
        except A2AExtensionContractError:
            continue
        token = normalize_error_token(str(name), code_value=code_value)
        code_to_error.setdefault(code_value, token)
    return code_to_error


def resolve_jsonrpc_interface(card: AgentCard) -> JsonRpcInterface:
    jsonrpc_url: Optional[str] = None
    for iface in getattr(card, "supported_interfaces", None) or []:
        transport = (getattr(iface, "protocol_binding", "") or "").strip().lower()
        url = (getattr(iface, "url", "") or "").strip()
        if transport == "jsonrpc" and url:
            jsonrpc_url = url
            break

    if not jsonrpc_url:
        raise A2AExtensionContractError(
            "Agent card is missing a JSON-RPC interface URL"
        )

    return JsonRpcInterface(url=jsonrpc_url, fallback_used=False)
