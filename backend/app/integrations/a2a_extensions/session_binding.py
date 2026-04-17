"""Shared session binding extension resolver and helpers."""

from __future__ import annotations

from typing import Any

from a2a.types import AgentCard

from app.integrations.a2a_extensions.contract_utils import as_dict, require_str
from app.integrations.a2a_extensions.errors import (
    A2AExtensionContractError,
    A2AExtensionNotSupportedError,
)
from app.integrations.a2a_extensions.shared_contract import (
    LEGACY_SHARED_SESSION_BINDING_URI,
    SHARED_SESSION_BINDING_URI,
    SHARED_SESSION_ID_FIELD,
    SUPPORTED_SESSION_BINDING_URIS,
)
from app.integrations.a2a_extensions.types import ResolvedSessionBindingExtension


def _normalize_string_list(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise A2AExtensionContractError("Extension contract missing/invalid list field")

    items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise A2AExtensionContractError(
                "Extension contract missing/invalid list item"
            )
        normalized = item.strip()
        if normalized and normalized not in items:
            items.append(normalized)
    return tuple(items)


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
        raise A2AExtensionNotSupportedError(
            "Shared session binding extension not found"
        )

    required = bool(getattr(ext, "required", False))
    params = as_dict(getattr(ext, "params", None))
    raw_provider = params.get("provider")
    if raw_provider is None:
        provider = "opencode"
    else:
        provider = require_str(raw_provider, field="params.provider").lower()

    metadata_field = require_str(
        params.get("metadata_field"),
        field="params.metadata_field",
    )
    if metadata_field != SHARED_SESSION_ID_FIELD:
        raise A2AExtensionContractError(
            f"Shared session binding metadata_field must be '{SHARED_SESSION_ID_FIELD}'"
        )

    behavior = require_str(
        params.get("behavior"),
        field="params.behavior",
    )
    supported_metadata = _normalize_string_list(params.get("supported_metadata"))
    provider_private_metadata = _normalize_string_list(
        params.get("provider_private_metadata")
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
        uri=str(getattr(ext, "uri", SHARED_SESSION_BINDING_URI)),
        required=required,
        provider=provider,
        metadata_field=metadata_field,
        behavior=behavior,
        supported_metadata=supported_metadata,
        provider_private_metadata=provider_private_metadata,
        shared_workspace_across_consumers=shared_workspace,
        tenant_isolation=tenant_isolation,
        legacy_uri_used=(
            str(getattr(ext, "uri", SHARED_SESSION_BINDING_URI))
            == LEGACY_SHARED_SESSION_BINDING_URI
        ),
    )
