"""Shared card URL validation helpers for A2A route handlers."""

from __future__ import annotations

from typing import Sequence
from urllib.parse import urlparse

from fastapi import HTTPException

from app.utils.outbound_url import (
    OutboundURLNotAllowedError,
    validate_outbound_http_url,
)


def normalize_card_url(
    value: str,
    *,
    allowed_hosts: Sequence[str] | None,
) -> str:
    """Normalize and validate a card URL for outbound proxy-safe usage."""

    trimmed = (value or "").strip()
    if not trimmed:
        raise HTTPException(status_code=400, detail="Card URL is required")

    parsed = urlparse(trimmed)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Card URL must be http(s)")

    try:
        validate_outbound_http_url(
            parsed.geturl(),
            allowed_hosts=allowed_hosts or (),
            purpose="Card URL",
        )
    except OutboundURLNotAllowedError as exc:
        if exc.code in {"missing_url", "invalid_scheme", "missing_host"}:
            raise HTTPException(
                status_code=400,
                detail="Card URL must be http(s)",
            ) from exc
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": "card_url_host_not_allowed",
                "message": "Card URL host is not allowed",
            },
        ) from exc
    return trimmed
