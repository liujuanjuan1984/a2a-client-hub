"""Shared session query extension resolver and helpers."""

from __future__ import annotations

from typing import Any, Dict, Literal

from a2a.types import AgentCard

from app.integrations.a2a_extensions import contract_utils
from app.integrations.a2a_extensions.errors import (
    A2AExtensionContractError,
    A2AExtensionNotSupportedError,
)
from app.integrations.a2a_extensions.shared_contract import (
    CODEX_SHARED_SESSION_QUERY_URI,
    SHARED_SESSION_QUERY_URI,
    SUPPORTED_SESSION_QUERY_URIS,
    is_supported_extension_uri,
)
from app.integrations.a2a_extensions.types import (
    MessageCursorPaginationContract,
    PageSizePagination,
    ResolvedExtension,
    ResolvedSessionControlMethodCapability,
    ResultEnvelopeMapping,
    SessionListFilterFieldContract,
    SessionListFiltersContract,
)

LIMIT_WITH_OPTIONAL_CURSOR_MODE = "limit_and_optional_cursor"


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
        return contract_utils.require_int(
            pagination.get(key),
            field=f"pagination.{key}",
        )
    raise A2AExtensionContractError(
        f"Extension contract missing/invalid 'pagination.{field}' for mode '{mode}'"
    )


