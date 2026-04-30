"""Compatibility-profile extension resolver and helpers."""

from __future__ import annotations

from typing import Any, Dict

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
    COMPATIBILITY_PROFILE_URI,
    SUPPORTED_COMPATIBILITY_PROFILE_URIS,
    is_supported_extension_uri,
    normalize_known_extension_uri,
)
from app.integrations.a2a_extensions.types import (
    CompatibilityRetentionEntry,
    ResolvedCompatibilityProfileExtension,
)


def _resolve_retention_entry(
    name: str,
    value: Any,
    *,
    field: str,
) -> CompatibilityRetentionEntry:
    entry = as_dict(value)
    if not entry:
        raise A2AExtensionContractError(
            f"Extension contract missing/invalid '{field}.{name}'"
        )

    extension_uri = entry.get("extension_uri")
    toggle = entry.get("toggle")
    implementation_scope = entry.get("implementation_scope")
    identity_scope = entry.get("identity_scope")
    upstream_stability = entry.get("upstream_stability")
    return CompatibilityRetentionEntry(
        surface=require_str(entry.get("surface"), field=f"{field}.{name}.surface"),
        availability=require_str(
            entry.get("availability"),
            field=f"{field}.{name}.availability",
        ),
        retention=require_str(
            entry.get("retention"),
            field=f"{field}.{name}.retention",
        ),
        extension_uri=(
            normalize_known_extension_uri(
                require_str(extension_uri, field=f"{field}.{name}.extension_uri")
            )
            if extension_uri is not None
            else None
        ),
        toggle=(
            require_str(toggle, field=f"{field}.{name}.toggle")
            if toggle is not None
            else None
        ),
        implementation_scope=(
            require_str(
                implementation_scope,
                field=f"{field}.{name}.implementation_scope",
            )
            if implementation_scope is not None
            else None
        ),
        identity_scope=(
            require_str(identity_scope, field=f"{field}.{name}.identity_scope")
            if identity_scope is not None
            else None
        ),
        upstream_stability=(
            require_str(
                upstream_stability,
                field=f"{field}.{name}.upstream_stability",
            )
            if upstream_stability is not None
            else None
        ),
    )


def _resolve_retention_map(
    value: Any,
    *,
    field: str,
) -> Dict[str, CompatibilityRetentionEntry]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise A2AExtensionContractError(f"Extension contract missing/invalid '{field}'")
    items = dict(value)

    return {
        normalize_known_extension_uri(require_str(key, field=field))
        or require_str(key, field=field): _resolve_retention_entry(
            require_str(key, field=field),
            item,
            field=field,
        )
        for key, item in items.items()
    }


def resolve_compatibility_profile(
    card: AgentCard,
) -> ResolvedCompatibilityProfileExtension:
    """Resolve the compatibility-profile extension from an Agent Card."""

    capabilities = getattr(card, "capabilities", None)
    extensions = getattr(capabilities, "extensions", None) if capabilities else None
    if not extensions:
        raise A2AExtensionNotSupportedError("Agent does not declare any extensions")

    ext = None
    for candidate in extensions:
        if is_supported_extension_uri(
            getattr(candidate, "uri", None),
            SUPPORTED_COMPATIBILITY_PROFILE_URIS,
        ):
            ext = candidate
            break
    if ext is None:
        raise A2AExtensionNotSupportedError("Compatibility profile extension not found")

    params = as_dict(getattr(ext, "params", None))
    raw_service_behaviors = params.get("service_behaviors")
    if raw_service_behaviors is None:
        service_behaviors = {}
    else:
        service_behaviors = as_dict(raw_service_behaviors)
        if not service_behaviors:
            raise A2AExtensionContractError(
                "Extension contract missing/invalid 'params.service_behaviors'"
            )
    service_behavior_methods = service_behaviors.get("methods")
    if service_behavior_methods is not None and not isinstance(
        service_behavior_methods, dict
    ):
        raise A2AExtensionContractError(
            "Extension contract missing/invalid 'params.service_behaviors.methods'"
        )

    return ResolvedCompatibilityProfileExtension(
        uri=str(getattr(ext, "uri", COMPATIBILITY_PROFILE_URI)),
        required=bool(getattr(ext, "required", False)),
        extension_retention=_resolve_retention_map(
            params.get("extension_retention"),
            field="params.extension_retention",
        ),
        method_retention=_resolve_retention_map(
            params.get("method_retention"),
            field="params.method_retention",
        ),
        service_behaviors=service_behaviors,
        consumer_guidance=normalize_string_list(
            params.get("consumer_guidance"),
            field="params.consumer_guidance",
            allow_empty=True,
        ),
    )
