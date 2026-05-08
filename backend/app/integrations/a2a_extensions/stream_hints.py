"""Shared stream-hints extension resolver and helpers."""

from __future__ import annotations

from a2a.types import AgentCard

from app.integrations.a2a_extensions.contract_utils import as_dict, require_str
from app.integrations.a2a_extensions.errors import (
    A2AExtensionContractError,
    A2AExtensionNotSupportedError,
)
from app.integrations.a2a_extensions.shared_contract import (
    SHARED_INTERRUPT_FIELD,
    SHARED_SESSION_FIELD,
    SHARED_STREAM_FIELD,
    SHARED_USAGE_FIELD,
    STREAM_HINTS_URI,
    SUPPORTED_STREAM_HINTS_URIS,
    infer_provider_key_from_extension_uri,
    is_supported_extension_uri,
)
from app.integrations.a2a_extensions.types import ResolvedStreamHintsExtension


def _resolve_field(value: object, *, field: str, default: str) -> str:
    if value is None:
        return default
    normalized = require_str(value, field=field)
    if normalized != default:
        raise A2AExtensionContractError(f"Stream hints '{field}' must be '{default}'")
    return normalized


def _resolve_aliasable_field(
    params: dict[str, object],
    *,
    primary: str,
    alias: str,
    default: str,
) -> str:
    value = params.get(primary)
    if value is None:
        value = params.get(alias)
    return _resolve_field(value, field=f"params.{primary}", default=default)


def resolve_stream_hints(card: AgentCard) -> ResolvedStreamHintsExtension:
    capabilities = getattr(card, "capabilities", None)
    extensions = getattr(capabilities, "extensions", None) if capabilities else None
    if not extensions:
        raise A2AExtensionNotSupportedError("Agent does not declare any extensions")

    ext = None
    for candidate in extensions:
        if is_supported_extension_uri(
            getattr(candidate, "uri", None),
            SUPPORTED_STREAM_HINTS_URIS,
        ):
            ext = candidate
            break
    if ext is None:
        raise A2AExtensionNotSupportedError("Stream hints extension not found")

    required = bool(getattr(ext, "required", False))
    params = as_dict(getattr(ext, "params", None))
    resolved_uri = str(getattr(ext, "uri", STREAM_HINTS_URI))
    raw_provider = params.get("provider")
    if raw_provider is None:
        provider = infer_provider_key_from_extension_uri(resolved_uri)
    else:
        provider = require_str(raw_provider, field="params.provider").lower()

    return ResolvedStreamHintsExtension(
        uri=resolved_uri,
        required=required,
        provider_key=provider,
        stream_field=_resolve_aliasable_field(
            params,
            primary="stream_field",
            alias="artifact_metadata_field",
            default=SHARED_STREAM_FIELD,
        ),
        usage_field=_resolve_aliasable_field(
            params,
            primary="usage_field",
            alias="usage_metadata_field",
            default=SHARED_USAGE_FIELD,
        ),
        interrupt_field=_resolve_aliasable_field(
            params,
            primary="interrupt_field",
            alias="interrupt_metadata_field",
            default=SHARED_INTERRUPT_FIELD,
        ),
        session_field=_resolve_aliasable_field(
            params,
            primary="session_field",
            alias="session_metadata_field",
            default=SHARED_SESSION_FIELD,
        ),
    )
