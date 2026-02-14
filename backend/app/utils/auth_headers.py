"""Helpers for resolving Authorization header name/scheme and header value."""

from __future__ import annotations

DEFAULT_AUTH_HEADER = "Authorization"
DEFAULT_AUTH_SCHEME = "Bearer"


def resolve_stored_auth_fields(
    *,
    auth_header: str | None,
    auth_scheme: str | None,
    existing_auth_header: str | None = None,
    existing_auth_scheme: str | None = None,
) -> tuple[str, str]:
    """Resolve stored auth fields for persistence/update flows.

    Semantics intentionally match existing service behavior:
    - `None` means "not provided", so it falls back to existing/default.
    - empty string behaves as false-y and also falls back to existing/default.
    - non-empty whitespace-only string is considered provided and then normalized.
    """

    header_value = (
        (auth_header if auth_header is not None else None)
        or existing_auth_header
        or DEFAULT_AUTH_HEADER
    )
    scheme_value = (
        (auth_scheme if auth_scheme is not None else None)
        or existing_auth_scheme
        or DEFAULT_AUTH_SCHEME
    )
    normalized_header = header_value.strip() or DEFAULT_AUTH_HEADER
    normalized_scheme = scheme_value.strip() or DEFAULT_AUTH_SCHEME
    return normalized_header, normalized_scheme


def build_auth_header_pair(
    *,
    auth_header: str | None,
    auth_scheme: str | None,
    token: str,
) -> tuple[str, str]:
    """Build HTTP header key/value for bearer-like auth use.

    Semantics intentionally match existing runtime/proxy behavior:
    - empty/None header falls back to Authorization.
    - scheme defaults to Bearer before strip.
    - whitespace-only scheme yields token-only header value.
    """

    header_name = (auth_header or DEFAULT_AUTH_HEADER).strip() or DEFAULT_AUTH_HEADER
    scheme = (auth_scheme or DEFAULT_AUTH_SCHEME).strip()
    header_value = f"{scheme} {token}" if scheme else token
    return header_name, header_value


__all__ = [
    "build_auth_header_pair",
    "resolve_stored_auth_fields",
]
