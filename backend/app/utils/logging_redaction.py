"""Helpers for redacting sensitive values before logging."""

from __future__ import annotations

import hashlib
from typing import Mapping
from urllib.parse import SplitResult, urlsplit, urlunsplit

_SENSITIVE_KEYWORDS = (
    "authorization",
    "cookie",
    "token",
    "ticket",
    "secret",
    "websocket-protocol",
    "api-key",
    "apikey",
    "password",
    "access_token",
    "refresh_token",
    "api_key",
    "x-api-key",
)

_SAFE_HEADER_ALLOWLIST = {
    "accept",
    "accept-encoding",
    "accept-language",
    "content-length",
    "content-type",
    "host",
    "origin",
    "traceparent",
    "tracestate",
    "user-agent",
    "x-request-id",
}


def redact_sensitive_value(value: str | None) -> str | None:
    """Redact a sensitive value by keeping the first 6 characters and adding a hash.

    If the value is shorter than 12 characters, we redact it completely to avoid
    leaking too much information.
    """
    if value is None:
        return None

    s_value = str(value)
    if not s_value:
        return s_value

    if len(s_value) < 12:
        return "<redacted>"

    prefix = s_value[:6]
    # Use a stable hash of the value to help with debugging across logs
    val_hash = hashlib.sha256(s_value.encode()).hexdigest()[:8]
    return f"{prefix}...{val_hash}"


def redact_headers_for_logging(headers: Mapping[str, str]) -> dict[str, str]:
    """Redact headers for logs using a secure-by-default policy.

    Only a small allowlist of operationally useful headers keeps its original
    value. All other headers are hidden by default so user-defined custom
    authentication headers do not leak into logs. Known sensitive headers keep a
    stable prefix+hash representation to preserve limited debugging value.
    """
    redacted: dict[str, str] = {}
    for key, value in headers.items():
        lower_key = key.lower()
        if lower_key in _SAFE_HEADER_ALLOWLIST:
            redacted[key] = value
        elif any(keyword in lower_key for keyword in _SENSITIVE_KEYWORDS):
            redacted[key] = redact_sensitive_value(value) or "<redacted>"
        else:
            redacted[key] = "<redacted>"
    return redacted


def redact_query_params_for_logging(query_params: Mapping[str, str]) -> dict[str, str]:
    """Redact sensitive query parameters."""
    redacted: dict[str, str] = {}
    for key, value in query_params.items():
        lower_key = key.lower()
        if any(keyword in lower_key for keyword in _SENSITIVE_KEYWORDS):
            redacted[key] = redact_sensitive_value(value) or "<redacted>"
        else:
            redacted[key] = value
    return redacted


def redact_url_for_logging(url: str | None) -> str | None:
    """Redact URL values for logs.

    We intentionally drop:
    - userinfo (username/password)
    - path
    - query
    - fragment

    Returning only `scheme://host[:port]` reduces the risk of leaking tokens that
    are sometimes embedded in query strings.
    """

    if url is None:
        return None

    trimmed = (url or "").strip()
    if not trimmed:
        return trimmed

    parts = urlsplit(trimmed)
    if not parts.scheme or not parts.netloc:
        return trimmed

    hostname = parts.hostname or ""
    if not hostname:
        return trimmed

    netloc = hostname
    if parts.port:
        netloc = f"{hostname}:{parts.port}"

    redacted = SplitResult(parts.scheme, netloc, "", "", "")
    return urlunsplit(redacted)
