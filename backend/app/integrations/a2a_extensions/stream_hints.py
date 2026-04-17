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
    raw_provider = params.get("provider")
    if raw_provider is None:
        provider = "opencode"
    else:
        provider = require_str(raw_provider, field="params.provider").lower()

    return ResolvedStreamHintsExtension(
        uri=str(getattr(ext, "uri", STREAM_HINTS_URI)),
        required=required,
        provider=provider,
        stream_field=_resolve_field(
            params.get("stream_field"),
            field="params.stream_field",
            default=SHARED_STREAM_FIELD,
        ),
        usage_field=_resolve_field(
            params.get("usage_field"),
            field="params.usage_field",
            default=SHARED_USAGE_FIELD,
        ),
        interrupt_field=_resolve_field(
            params.get("interrupt_field"),
            field="params.interrupt_field",
            default=SHARED_INTERRUPT_FIELD,
        ),
        session_field=_resolve_field(
            params.get("session_field"),
            field="params.session_field",
            default=SHARED_SESSION_FIELD,
        ),
    )
