"""Provider/model discovery extension resolver and helpers."""

from __future__ import annotations

from typing import Any, Dict

from a2a.types import AgentCard

from app.integrations.a2a_extensions.contract_utils import (
    as_dict,
    build_business_code_map,
    normalize_method_name,
    resolve_jsonrpc_interface,
)
from app.integrations.a2a_extensions.errors import (
    A2AExtensionNotSupportedError,
)
from app.integrations.a2a_extensions.shared_contract import (
    PROVIDER_DISCOVERY_URI,
    SUPPORTED_PROVIDER_DISCOVERY_URIS,
    is_supported_extension_uri,
)
from app.integrations.a2a_extensions.types import ResolvedProviderDiscoveryExtension


def resolve_provider_discovery(
    card: AgentCard,
) -> ResolvedProviderDiscoveryExtension:
    """Resolve the provider-discovery extension from an Agent Card."""

    capabilities = getattr(card, "capabilities", None)
    extensions = getattr(capabilities, "extensions", None) if capabilities else None
    if not extensions:
        raise A2AExtensionNotSupportedError("Agent does not declare any extensions")

    ext = None
    for candidate in extensions:
        if is_supported_extension_uri(
            getattr(candidate, "uri", None),
            SUPPORTED_PROVIDER_DISCOVERY_URIS,
        ):
            ext = candidate
            break
    if ext is None:
        raise A2AExtensionNotSupportedError(
            "OpenCode provider discovery extension not found"
        )

    required = bool(getattr(ext, "required", False))
    params: Dict[str, Any] = as_dict(getattr(ext, "params", None))
    methods = as_dict(params.get("methods"))
    list_providers_method = normalize_method_name(
        methods.get("list_providers"),
        field="methods.list_providers",
    )
    list_models_method = normalize_method_name(
        methods.get("list_models"),
        field="methods.list_models",
    )

    errors = as_dict(params.get("errors"))
    code_to_error = build_business_code_map(errors.get("business_codes"))

    return ResolvedProviderDiscoveryExtension(
        uri=str(getattr(ext, "uri", PROVIDER_DISCOVERY_URI)),
        required=required,
        provider="opencode",
        metadata_namespace="opencode",
        jsonrpc=resolve_jsonrpc_interface(card),
        methods={
            "list_providers": list_providers_method,
            "list_models": list_models_method,
        },
        business_code_map=code_to_error,
    )
