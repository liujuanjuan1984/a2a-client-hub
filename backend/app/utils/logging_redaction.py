"""Helpers for redacting sensitive values before logging."""

from __future__ import annotations

from urllib.parse import SplitResult, urlsplit, urlunsplit


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


__all__ = ["redact_url_for_logging"]

