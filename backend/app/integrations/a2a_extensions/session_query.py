"""Shared session query extension resolver and helpers."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from a2a.types import AgentCard

from app.integrations.a2a_extensions.contract_utils import (
    as_dict,
    build_business_code_map,
    normalize_method_name,
    require_int,
    require_str,
    resolve_jsonrpc_interface,
)
from app.integrations.a2a_extensions.errors import (
    A2AExtensionContractError,
    A2AExtensionNotSupportedError,
)
from app.integrations.a2a_extensions.shared_contract import (
    SHARED_SESSION_QUERY_URI,
    SUPPORTED_SESSION_QUERY_URIS,
)
from app.integrations.a2a_extensions.types import PageSizePagination, ResolvedExtension


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
        return require_int(
            pagination.get(key),
            field=f"pagination.{key}",
        )
    raise A2AExtensionContractError(
        f"Extension contract missing/invalid 'pagination.{field}' for mode '{mode}'"
    )


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
            if not token or token in params:
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


def resolve_session_query(card: AgentCard) -> ResolvedExtension:
    """Resolve the shared session query extension from an Agent Card."""

    capabilities = getattr(card, "capabilities", None)
    extensions = getattr(capabilities, "extensions", None) if capabilities else None
    if not extensions:
        raise A2AExtensionNotSupportedError("Agent does not declare any extensions")

    ext = None
    for candidate in extensions:
        if getattr(candidate, "uri", None) in SUPPORTED_SESSION_QUERY_URIS:
            ext = candidate
            break
    if ext is None:
        raise A2AExtensionNotSupportedError("Shared session query extension not found")

    required = bool(getattr(ext, "required", False))
    params: Dict[str, Any] = as_dict(getattr(ext, "params", None))
    raw_provider = params.get("provider")
    if raw_provider is None:
        provider = "opencode"
    else:
        provider = require_str(raw_provider, field="params.provider").lower()

    methods = as_dict(params.get("methods"))
    list_sessions_method = require_str(
        methods.get("list_sessions"), field="methods.list_sessions"
    )
    get_messages_method = require_str(
        methods.get("get_session_messages"),
        field="methods.get_session_messages",
    )
    prompt_async_method = normalize_method_name(
        methods.get("prompt_async"),
        field="methods.prompt_async",
    )

    pagination = as_dict(params.get("pagination"))
    mode = require_str(pagination.get("mode"), field="pagination.mode")
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

    errors = as_dict(params.get("errors"))
    code_to_error = build_business_code_map(errors.get("business_codes"))

    result_envelope = params.get("result_envelope")
    envelope_mapping: Optional[Mapping[str, Any]] = None
    if isinstance(result_envelope, dict):
        envelope_mapping = dict(result_envelope)

    return ResolvedExtension(
        uri=str(getattr(ext, "uri", SHARED_SESSION_QUERY_URI)),
        required=required,
        provider=provider,
        jsonrpc=resolve_jsonrpc_interface(card),
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
        result_envelope=envelope_mapping,
    )


__all__ = ["resolve_session_query"]
