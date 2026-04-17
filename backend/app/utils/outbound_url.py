"""Helpers for validating outbound HTTP(S) targets to reduce SSRF exposure."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Iterable, Optional
from urllib.parse import urlparse


class OutboundURLNotAllowedError(ValueError):
    """Raised when an outbound URL is not permitted by the allowlist."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class AllowedHostEntry:
    host: str
    port: Optional[int]


def _normalize_host(value: str) -> str:
    return (value or "").strip().lower().rstrip(".")


def _parse_allowed_host_entry(value: str) -> AllowedHostEntry:
    trimmed = (value or "").strip()
    if not trimmed:
        return AllowedHostEntry(host="", port=None)
    if "://" in trimmed:
        parsed = urlparse(trimmed)
        return AllowedHostEntry(host=parsed.hostname or "", port=parsed.port)
    if trimmed.startswith("[") and "]" in trimmed:
        host_part, _, remainder = trimmed[1:].partition("]")
        if remainder.startswith(":") and remainder[1:].isdigit():
            return AllowedHostEntry(host=host_part, port=int(remainder[1:]))
        return AllowedHostEntry(host=host_part, port=None)
    if ":" in trimmed:
        host_part, port_part = trimmed.rsplit(":", 1)
        if port_part.isdigit():
            return AllowedHostEntry(host=host_part, port=int(port_part))
    return AllowedHostEntry(host=trimmed, port=None)


def _match_allowed_host(host: str, allowed_host: str) -> bool:
    if not allowed_host:
        return False
    if allowed_host.startswith("*."):
        suffix = allowed_host[2:]
        if not suffix:
            return False
        return host == suffix or host.endswith(f".{suffix}")
    if allowed_host.startswith("."):
        suffix = allowed_host[1:]
        if not suffix:
            return False
        return host == suffix or host.endswith(f".{suffix}")
    return host == allowed_host


def validate_outbound_http_url(
    url: str,
    *,
    allowed_hosts: Iterable[str],
    purpose: str = "outbound HTTP request",
) -> str:
    """Validate an outbound HTTP(S) URL using an allowlist and IP safety checks.

    This helper should be used for user-supplied or card-supplied targets (e.g.,
    agent card URLs, additional interfaces).
    """

    trimmed = (url or "").strip()
    if not trimmed:
        raise OutboundURLNotAllowedError(
            f"{purpose}: URL is required", code="missing_url"
        )

    parsed = urlparse(trimmed)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise OutboundURLNotAllowedError(
            f"{purpose}: URL must be http(s)", code="invalid_scheme"
        )

    host = _normalize_host(parsed.hostname or "")
    if not host:
        raise OutboundURLNotAllowedError(
            f"{purpose}: URL host is required", code="missing_host"
        )
    if host == "localhost" or host.endswith(".localhost"):
        raise OutboundURLNotAllowedError(
            f"{purpose}: URL host is not allowed", code="host_not_allowed"
        )

    # Block outbound calls to IP literals in private/reserved ranges.
    try:
        ip_value = ipaddress.ip_address(host)
    except ValueError:
        ip_value = None
    if ip_value and (
        ip_value.is_private
        or ip_value.is_loopback
        or ip_value.is_link_local
        or ip_value.is_multicast
        or ip_value.is_reserved
        or ip_value.is_unspecified
    ):
        raise OutboundURLNotAllowedError(
            f"{purpose}: URL host is not allowed", code="host_not_allowed"
        )

    allowlist = [
        _parse_allowed_host_entry(entry)
        for entry in allowed_hosts
        if (entry or "").strip()
    ]
    if not allowlist:
        raise OutboundURLNotAllowedError(
            f"{purpose}: URL host is not allowed", code="host_not_allowed"
        )

    port = parsed.port
    if port is None:
        if parsed.scheme == "https":
            port = 443
        elif parsed.scheme == "http":
            port = 80

    for entry in allowlist:
        entry_host = _normalize_host(entry.host)
        if not entry_host:
            continue
        if entry.port is not None and port is not None and entry.port != port:
            continue
        if entry.port is not None and port is None:
            continue
        if _match_allowed_host(host, entry_host):
            return trimmed

    raise OutboundURLNotAllowedError(
        f"{purpose}: URL host is not allowed", code="host_not_allowed"
    )
