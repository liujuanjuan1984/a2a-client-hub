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
OPENCODE_SESSION_BINDING_URI = "urn:opencode-a2a:opencode-session-binding/v1"


def _as_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _require_str(value: Any, *, field: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise A2AExtensionContractError(f"Extension contract missing/invalid '{field}'")


def _normalize_method_name(value: Any, *, field: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise A2AExtensionContractError(f"'{field}' must be a string if provided")
    normalized = value.strip()
    return normalized or None


def _require_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool):
        raise A2AExtensionContractError(f"Extension contract missing/invalid '{field}'")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    raise A2AExtensionContractError(f"Extension contract missing/invalid '{field}'")


def _resolve_pagination_size(
    pagination: Dict[str, Any],
    *,
    mode: str,
    field: str,
    legacy_field: str | None = None,
) -> int:
    candidates = [field]
    if legacy_field:
        candidates.append(legacy_field)
    for key in candidates:
        if key not in pagination:
            continue
        return _require_int(
            pagination.get(key),
            field=f"pagination.{key}",
        )
    raise A2AExtensionContractError(
        f"Extension contract missing/invalid 'pagination.{field}' for mode '{mode}'"
    )


def _resolve_session_binding_metadata_key(
    extensions: list[Any],
) -> Optional[str]:
    for candidate in extensions:
        if getattr(candidate, "uri", None) != OPENCODE_SESSION_BINDING_URI:
            continue
        params = _as_dict(getattr(candidate, "params", None))
        return _require_str(params.get("metadata_key"), field="params.metadata_key")
    return None


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


def _parse_pagination_params(
    pagination: Dict[str, Any], *, mode: str
) -> tuple[tuple[str, ...], bool]:
    raw_params = pagination.get("params")
    params: list[str] = []
    if isinstance(raw_params, list):
        for item in raw_params:
            if not isinstance(item, str):
                continue
            token = item.strip().lower()
            if not token:
                continue
            if token in params:
                continue
            params.append(token)

    if not params:
        params = ["page", "size"] if mode == "page_size" else ["limit"]

    if mode == "page_size":
        if "page" not in params or "size" not in params:
            raise A2AExtensionContractError(
                "Extension pagination.params must include page and size for mode 'page_size'"
            )
        return tuple(params), False

    if "limit" not in params:
        raise A2AExtensionContractError(
            "Extension pagination.params must include limit for mode 'limit'"
        )
    return tuple(params), "offset" in params


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
        raise A2AExtensionNotSupportedError(
            "OpenCode session query extension not found"
        )

    required = bool(getattr(ext, "required", False))
    params: Dict[str, Any] = _as_dict(getattr(ext, "params", None))

    methods = _as_dict(params.get("methods"))
    list_sessions_method = _require_str(
        methods.get("list_sessions"), field="methods.list_sessions"
    )
    get_messages_method = _require_str(
        methods.get("get_session_messages"),
        field="methods.get_session_messages",
    )
    prompt_async_method = _normalize_method_name(
        methods.get("prompt_async"),
        field="methods.prompt_async",
    )

    pagination = _as_dict(params.get("pagination"))
    mode = _require_str(pagination.get("mode"), field="pagination.mode")
    if mode == "page_size":
        default_size = _resolve_pagination_size(
            pagination,
            mode=mode,
            field="default_size",
        )
        max_size = _resolve_pagination_size(
            pagination,
            mode=mode,
            field="max_size",
        )
    elif mode == "limit":
        default_size = _resolve_pagination_size(
            pagination,
            mode=mode,
            field="default_limit",
            legacy_field="default_size",
        )
        max_size = _resolve_pagination_size(
            pagination,
            mode=mode,
            field="max_limit",
            legacy_field="max_size",
        )
    else:
        raise A2AExtensionContractError(
            "Extension pagination.mode must be one of 'page_size' or 'limit'"
        )
    if default_size <= 0 or max_size <= 0 or default_size > max_size:
        raise A2AExtensionContractError("Extension pagination sizes are invalid")
    pagination_params, supports_offset = _parse_pagination_params(pagination, mode=mode)

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

    session_binding_metadata_key = _resolve_session_binding_metadata_key(extensions)

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
        raise A2AExtensionContractError(
            "Agent card is missing a JSON-RPC interface URL"
        )

    return ResolvedExtension(
        uri=OPENCODE_SESSION_QUERY_URI,
        required=required,
        jsonrpc=JsonRpcInterface(url=jsonrpc_url, fallback_used=fallback_used),
        methods={
            "list_sessions": list_sessions_method,
            "get_session_messages": get_messages_method,
            "prompt_async": prompt_async_method,
        },
        pagination=PageSizePagination(
            mode=mode,
            default_size=default_size,
            max_size=max_size,
            params=pagination_params,
            supports_offset=supports_offset,
        ),
        business_code_map=code_to_error,
        session_binding_metadata_key=session_binding_metadata_key,
        result_envelope=envelope_mapping,
    )


__all__ = [
    "OPENCODE_SESSION_BINDING_URI",
    "OPENCODE_SESSION_QUERY_URI",
    "resolve_opencode_session_query",
]
