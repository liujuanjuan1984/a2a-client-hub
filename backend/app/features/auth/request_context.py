"""Shared request parsing helpers for auth endpoints."""

from __future__ import annotations

from typing import Iterable
from urllib.parse import urlparse

from fastapi import HTTPException, Request, status

from app.core.config import settings


def get_client_ip(request: Request) -> str | None:
    """Extract a normalized client IP address from the request."""

    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    client = getattr(request, "client", None)
    host = getattr(client, "host", None)
    return host or None


def get_user_agent(request: Request) -> str | None:
    """Extract a truncated User-Agent string."""

    value = (request.headers.get("user-agent") or "").strip()
    if not value:
        return None
    return value[:512]


def normalize_origin(origin: str) -> str:
    """Normalize origin/referer values to scheme://host[:port]."""

    parsed = urlparse(origin.strip())
    if not parsed.scheme or not parsed.netloc:
        return origin.strip().lower().rstrip("/")
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}".rstrip("/")


def get_trusted_cookie_origins() -> list[str]:
    """Resolve the trusted origin list for cookie-auth endpoints."""

    configured = settings.auth_cookie_trusted_origins or settings.backend_cors_origins
    normalized: list[str] = []
    for item in configured:
        candidate = (item or "").strip()
        if not candidate:
            continue
        normalized.append(normalize_origin(candidate))
    return normalized


def _iter_present_sources(request: Request) -> Iterable[tuple[str, str]]:
    origin = (request.headers.get("origin") or "").strip()
    if origin:
        yield ("origin", normalize_origin(origin))

    referer = (request.headers.get("referer") or "").strip()
    if referer:
        yield ("referer", normalize_origin(referer))


def enforce_trusted_cookie_origin(request: Request) -> None:
    """Reject cookie-auth requests from untrusted browser origins."""

    sources = list(_iter_present_sources(request))
    if not sources:
        if settings.auth_cookie_require_origin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Trusted Origin or Referer is required",
            )
        return

    trusted = set(get_trusted_cookie_origins())
    for header_name, candidate in sources:
        if candidate not in trusted:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Untrusted {header_name} for cookie-auth request",
            )


__all__ = [
    "enforce_trusted_cookie_origin",
    "get_client_ip",
    "get_trusted_cookie_origins",
    "get_user_agent",
    "normalize_origin",
]
