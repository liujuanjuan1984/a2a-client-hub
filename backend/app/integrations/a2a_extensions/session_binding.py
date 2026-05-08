"""Session binding extension resolver and helpers."""

from __future__ import annotations

from a2a.types import AgentCard

from app.integrations.a2a_extensions.contract_utils import (
    as_dict,
    normalize_string_list,
    require_str,
)
from app.integrations.a2a_extensions.errors import (
    A2AExtensionContractError,
    A2AExtensionNotSupportedError,
)
from app.integrations.a2a_extensions.shared_contract import (
    SESSION_BINDING_URI,
    SHARED_SESSION_ID_FIELD,
    SUPPORTED_SESSION_BINDING_URIS,
    infer_provider_key_from_extension_uri,
)
from app.integrations.a2a_extensions.types import ResolvedSessionBindingExtension


def resolve_session_binding(card: AgentCard) -> ResolvedSessionBindingExtension:
    capabilities = getattr(card, "capabilities", None)
    extensions = getattr(capabilities, "extensions", None) if capabilities else None
    if not extensions:
        raise A2AExtensionNotSupportedError("Agent does not declare any extensions")

    ext = None
    for candidate in extensions:
        if getattr(candidate, "uri", None) in SUPPORTED_SESSION_BINDING_URIS:
            ext = candidate
            break
    if ext is None:
        raise A2AExtensionNotSupportedError("Session binding extension not found")

    required = bool(getattr(ext, "required", False))
    params = as_dict(getattr(ext, "params", None))
    resolved_uri = str(getattr(ext, "uri", SESSION_BINDING_URI))
    raw_provider = params.get("provider")
    if raw_provider is None:
        provider = infer_provider_key_from_extension_uri(resolved_uri)
    else:
        provider = require_str(raw_provider, field="params.provider").lower()

    metadata_field = require_str(
        params.get("metadata_field"),
        field="params.metadata_field",
    )
    if metadata_field != SHARED_SESSION_ID_FIELD:
        raise A2AExtensionContractError(
            f"Session binding metadata_field must be '{SHARED_SESSION_ID_FIELD}'"
        )

    behavior = require_str(
        params.get("behavior"),
        field="params.behavior",
    )
    supported_metadata = normalize_string_list(
        params.get("supported_metadata"),
        field="params.supported_metadata",
        allow_missing=True,
    )
    adapter_metadata_fields = normalize_string_list(
        params.get("provider_private_metadata"),
        field="params.provider_private_metadata",
        allow_missing=True,
    )
    shared_workspace = params.get("shared_workspace_across_consumers")
    if shared_workspace is not None and not isinstance(shared_workspace, bool):
        raise A2AExtensionContractError(
            "Extension contract missing/invalid 'params.shared_workspace_across_consumers'"
        )
    tenant_isolation = params.get("tenant_isolation")
    if tenant_isolation is not None:
        tenant_isolation = require_str(
            tenant_isolation,
            field="params.tenant_isolation",
        )

    return ResolvedSessionBindingExtension(
        uri=resolved_uri,
        required=required,
        provider_key=provider,
        metadata_field=metadata_field,
        behavior=behavior,
        supported_metadata=supported_metadata,
        adapter_metadata_fields=adapter_metadata_fields,
        shared_workspace_across_consumers=shared_workspace,
        tenant_isolation=tenant_isolation,
    )
