"""Canonical A2A extension contract constants and alias helpers.

The Hub keeps stable internal canonical identifiers while recognizing multiple
upstream URI aliases, including the newer ``opencode-a2a`` HTTPS specification
URIs and older ``urn:*`` transition forms.
"""

from __future__ import annotations

EXTENSION_SPECIFICATIONS_DOCUMENT_URL = (
    "https://github.com/Intelligent-Internet/opencode-a2a/blob/main/"
    "docs/extension-specifications.md"
)


def _spec_uri(fragment: str) -> str:
    return f"{EXTENSION_SPECIFICATIONS_DOCUMENT_URL}#{fragment}"


SHARED_SESSION_BINDING_URI = "urn:a2a:session-binding/v1"
OPENCODE_SHARED_SESSION_BINDING_URN = (
    "urn:opencode-a2a:extension:shared:session-binding:v1"
)
OPENCODE_SHARED_SESSION_BINDING_URI = _spec_uri("shared-session-binding-v1")
SUPPORTED_SESSION_BINDING_URIS = (
    SHARED_SESSION_BINDING_URI,
    OPENCODE_SHARED_SESSION_BINDING_URN,
    OPENCODE_SHARED_SESSION_BINDING_URI,
)

SHARED_SESSION_QUERY_URI = "urn:opencode-a2a:session-query/v1"
OPENCODE_SHARED_SESSION_MANAGEMENT_URN = (
    "urn:opencode-a2a:extension:private:session-management:v1"
)
OPENCODE_SHARED_SESSION_MANAGEMENT_URI = _spec_uri("opencode-session-management-v1")
# Deprecated upstream alias kept for older peers that still publish the
# earlier public taxonomy.
OPENCODE_SHARED_SESSION_QUERY_URI = _spec_uri("opencode-session-query-v1")
CODEX_SHARED_SESSION_QUERY_URI = "urn:codex-a2a:codex-session-query/v1"
SUPPORTED_SESSION_QUERY_URIS = (
    SHARED_SESSION_QUERY_URI,
    OPENCODE_SHARED_SESSION_MANAGEMENT_URN,
    OPENCODE_SHARED_SESSION_MANAGEMENT_URI,
    OPENCODE_SHARED_SESSION_QUERY_URI,
    CODEX_SHARED_SESSION_QUERY_URI,
)

INVOKE_METADATA_URI = "urn:a2a:invoke-metadata/v1"
OPENCODE_INVOKE_METADATA_URI = _spec_uri("shared-invoke-metadata-v1")
SUPPORTED_INVOKE_METADATA_URIS = (
    INVOKE_METADATA_URI,
    OPENCODE_INVOKE_METADATA_URI,
)

MODEL_SELECTION_URI = "urn:a2a:model-selection/v1"
OPENCODE_MODEL_SELECTION_URN = "urn:opencode-a2a:extension:shared:model-selection:v1"
OPENCODE_MODEL_SELECTION_URI = _spec_uri("shared-model-selection-v1")
SUPPORTED_MODEL_SELECTION_URIS = (
    MODEL_SELECTION_URI,
    OPENCODE_MODEL_SELECTION_URN,
    OPENCODE_MODEL_SELECTION_URI,
)

COMPATIBILITY_PROFILE_URI = "urn:a2a:compatibility-profile/v1"
OPENCODE_COMPATIBILITY_PROFILE_URN = (
    "urn:opencode-a2a:extension:private:compatibility-profile:v1"
)
OPENCODE_COMPATIBILITY_PROFILE_URI = _spec_uri("a2a-compatibility-profile-v1")
SUPPORTED_COMPATIBILITY_PROFILE_URIS = (
    COMPATIBILITY_PROFILE_URI,
    OPENCODE_COMPATIBILITY_PROFILE_URN,
    OPENCODE_COMPATIBILITY_PROFILE_URI,
)

WIRE_CONTRACT_URI = "urn:a2a:wire-contract/v1"
OPENCODE_WIRE_CONTRACT_URN = "urn:opencode-a2a:extension:private:wire-contract:v1"
OPENCODE_WIRE_CONTRACT_URI = _spec_uri("a2a-wire-contract-v1")
SUPPORTED_WIRE_CONTRACT_URIS = (
    WIRE_CONTRACT_URI,
    OPENCODE_WIRE_CONTRACT_URN,
    OPENCODE_WIRE_CONTRACT_URI,
)

PROVIDER_DISCOVERY_URI = "urn:opencode-a2a:provider-discovery/v1"
OPENCODE_PROVIDER_DISCOVERY_URN = (
    "urn:opencode-a2a:extension:private:provider-discovery:v1"
)
OPENCODE_PROVIDER_DISCOVERY_URI = _spec_uri("opencode-provider-discovery-v1")
SUPPORTED_PROVIDER_DISCOVERY_URIS = (
    PROVIDER_DISCOVERY_URI,
    OPENCODE_PROVIDER_DISCOVERY_URN,
    OPENCODE_PROVIDER_DISCOVERY_URI,
)

