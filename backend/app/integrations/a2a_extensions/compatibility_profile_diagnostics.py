"""Compatibility-profile diagnostics for card validation and capability review."""

from __future__ import annotations

from typing import Any

from a2a.types import AgentCard

from app.integrations.a2a_extensions.compatibility_profile import (
    resolve_compatibility_profile,
)
from app.integrations.a2a_extensions.contract_utils import as_dict
from app.integrations.a2a_extensions.errors import A2AExtensionContractError
from app.integrations.a2a_extensions.shared_contract import (
    COMPATIBILITY_PROFILE_URI,
    SUPPORTED_COMPATIBILITY_PROFILE_URIS,
    is_supported_extension_uri,
)
from app.schemas.a2a_compatibility_profile import (
    A2ACompatibilityProfileDiagnostic,
    A2ACompatibilityProfileEntry,
)


def _find_declared_extension(card: AgentCard) -> tuple[Any | None, str | None]:
    capabilities = getattr(card, "capabilities", None)
    extensions = getattr(capabilities, "extensions", None) if capabilities else None
    if not extensions:
        return None, None

    hinted = None
    for candidate in extensions:
        uri = str(getattr(candidate, "uri", "") or "").strip()
        if is_supported_extension_uri(uri, SUPPORTED_COMPATIBILITY_PROFILE_URIS):
            return candidate, uri
        if hinted is None and "compatibility-profile" in uri:
            hinted = candidate, uri
    return hinted if hinted is not None else (None, None)


def diagnose_compatibility_profile(
    card: AgentCard,
) -> A2ACompatibilityProfileDiagnostic:
    ext, uri = _find_declared_extension(card)
    if ext is None:
        return A2ACompatibilityProfileDiagnostic(
            declared=False,
            status="unsupported",
            error="Compatibility profile extension not declared",
        )

    if uri != COMPATIBILITY_PROFILE_URI:
        return A2ACompatibilityProfileDiagnostic(
            declared=True,
            status="unsupported",
            uri=uri,
            error="Compatibility profile extension URI is not supported by Hub",
        )

    try:
        resolved = resolve_compatibility_profile(card)
    except A2AExtensionContractError as exc:
        params = as_dict(getattr(ext, "params", None))
        consumer_guidance = [
            item.strip()
            for item in params.get("consumer_guidance", [])
            if isinstance(item, str) and item.strip()
        ]
        return A2ACompatibilityProfileDiagnostic(
            declared=True,
            status="invalid",
            uri=uri,
            consumerGuidance=consumer_guidance,
            error=str(exc),
        )

    return A2ACompatibilityProfileDiagnostic(
        declared=True,
        status="supported",
        uri=resolved.uri,
        extensionRetention={
            name: A2ACompatibilityProfileEntry.model_validate(entry)
            for name, entry in resolved.extension_retention.items()
        },
        methodRetention={
            name: A2ACompatibilityProfileEntry.model_validate(entry)
            for name, entry in resolved.method_retention.items()
        },
        serviceBehaviors=dict(resolved.service_behaviors),
        consumerGuidance=list(resolved.consumer_guidance),
    )
