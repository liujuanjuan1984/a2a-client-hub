"""OpenCode interrupt callback extension resolver and helpers."""

from __future__ import annotations

from typing import Any, Dict, Optional

from a2a.types import AgentCard

from app.integrations.a2a_extensions.errors import (
    A2AExtensionContractError,
    A2AExtensionNotSupportedError,
)
from app.integrations.a2a_extensions.types import (
    JsonRpcInterface,
    ResolvedInterruptCallbackExtension,
)

OPENCODE_INTERRUPT_CALLBACK_URI = "urn:opencode-a2a:opencode-interrupt-callback/v1"


def _as_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _require_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool):
        raise A2AExtensionContractError(f"Extension contract missing/invalid '{field}'")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    raise A2AExtensionContractError(f"Extension contract missing/invalid '{field}'")


def _normalize_error_token(name: str, *, code_value: int) -> str:
    normalized = []
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


def _normalize_method_name(value: Any, *, field: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise A2AExtensionContractError(f"'{field}' must be a string if provided")
    normalized = value.strip()
    return normalized or None


def _resolve_jsonrpc_interface(card: AgentCard) -> JsonRpcInterface:
    jsonrpc_url: Optional[str] = None
    additional = getattr(card, "additional_interfaces", None) or []
    for iface in additional:
        transport = (getattr(iface, "transport", "") or "").strip().lower()
        url = (getattr(iface, "url", "") or "").strip()
        if transport == "jsonrpc" and url:
            jsonrpc_url = url
            break

    fallback_used = False
    if not jsonrpc_url:
        jsonrpc_url = (getattr(card, "url", "") or "").strip()
        fallback_used = True
    if not jsonrpc_url:
        raise A2AExtensionContractError(
            "Agent card is missing a JSON-RPC interface URL"
        )

    return JsonRpcInterface(url=jsonrpc_url, fallback_used=fallback_used)


def resolve_opencode_interrupt_callback(
    card: AgentCard,
) -> ResolvedInterruptCallbackExtension:
    capabilities = getattr(card, "capabilities", None)
    extensions = getattr(capabilities, "extensions", None) if capabilities else None
    if not extensions:
        raise A2AExtensionNotSupportedError("Agent does not declare any extensions")

    ext = None
    for candidate in extensions:
        if getattr(candidate, "uri", None) == OPENCODE_INTERRUPT_CALLBACK_URI:
            ext = candidate
            break
    if ext is None:
        raise A2AExtensionNotSupportedError(
            "OpenCode interrupt callback extension not found"
        )

    required = bool(getattr(ext, "required", False))
    params = _as_dict(getattr(ext, "params", None))
    methods = _as_dict(params.get("methods"))
    reply_permission_method = _normalize_method_name(
        methods.get("reply_permission"),
        field="methods.reply_permission",
    )
    reply_question_method = _normalize_method_name(
        methods.get("reply_question"),
        field="methods.reply_question",
    )
    reject_question_method = _normalize_method_name(
        methods.get("reject_question"),
        field="methods.reject_question",
    )

    errors = _as_dict(params.get("errors"))
    business_codes = _as_dict(errors.get("business_codes"))
    code_to_error: Dict[int, str] = {}
    for name, code in business_codes.items():
        try:
            code_value = _require_int(code, field="errors.business_codes.*")
        except A2AExtensionContractError:
            continue
        token = _normalize_error_token(str(name), code_value=code_value)
        code_to_error.setdefault(code_value, token)

    return ResolvedInterruptCallbackExtension(
        uri=OPENCODE_INTERRUPT_CALLBACK_URI,
        required=required,
        jsonrpc=_resolve_jsonrpc_interface(card),
        methods={
            "reply_permission": reply_permission_method,
            "reply_question": reply_question_method,
            "reject_question": reject_question_method,
        },
        business_code_map=code_to_error,
    )


__all__ = [
    "OPENCODE_INTERRUPT_CALLBACK_URI",
    "resolve_opencode_interrupt_callback",
]