def _parse_pagination_params(
    pagination: Dict[str, Any], *, mode: str, declared_mode: str
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
        if mode == "page_size":
            params = ["page", "size"]
        elif declared_mode == LIMIT_WITH_OPTIONAL_CURSOR_MODE:
            params = ["limit", "before"]
        else:
            params = ["limit"]

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
    if declared_mode == LIMIT_WITH_OPTIONAL_CURSOR_MODE and "offset" in params:
        raise A2AExtensionContractError(
            "Extension pagination.params must not include offset for mode "
            "'limit_and_optional_cursor'"
        )
    return tuple(params), "offset" in params


def _resolve_result_envelope_field(value: Any, *, field: str, default: str) -> str:
    if value is None or value is True:
        return default
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise A2AExtensionContractError(f"Extension contract missing/invalid '{field}'")


def _resolve_result_envelope(value: Any) -> ResultEnvelopeMapping:
    if value is None:
        return ResultEnvelopeMapping()
    if not isinstance(value, dict):
        raise A2AExtensionContractError(
            "Extension contract missing/invalid 'result_envelope'"
        )

    unknown_keys = sorted(
        key for key in value.keys() if key not in {"items", "pagination", "raw"}
    )
    if unknown_keys:
        raise A2AExtensionContractError(
            "Extension result_envelope contains unsupported keys"
        )

    return ResultEnvelopeMapping(
        items=_resolve_result_envelope_field(
            value.get("items"),
            field="result_envelope.items",
            default="items",
        ),
        pagination=_resolve_result_envelope_field(
            value.get("pagination"),
            field="result_envelope.pagination",
            default="pagination",
        ),
        raw=_resolve_result_envelope_field(
            value.get("raw"),
            field="result_envelope.raw",
            default="raw",
        ),
    )


def _resolve_message_cursor_pagination(
    pagination: Dict[str, Any],
    *,
    pagination_mode: str,
    get_messages_method: str,
) -> MessageCursorPaginationContract:
    raw_cursor_applies_to = pagination.get("cursor_applies_to")
    cursor_applies_to: set[str] = set()
    if isinstance(raw_cursor_applies_to, list):
        for item in raw_cursor_applies_to:
            if isinstance(item, str) and item.strip():
                cursor_applies_to.add(item.strip())

    if cursor_applies_to and get_messages_method not in cursor_applies_to:
        return MessageCursorPaginationContract()

    raw_cursor_param = pagination.get("cursor_param")
    raw_result_cursor_field = pagination.get("result_cursor_field")
    if raw_cursor_param is None and raw_result_cursor_field is None:
        if pagination_mode == LIMIT_WITH_OPTIONAL_CURSOR_MODE:
            raise A2AExtensionContractError(
                "Extension contract missing/invalid cursor pagination fields for mode "
                "'limit_and_optional_cursor'"
            )
        return MessageCursorPaginationContract()
    if not isinstance(raw_cursor_param, str) or not raw_cursor_param.strip():
        raise A2AExtensionContractError(
            "Extension contract missing/invalid 'pagination.cursor_param'"
        )
    if (
        not isinstance(raw_result_cursor_field, str)
        or not raw_result_cursor_field.strip()
    ):
        raise A2AExtensionContractError(
            "Extension contract missing/invalid 'pagination.result_cursor_field'"
        )
    return MessageCursorPaginationContract(
        cursor_param=raw_cursor_param.strip(),
        result_cursor_field=raw_result_cursor_field.strip(),
    )


def _resolve_method_contract_param_names(
    params: Dict[str, Any],
    *,
    method_name: str,
    field_name: Literal["required", "optional", "unsupported"],
) -> set[str]:
    raw_method_contracts = params.get("method_contracts")
    if raw_method_contracts is None:
        return set()

    method_contracts = contract_utils.as_dict(raw_method_contracts)
    raw_method_contract = method_contracts.get(method_name)
    if raw_method_contract is None:
        return set()

    method_contract = contract_utils.as_dict(raw_method_contract)
    raw_params_contract = method_contract.get("params")
    if raw_params_contract is None:
        return set()

    params_contract = contract_utils.as_dict(raw_params_contract)
    candidate_fields = {
        "required": ("required", "required_params"),
        "optional": ("optional", "optional_params"),
        "unsupported": ("unsupported", "unsupported_params"),
    }[field_name]

    resolved_params: set[str] = set()
    for candidate_field in candidate_fields:
        raw_param_names = params_contract.get(candidate_field)
        if raw_param_names is None:
            continue
        if not isinstance(raw_param_names, list):
            raise A2AExtensionContractError(
                f"Extension method_contracts.{method_name}.params.{candidate_field} must be an array if provided"
            )
        for item in raw_param_names:
            if not isinstance(item, str):
                raise A2AExtensionContractError(
                    f"Extension method_contracts.{method_name}.params.{candidate_field} must contain only strings"
                )
            token = item.strip()
            if token:
                resolved_params.add(token)
    return resolved_params


def _is_empty_session_list_filter_contract(
    contract: SessionListFilterFieldContract,
) -> bool:
    return contract.top_level_param is None and contract.query_param is None


def _validate_codex_session_query_compatibility(
    *,
    params: Dict[str, Any],
    ext: ResolvedExtension,
    declared_mode: str,
) -> None:
    if declared_mode != "limit":
        raise A2AExtensionContractError(
            "Codex session query compatibility requires pagination.mode to be 'limit'"
        )

    if ext.pagination.supports_offset:
        raise A2AExtensionContractError(
            "Codex session query compatibility does not support offset pagination"
        )

    if ext.message_cursor_pagination.cursor_param is not None:
        raise A2AExtensionContractError(
            "Codex session query compatibility does not support cursor pagination"
        )

    if not _is_empty_session_list_filter_contract(ext.session_list_filters.directory):
        raise A2AExtensionContractError(
            "Codex session query compatibility does not support directory filters"
        )
    if not _is_empty_session_list_filter_contract(ext.session_list_filters.roots):
        raise A2AExtensionContractError(
            "Codex session query compatibility does not support roots filters"
        )
    if not _is_empty_session_list_filter_contract(ext.session_list_filters.start):
        raise A2AExtensionContractError(
            "Codex session query compatibility does not support start filters"
        )
    if not _is_empty_session_list_filter_contract(ext.session_list_filters.search):
        raise A2AExtensionContractError(
            "Codex session query compatibility does not support search filters"
        )

    prompt_async_method = ext.methods.get("prompt_async")
    if prompt_async_method:
        unsupported_required = _resolve_method_contract_param_names(
            params,
            method_name=prompt_async_method,
            field_name="required",
        ) - {"session_id", "request.parts"}
        if unsupported_required:
            raise A2AExtensionContractError(
                "Codex session query prompt_async declares unsupported required params"
            )

    command_method = ext.methods.get("command")
    if command_method:
        command_required = _resolve_method_contract_param_names(
            params,
            method_name=command_method,
            field_name="required",
        )
        if "request.arguments" in command_required:
            raise A2AExtensionContractError(
                "Codex session query command must not require request.arguments"
            )
        unsupported_required = command_required - {"session_id", "request.command"}
        if unsupported_required:
            raise A2AExtensionContractError(
                "Codex session query command declares unsupported required params"
            )


def _resolve_session_list_filter_field(
    optional_params: set[str],
    *,
    field_name: str,
) -> SessionListFilterFieldContract:
    top_level_param = field_name if field_name in optional_params else None
    query_param = field_name if f"query.{field_name}" in optional_params else None
    return SessionListFilterFieldContract(
        top_level_param=top_level_param,
        query_param=query_param,
    )


def _resolve_session_list_filters(
    params: Dict[str, Any],
    *,
    list_sessions_method: str,
) -> SessionListFiltersContract:
    optional_params = _resolve_method_contract_param_names(
        params,
        method_name=list_sessions_method,
        field_name="optional",
    )
    if not optional_params:
        return SessionListFiltersContract()

    return SessionListFiltersContract(
        directory=_resolve_session_list_filter_field(
            optional_params, field_name="directory"
        ),
        roots=_resolve_session_list_filter_field(optional_params, field_name="roots"),
        start=_resolve_session_list_filter_field(optional_params, field_name="start"),
        search=_resolve_session_list_filter_field(optional_params, field_name="search"),
    )


def _resolve_control_method_flag(
    raw_flags: Dict[str, Any],
    *,
    method_key: str,
    method_name: str | None,
) -> tuple[str | None, Any]:
    if method_name is not None and method_name in raw_flags:
        return method_name, raw_flags.get(method_name)
    if method_key in raw_flags:
        return method_key, raw_flags.get(method_key)

    suffix = f".{method_key}"
    suffix_matches = [
        key for key in raw_flags.keys() if isinstance(key, str) and key.endswith(suffix)
    ]
    if len(suffix_matches) == 1:
        matched_key = suffix_matches[0]
        return matched_key, raw_flags.get(matched_key)
    return None, None


def _find_session_query_extension(
    card: AgentCard,
) -> Any:
    capabilities = getattr(card, "capabilities", None)
    extensions = getattr(capabilities, "extensions", None) if capabilities else None
    if not extensions:
        raise A2AExtensionNotSupportedError("Agent does not declare any extensions")

    for candidate in extensions:
        uri = getattr(candidate, "uri", None)
        if is_supported_extension_uri(uri, SUPPORTED_SESSION_QUERY_URIS):
            return candidate
    raise A2AExtensionNotSupportedError("Shared session query extension not found")


def _uses_legacy_limit_fields(pagination: Dict[str, Any]) -> bool:
    return bool(
        pagination.get("mode") == "limit"
        and (
            "default_size" in pagination
            or "max_size" in pagination
            or "page" in pagination.get("params", [])
        )
    )


def _resolve_extension(
    card: AgentCard,
    *,
    variant: str,
) -> ResolvedExtension:
    ext = _find_session_query_extension(card)

    required = bool(getattr(ext, "required", False))
    params: Dict[str, Any] = contract_utils.as_dict(getattr(ext, "params", None))
    raw_provider = params.get("provider")
    if raw_provider is None:
        provider = "opencode"
    else:
        provider = contract_utils.require_str(
            raw_provider, field="params.provider"
        ).lower()

    methods = contract_utils.as_dict(params.get("methods"))
    list_sessions_method = contract_utils.require_str(
        methods.get("list_sessions"), field="methods.list_sessions"
    )
    get_messages_method = contract_utils.require_str(
        methods.get("get_session_messages"),
        field="methods.get_session_messages",
    )
    get_session_method = contract_utils.normalize_method_name(
        methods.get("get_session"),
        field="methods.get_session",
    )
    get_session_children_method = contract_utils.normalize_method_name(
        methods.get("get_session_children"),
        field="methods.get_session_children",
    )
    get_session_todo_method = contract_utils.normalize_method_name(
        methods.get("get_session_todo"),
        field="methods.get_session_todo",
    )
    get_session_diff_method = contract_utils.normalize_method_name(
        methods.get("get_session_diff"),
        field="methods.get_session_diff",
    )
    get_session_message_method = contract_utils.normalize_method_name(
        methods.get("get_session_message"),
        field="methods.get_session_message",
    )
    prompt_async_method = contract_utils.normalize_method_name(
        methods.get("prompt_async"),
        field="methods.prompt_async",
    )
    command_method = contract_utils.normalize_method_name(
        methods.get("command"),
        field="methods.command",
    )
    fork_method = contract_utils.normalize_method_name(
        methods.get("fork"),
        field="methods.fork",
    )
    share_method = contract_utils.normalize_method_name(
        methods.get("share"),
        field="methods.share",
    )
    unshare_method = contract_utils.normalize_method_name(
        methods.get("unshare"),
        field="methods.unshare",
    )
    summarize_method = contract_utils.normalize_method_name(
        methods.get("summarize"),
        field="methods.summarize",
    )
    revert_method = contract_utils.normalize_method_name(
        methods.get("revert"),
        field="methods.revert",
    )
    unrevert_method = contract_utils.normalize_method_name(
        methods.get("unrevert"),
        field="methods.unrevert",
    )
    shell_method = contract_utils.normalize_method_name(
        methods.get("shell"),
        field="methods.shell",
    )

    pagination = contract_utils.as_dict(params.get("pagination"))
    declared_mode = contract_utils.require_str(
        pagination.get("mode"), field="pagination.mode"
    )
    mode = (
        "limit" if declared_mode == LIMIT_WITH_OPTIONAL_CURSOR_MODE else declared_mode
    )
    uses_legacy_limit_fields = _uses_legacy_limit_fields(pagination)
    is_codex_variant = getattr(ext, "uri", None) == CODEX_SHARED_SESSION_QUERY_URI
    if variant == "codex" and not is_codex_variant:
        raise A2AExtensionNotSupportedError(
            "Codex session query compatibility variant not found"
        )
    if variant in {"canonical", "generic"} and uses_legacy_limit_fields:
        raise A2AExtensionContractError(
            "Shared session query legacy pagination fields are no longer supported; "
            "use pagination.default_limit/max_limit for mode 'limit'"
        )
    if variant == "canonical" and is_codex_variant:
        raise A2AExtensionContractError(
            "Codex session query variants must use the explicit codex resolver"
        )

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
        )
        max_size = _resolve_pagination_size(
            pagination,
            mode=mode,
            field="max_limit",
        )
    else:
        raise A2AExtensionContractError(
            "Extension pagination.mode must be one of 'page_size', 'limit', or "
            "'limit_and_optional_cursor'"
        )
    if default_size <= 0 or max_size <= 0 or default_size > max_size:
        raise A2AExtensionContractError("Extension pagination sizes are invalid")
    pagination_params, supports_offset = _parse_pagination_params(
        pagination,
        mode=mode,
        declared_mode=declared_mode,
    )

    errors = contract_utils.as_dict(params.get("errors"))
    code_to_error = contract_utils.build_business_code_map(errors.get("business_codes"))

    envelope_mapping = _resolve_result_envelope(params.get("result_envelope"))
    message_cursor_pagination = _resolve_message_cursor_pagination(
        pagination,
        pagination_mode=declared_mode,
        get_messages_method=get_messages_method,
    )
    session_list_filters = _resolve_session_list_filters(
        params,
        list_sessions_method=list_sessions_method,
    )

    resolved = ResolvedExtension(
        uri=str(getattr(ext, "uri", SHARED_SESSION_QUERY_URI)),
        required=required,
        provider=provider,
        jsonrpc=contract_utils.resolve_jsonrpc_interface(card),
        methods={
            "list_sessions": list_sessions_method,
            "get_session": get_session_method,
            "get_session_children": get_session_children_method,
            "get_session_todo": get_session_todo_method,
            "get_session_diff": get_session_diff_method,
            "get_session_message": get_session_message_method,
            "get_session_messages": get_messages_method,
            "prompt_async": prompt_async_method,
            "command": command_method,
            "fork": fork_method,
            "share": share_method,
            "unshare": unshare_method,
            "summarize": summarize_method,
            "revert": revert_method,
            "unrevert": unrevert_method,
            "shell": shell_method,
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
        message_cursor_pagination=message_cursor_pagination,
        session_list_filters=session_list_filters,
    )
    if is_codex_variant:
        _validate_codex_session_query_compatibility(
            params=params,
            ext=resolved,
            declared_mode=declared_mode,
        )
    return resolved


def resolve_session_query(card: AgentCard) -> ResolvedExtension:
    """Resolve the shared session query extension from an Agent Card."""

    return _resolve_extension(
        card,
        variant="generic",
    )


def resolve_canonical_session_query(card: AgentCard) -> ResolvedExtension:
    """Resolve the canonical shared session query contract only."""

    return _resolve_extension(
        card,
        variant="canonical",
    )


def resolve_codex_session_query(card: AgentCard) -> ResolvedExtension:
    """Resolve the Codex-compatible shared session query contract explicitly."""

    return _resolve_extension(
        card,
        variant="codex",
    )


def resolve_session_query_control_methods(
    card: AgentCard,
    *,
    ext: ResolvedExtension,
) -> dict[str, ResolvedSessionControlMethodCapability]:
    """Resolve per-method session control capability metadata."""

    raw_ext = _find_session_query_extension(card)
    params: Dict[str, Any] = contract_utils.as_dict(getattr(raw_ext, "params", None))
    raw_flags = contract_utils.as_dict(params.get("control_method_flags"))
    control_methods: dict[str, ResolvedSessionControlMethodCapability] = {}

    for method_key in ("prompt_async", "command", "shell"):
        method_name = contract_utils.normalize_method_name(
            ext.methods.get(method_key),
            field=f"methods.{method_key}",
        )
        declared = method_name is not None
        enabled_by_default: bool | None = None
        config_key: str | None = None
        availability: Literal["always", "conditional", "unsupported"] = (
            "always" if declared else "unsupported"
        )

        raw_flag_key, raw_flag = _resolve_control_method_flag(
            raw_flags,
            method_key=method_key,
            method_name=method_name,
        )
        if raw_flag is not None:
            if not isinstance(raw_flag, dict):
                raise A2AExtensionContractError(
                    f"'control_method_flags.{raw_flag_key}' must be an object if provided"
                )

            unknown_keys = sorted(
                key
                for key in raw_flag.keys()
                if key not in {"enabled_by_default", "config_key"}
            )
            if unknown_keys:
                raise A2AExtensionContractError(
                    f"'control_method_flags.{raw_flag_key}' contains unsupported keys"
                )

            raw_enabled_by_default = raw_flag.get("enabled_by_default")
            if raw_enabled_by_default is not None:
                if not isinstance(raw_enabled_by_default, bool):
                    raise A2AExtensionContractError(
                        f"'control_method_flags.{raw_flag_key}.enabled_by_default' must be a boolean if provided"
                    )
                enabled_by_default = raw_enabled_by_default

            raw_config_key = raw_flag.get("config_key")
            if raw_config_key is not None:
                config_key = contract_utils.require_str(
                    raw_config_key,
                    field=f"control_method_flags.{raw_flag_key}.config_key",
                )

            availability = "conditional"

        control_methods[method_key] = ResolvedSessionControlMethodCapability(
            method=method_name,
            declared=declared,
            availability=availability,
            enabled_by_default=enabled_by_default,
            config_key=config_key,
        )

    return control_methods
