"""Current A2A extension contract constants for supported upstreams.

The Hub integrates only the current ``opencode-a2a`` and ``codex-a2a`` URI
shapes. Legacy HTTPS specification aliases and deprecated transition URNs are
intentionally unsupported.
"""

from __future__ import annotations

SESSION_BINDING_URI = "urn:a2a:session-binding/v1"
OPENCODE_SESSION_BINDING_URI = "urn:opencode-a2a:extension:session-binding:v1"
CODEX_SESSION_BINDING_URI = "urn:codex-a2a:extension:session-binding:v1"
SUPPORTED_SESSION_BINDING_URIS = (
    SESSION_BINDING_URI,
    OPENCODE_SESSION_BINDING_URI,
    CODEX_SESSION_BINDING_URI,
)

OPENCODE_SESSION_MANAGEMENT_URI = "urn:opencode-a2a:extension:session-management:v1"
SESSION_QUERY_URI = OPENCODE_SESSION_MANAGEMENT_URI
CODEX_SESSION_QUERY_URI = "urn:codex-a2a:extension:session-query:v1"
SUPPORTED_SESSION_QUERY_URIS = (
    OPENCODE_SESSION_MANAGEMENT_URI,
    CODEX_SESSION_QUERY_URI,
)

INVOKE_METADATA_URI = "urn:a2a:invoke-metadata/v1"
SUPPORTED_INVOKE_METADATA_URIS = (INVOKE_METADATA_URI,)

MODEL_SELECTION_URI = "urn:opencode-a2a:extension:model-selection:v1"
SUPPORTED_MODEL_SELECTION_URIS = (MODEL_SELECTION_URI,)

COMPATIBILITY_PROFILE_URI = "urn:opencode-a2a:extension:compatibility-profile:v1"
CODEX_COMPATIBILITY_PROFILE_URI = "urn:codex-a2a:extension:compatibility-profile:v1"
SUPPORTED_COMPATIBILITY_PROFILE_URIS = (
    COMPATIBILITY_PROFILE_URI,
    CODEX_COMPATIBILITY_PROFILE_URI,
)

WIRE_CONTRACT_URI = "urn:opencode-a2a:extension:wire-contract:v1"
CODEX_WIRE_CONTRACT_URI = "urn:codex-a2a:extension:wire-contract:v1"
SUPPORTED_WIRE_CONTRACT_URIS = (
    WIRE_CONTRACT_URI,
    CODEX_WIRE_CONTRACT_URI,
)

PROVIDER_DISCOVERY_URI = "urn:opencode-a2a:extension:provider-discovery:v1"
SUPPORTED_PROVIDER_DISCOVERY_URIS = (PROVIDER_DISCOVERY_URI,)

INTERRUPT_RECOVERY_URI = "urn:opencode-a2a:extension:interrupt-recovery:v1"
CODEX_INTERRUPT_RECOVERY_URI = "urn:codex-a2a:extension:interrupt-recovery:v1"
SUPPORTED_INTERRUPT_RECOVERY_URIS = (
    INTERRUPT_RECOVERY_URI,
    CODEX_INTERRUPT_RECOVERY_URI,
)

INTERRUPT_CALLBACK_URI = "urn:a2a:interactive-interrupt/v1"
OPENCODE_INTERRUPT_CALLBACK_URI = "urn:opencode-a2a:extension:interactive-interrupt:v1"
CODEX_INTERRUPT_CALLBACK_URI = "urn:codex-a2a:extension:interactive-interrupt:v1"
SUPPORTED_INTERRUPT_CALLBACK_URIS = (
    INTERRUPT_CALLBACK_URI,
    OPENCODE_INTERRUPT_CALLBACK_URI,
    CODEX_INTERRUPT_CALLBACK_URI,
)
STREAM_HINTS_URI = "urn:a2a:stream-hints/v1"
OPENCODE_STREAM_HINTS_URI = "urn:opencode-a2a:extension:stream-hints:v1"
CODEX_STREAM_HINTS_URI = "urn:codex-a2a:extension:stream-hints:v1"
SUPPORTED_STREAM_HINTS_URIS = (
    STREAM_HINTS_URI,
    OPENCODE_STREAM_HINTS_URI,
    CODEX_STREAM_HINTS_URI,
)

CODEX_DISCOVERY_URI = "urn:codex-a2a:extension:discovery:v1"
CODEX_THREAD_LIFECYCLE_URI = "urn:codex-a2a:extension:thread-lifecycle:v1"
CODEX_TURN_CONTROL_URI = "urn:codex-a2a:extension:turn-control:v1"
CODEX_REVIEW_CONTROL_URI = "urn:codex-a2a:extension:review-control:v1"
CODEX_EXEC_CONTROL_URI = "urn:codex-a2a:extension:exec-control:v1"

_PREFERRED_EXTENSION_URI_BY_ALIAS = {
    uri: uri
    for uri in (
        *SUPPORTED_SESSION_BINDING_URIS,
        *SUPPORTED_SESSION_QUERY_URIS,
        *SUPPORTED_INVOKE_METADATA_URIS,
        *SUPPORTED_MODEL_SELECTION_URIS,
        *SUPPORTED_COMPATIBILITY_PROFILE_URIS,
        *SUPPORTED_WIRE_CONTRACT_URIS,
        *SUPPORTED_PROVIDER_DISCOVERY_URIS,
        *SUPPORTED_INTERRUPT_RECOVERY_URIS,
        *SUPPORTED_INTERRUPT_CALLBACK_URIS,
        *SUPPORTED_STREAM_HINTS_URIS,
        CODEX_DISCOVERY_URI,
        CODEX_THREAD_LIFECYCLE_URI,
        CODEX_TURN_CONTROL_URI,
        CODEX_REVIEW_CONTROL_URI,
        CODEX_EXEC_CONTROL_URI,
    )
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


def infer_provider_key_from_extension_uri(value: str | None) -> str:
    """Infer the provider namespace from a supported extension URI."""

    normalized = normalize_known_extension_uri(value)
    if isinstance(normalized, str) and normalized.startswith("urn:codex-a2a:"):
        return "codex"
    return "opencode"


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
