"""OpenCode session query extension resolver and helpers."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from a2a.types import AgentCard

from app.integrations.a2a_extensions.errors import (
    A2AExtensionContractError,
    A2AExtensionNotSupportedError,
)
from app.integrations.a2a_extensions.types import (
    JsonRpcInterface,
    PageSizePagination,
    ResolvedExtension,
)

OPENCODE_SESSION_QUERY_URI = "urn:opencode-a2a:opencode-session-query/v1"


def _as_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _require_str(value: Any, *, field: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise A2AExtensionContractError(f"Extension contract missing/invalid '{field}'")


def _require_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool):
        raise A2AExtensionContractError(f"Extension contract missing/invalid '{field}'")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    raise A2AExtensionContractError(f"Extension contract missing/invalid '{field}'")


def resolve_opencode_session_query(card: AgentCard) -> ResolvedExtension:
    """Resolve the OpenCode session query extension from an Agent Card."""

    capabilities = getattr(card, "capabilities", None)
    extensions = getattr(capabilities, "extensions", None) if capabilities else None
    if not extensions:
        raise A2AExtensionNotSupportedError("Agent does not declare any extensions")

    ext = None
    for candidate in extensions:
        if getattr(candidate, "uri", None) == OPENCODE_SESSION_QUERY_URI:
            ext = candidate
            break
    if ext is None:
        raise A2AExtensionNotSupportedError("OpenCode session query extension not found")

    required = bool(getattr(ext, "required", False))
    params: Dict[str, Any] = _as_dict(getattr(ext, "params", None))

    methods = _as_dict(params.get("methods"))
    list_sessions_method = _require_str(methods.get("list_sessions"), field="methods.list_sessions")
    get_messages_method = _require_str(
        methods.get("get_session_messages"),
        field="methods.get_session_messages",
    )

    pagination = _as_dict(params.get("pagination"))
    mode = _require_str(pagination.get("mode"), field="pagination.mode")
    if mode != "page_size":
        raise A2AExtensionContractError("Extension pagination.mode must be 'page_size'")
    default_size = _require_int(pagination.get("default_size"), field="pagination.default_size")
    max_size = _require_int(pagination.get("max_size"), field="pagination.max_size")
    if default_size <= 0 or max_size <= 0 or default_size > max_size:
        raise A2AExtensionContractError("Extension pagination sizes are invalid")

    errors = _as_dict(params.get("errors"))
    business_codes = _as_dict(errors.get("business_codes"))
    # Map known business codes to stable API error_code values.
    code_to_error: Dict[int, str] = {}
    for _, code in business_codes.items():
        try:
            code_value = _require_int(code, field="errors.business_codes.*")
        except A2AExtensionContractError:
            continue
        if code_value == -32001:
            code_to_error[code_value] = "session_not_found"
        elif code_value == -32002:
            code_to_error[code_value] = "upstream_unreachable"
        elif code_value == -32003:
            code_to_error[code_value] = "upstream_http_error"

    # Ensure the documented codes map even if upstream uses different keys.
    code_to_error.setdefault(-32001, "session_not_found")
    code_to_error.setdefault(-32002, "upstream_unreachable")
    code_to_error.setdefault(-32003, "upstream_http_error")

    result_envelope = params.get("result_envelope")
    envelope_mapping: Optional[Mapping[str, Any]] = None
    if isinstance(result_envelope, dict):
        envelope_mapping = dict(result_envelope)

    # Pick the JSON-RPC interface URL from additional_interfaces; fall back to card.url.
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
        raise A2AExtensionContractError("Agent card is missing a JSON-RPC interface URL")

    return ResolvedExtension(
        uri=OPENCODE_SESSION_QUERY_URI,
        required=required,
        jsonrpc=JsonRpcInterface(url=jsonrpc_url, fallback_used=fallback_used),
        methods={
            "list_sessions": list_sessions_method,
            "get_session_messages": get_messages_method,
        },
        pagination=PageSizePagination(mode=mode, default_size=default_size, max_size=max_size),
        business_code_map=code_to_error,
        result_envelope=envelope_mapping,
    )


__all__ = ["OPENCODE_SESSION_QUERY_URI", "resolve_opencode_session_query"]

