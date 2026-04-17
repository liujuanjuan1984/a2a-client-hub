"""Helpers for resolving Authorization header name/scheme and header value."""

from __future__ import annotations

import base64

DEFAULT_AUTH_HEADER = "Authorization"
DEFAULT_AUTH_SCHEME = "Bearer"
DEFAULT_BASIC_AUTH_SCHEME = "Basic"


def resolve_stored_auth_fields(
    *,
    auth_header: str | None,
    auth_scheme: str | None,
    existing_auth_header: str | None = None,
    existing_auth_scheme: str | None = None,
    default_header: str = DEFAULT_AUTH_HEADER,
    default_scheme: str = DEFAULT_AUTH_SCHEME,
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
        or default_header
    )
    scheme_value = (
        (auth_scheme if auth_scheme is not None else None)
        or existing_auth_scheme
        or default_scheme
    )
    normalized_header = header_value.strip() or default_header
    normalized_scheme = scheme_value.strip() or default_scheme
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


def build_proxy_auth_headers(
    *,
    auth_type: str,
    token: str | None,
    basic_username: str | None = None,
    basic_password: str | None = None,
    auth_header: str | None = None,
    auth_scheme: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build complete header set for A2A proxy requests."""

    headers = dict(extra_headers or {})
    if auth_type == "bearer":
        token_value = (token or "").strip()
        if not token_value:
            raise ValueError("Bearer token is required")
        header_name, header_value = build_auth_header_pair(
            auth_header=auth_header,
            auth_scheme=auth_scheme,
            token=token_value,
        )
        headers[header_name] = header_value
    elif auth_type == "basic":
        username = (basic_username or "").strip()
        password = (basic_password or "").strip()
        if not username:
            raise ValueError("Basic username is required")
        if not password:
            raise ValueError("Basic password is required")
        encoded = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode(
            "ascii"
        )
        header_name, header_value = build_auth_header_pair(
            auth_header=DEFAULT_AUTH_HEADER,
            auth_scheme=DEFAULT_BASIC_AUTH_SCHEME,
            token=encoded,
        )
        headers[header_name] = header_value
    elif auth_type != "none":
        raise ValueError(f"Unsupported auth_type: {auth_type}")
    return headers