INTERRUPT_RECOVERY_URI = "urn:opencode-a2a:interrupt-recovery/v1"
OPENCODE_INTERRUPT_RECOVERY_URN = (
    "urn:opencode-a2a:extension:private:interrupt-recovery:v1"
)
OPENCODE_INTERRUPT_RECOVERY_URI = _spec_uri("opencode-interrupt-recovery-v1")
CODEX_INTERRUPT_RECOVERY_URI = "urn:codex-a2a:codex-interrupt-recovery/v1"
SUPPORTED_INTERRUPT_RECOVERY_URIS = (
    INTERRUPT_RECOVERY_URI,
    OPENCODE_INTERRUPT_RECOVERY_URN,
    OPENCODE_INTERRUPT_RECOVERY_URI,
    CODEX_INTERRUPT_RECOVERY_URI,
)

SHARED_INTERRUPT_CALLBACK_URI = "urn:a2a:interactive-interrupt/v1"
OPENCODE_INTERRUPT_CALLBACK_URN = (
    "urn:opencode-a2a:extension:shared:interactive-interrupt:v1"
)
OPENCODE_INTERRUPT_CALLBACK_URI = _spec_uri("shared-interactive-interrupt-v1")
SUPPORTED_INTERRUPT_CALLBACK_URIS = (
    SHARED_INTERRUPT_CALLBACK_URI,
    OPENCODE_INTERRUPT_CALLBACK_URN,
    OPENCODE_INTERRUPT_CALLBACK_URI,
)
STREAM_HINTS_URI = "urn:a2a:stream-hints/v1"
OPENCODE_STREAM_HINTS_URN = "urn:opencode-a2a:extension:shared:stream-hints:v1"
OPENCODE_STREAM_HINTS_URI = _spec_uri("shared-stream-hints-v1")
SUPPORTED_STREAM_HINTS_URIS = (
    STREAM_HINTS_URI,
    OPENCODE_STREAM_HINTS_URN,
    OPENCODE_STREAM_HINTS_URI,
)

_PREFERRED_EXTENSION_URI_BY_ALIAS = {
    alias: preferred
    for preferred, aliases in (
        (SHARED_SESSION_BINDING_URI, SUPPORTED_SESSION_BINDING_URIS),
        (SHARED_SESSION_QUERY_URI, SUPPORTED_SESSION_QUERY_URIS),
        (INVOKE_METADATA_URI, SUPPORTED_INVOKE_METADATA_URIS),
        (MODEL_SELECTION_URI, SUPPORTED_MODEL_SELECTION_URIS),
        (COMPATIBILITY_PROFILE_URI, SUPPORTED_COMPATIBILITY_PROFILE_URIS),
        (WIRE_CONTRACT_URI, SUPPORTED_WIRE_CONTRACT_URIS),
        (PROVIDER_DISCOVERY_URI, SUPPORTED_PROVIDER_DISCOVERY_URIS),
        (INTERRUPT_RECOVERY_URI, SUPPORTED_INTERRUPT_RECOVERY_URIS),
        (SHARED_INTERRUPT_CALLBACK_URI, SUPPORTED_INTERRUPT_CALLBACK_URIS),
        (STREAM_HINTS_URI, SUPPORTED_STREAM_HINTS_URIS),
    )
    for alias in aliases
}


def is_supported_extension_uri(
    value: object,
    supported_uris: tuple[str, ...],
) -> bool:
    """Return whether a declared extension URI matches any supported alias."""

    return isinstance(value, str) and value.strip() in supported_uris


def normalize_known_extension_uri(value: str | None) -> str | None:
    """Normalize a known extension URI alias to the Hub's stable identifier."""

    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return normalized
    return _PREFERRED_EXTENSION_URI_BY_ALIAS.get(normalized, normalized)


SHARED_METADATA_KEY = "shared"
SHARED_SESSION_KEY = "session"
SHARED_INVOKE_KEY = "invoke"
SHARED_STREAM_KEY = "stream"
SHARED_INTERRUPT_KEY = "interrupt"
SHARED_USAGE_KEY = "usage"

SHARED_SESSION_ID_FIELD = "metadata.shared.session.id"
SHARED_SESSION_FIELD = "metadata.shared.session"
SHARED_INVOKE_FIELD = "metadata.shared.invoke"
SHARED_STREAM_FIELD = "metadata.shared.stream"
SHARED_INTERRUPT_FIELD = "metadata.shared.interrupt"
SHARED_USAGE_FIELD = "metadata.shared.usage"
CANONICAL_PROVIDER_KEY = "provider"
CANONICAL_EXTERNAL_SESSION_ID_KEY = "externalSessionId"
SHARED_MODEL_FIELD = "metadata.shared.model"
