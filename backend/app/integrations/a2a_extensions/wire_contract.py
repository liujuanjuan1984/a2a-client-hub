"""Wire-contract extension resolver and helpers."""

from __future__ import annotations

from typing import Any, Dict

from a2a.types import AgentCard

from app.integrations.a2a_extensions.contract_utils import (
    as_dict,
    normalize_string_list,
    require_int,
    require_str,
)
from app.integrations.a2a_extensions.errors import (
    A2AExtensionContractError,
    A2AExtensionNotSupportedError,
)
from app.integrations.a2a_extensions.shared_contract import (
    SUPPORTED_WIRE_CONTRACT_URIS,
    WIRE_CONTRACT_URI,
    is_supported_extension_uri,
    normalize_known_extension_uri,
)
from app.integrations.a2a_extensions.types import (
    ResolvedConditionalMethodAvailability,
    ResolvedUnsupportedMethodErrorContract,
    ResolvedWireContractExtension,
)


def _normalize_method_availability_map(
    value: Any,
    *,
    field: str,
) -> Dict[str, ResolvedConditionalMethodAvailability]:
    if not isinstance(value, dict):
        raise A2AExtensionContractError(f"Extension contract missing/invalid '{field}'")

    resolved: Dict[str, ResolvedConditionalMethodAvailability] = {}
    for method_name, item in value.items():
        normalized_method = require_str(method_name, field=field)
        entry = as_dict(item)
        if not entry:
            raise A2AExtensionContractError(
                f"Extension contract missing/invalid '{field}.{normalized_method}'"
            )
        toggle = entry.get("toggle")
        resolved[normalized_method] = ResolvedConditionalMethodAvailability(
            reason=require_str(
                entry.get("reason"),
                field=f"{field}.{normalized_method}.reason",
            ),
            toggle=(
                require_str(toggle, field=f"{field}.{normalized_method}.toggle")
                if toggle is not None
                else None
            ),
        )
    return resolved


def _resolve_unsupported_method_error(
    value: Any,
) -> ResolvedUnsupportedMethodErrorContract:
    payload = as_dict(value)
    if not payload:
        raise A2AExtensionContractError(
            "Extension contract missing/invalid 'params.unsupported_method_error'"
        )

    return ResolvedUnsupportedMethodErrorContract(
        code=require_int(
            payload.get("code"),
            field="params.unsupported_method_error.code",
        ),
        type=require_str(
            payload.get("type"),
            field="params.unsupported_method_error.type",
        ),
        data_fields=normalize_string_list(
            payload.get("data_fields"),
            field="params.unsupported_method_error.data_fields",
            allow_empty=False,
        ),
    )


def resolve_wire_contract(card: AgentCard) -> ResolvedWireContractExtension:
    """Resolve the wire-contract extension from an Agent Card."""

    capabilities = getattr(card, "capabilities", None)
    extensions = getattr(capabilities, "extensions", None) if capabilities else None
    if not extensions:
        raise A2AExtensionNotSupportedError("Agent does not declare any extensions")

    ext = None
    for candidate in extensions:
        if is_supported_extension_uri(
            getattr(candidate, "uri", None),
            SUPPORTED_WIRE_CONTRACT_URIS,
        ):
            ext = candidate
            break
    if ext is None:
        raise A2AExtensionNotSupportedError("Wire contract extension not found")

    params = as_dict(getattr(ext, "params", None))
    core = as_dict(params.get("core"))
    extensions_params = as_dict(params.get("extensions"))

    return ResolvedWireContractExtension(
        uri=str(getattr(ext, "uri", WIRE_CONTRACT_URI)),
        required=bool(getattr(ext, "required", False)),
        protocol_version=require_str(
            params.get("protocol_version"),
            field="params.protocol_version",
        ),
        preferred_transport=require_str(
            params.get("preferred_transport"),
            field="params.preferred_transport",
        ),
        additional_transports=normalize_string_list(
            params.get("additional_transports"),
            field="params.additional_transports",
            allow_missing=True,
            allow_empty=True,
        ),
        core_jsonrpc_methods=normalize_string_list(
            core.get("jsonrpc_methods"),
            field="params.core.jsonrpc_methods",
            allow_empty=False,
        ),
        core_http_endpoints=normalize_string_list(
            core.get("http_endpoints"),
            field="params.core.http_endpoints",
            allow_empty=False,
        ),
        extension_jsonrpc_methods=normalize_string_list(
            extensions_params.get("jsonrpc_methods"),
            field="params.extensions.jsonrpc_methods",
            allow_missing=True,
            allow_empty=True,
        ),
        conditionally_available_methods=_normalize_method_availability_map(
            extensions_params.get("conditionally_available_methods"),
            field="params.extensions.conditionally_available_methods",
        ),
        extension_uris=tuple(
            normalize_known_extension_uri(item) or item
            for item in normalize_string_list(
                extensions_params.get("extension_uris"),
                field="params.extensions.extension_uris",
                allow_missing=True,
                allow_empty=True,
            )
        ),
        all_jsonrpc_methods=normalize_string_list(
            params.get("all_jsonrpc_methods"),
            field="params.all_jsonrpc_methods",
            allow_empty=False,
        ),
        service_behaviors=as_dict(params.get("service_behaviors")),
        unsupported_method_error=_resolve_unsupported_method_error(
            params.get("unsupported_method_error")
        ),
    )
