"""Shared model-selection extension resolver and helpers."""

from __future__ import annotations

from typing import Any

from a2a.types import AgentCard

from app.integrations.a2a_extensions.contract_utils import as_dict, require_str
from app.integrations.a2a_extensions.errors import (
    A2AExtensionContractError,
    A2AExtensionNotSupportedError,
)
from app.integrations.a2a_extensions.shared_contract import (
    MODEL_SELECTION_URI,
    SHARED_MODEL_FIELD,
    SUPPORTED_MODEL_SELECTION_URIS,
    is_supported_extension_uri,
)
from app.integrations.a2a_extensions.types import ResolvedModelSelectionExtension


def _normalize_string_list(value: Any, *, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise A2AExtensionContractError(f"Extension contract missing/invalid '{field}'")

    items: list[str] = []
    for item in value:
        normalized = require_str(item, field=field)
        if normalized and normalized not in items:
            items.append(normalized)
    return tuple(items)


def resolve_model_selection(card: AgentCard) -> ResolvedModelSelectionExtension:
    capabilities = getattr(card, "capabilities", None)
    extensions = getattr(capabilities, "extensions", None) if capabilities else None
    if not extensions:
        raise A2AExtensionNotSupportedError("Agent does not declare any extensions")

    ext = None
    for candidate in extensions:
        if is_supported_extension_uri(
            getattr(candidate, "uri", None),
            SUPPORTED_MODEL_SELECTION_URIS,
        ):
            ext = candidate
            break
    if ext is None:
        raise A2AExtensionNotSupportedError("Model selection extension not found")

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
    if metadata_field != SHARED_MODEL_FIELD:
        raise A2AExtensionContractError(
            f"Shared model selection metadata_field must be '{SHARED_MODEL_FIELD}'"
        )

    behavior = require_str(
        params.get("behavior"),
        field="params.behavior",
    )
    applies_to_methods = _normalize_string_list(
        params.get("applies_to_methods"),
        field="params.applies_to_methods",
    )
    if not applies_to_methods:
        raise A2AExtensionContractError(
            "Extension contract missing/invalid 'params.applies_to_methods'"
        )

    return ResolvedModelSelectionExtension(
        uri=str(getattr(ext, "uri", MODEL_SELECTION_URI)),
        required=required,
        provider=provider,
        metadata_field=metadata_field,
        behavior=behavior,
        applies_to_methods=applies_to_methods,
        supported_metadata=_normalize_string_list(
            params.get("supported_metadata"),
            field="params.supported_metadata",
        ),
        provider_private_metadata=_normalize_string_list(
            params.get("provider_private_metadata"),
            field="params.provider_private_metadata",
        ),
    )


__all__ = ["resolve_model_selection"]
