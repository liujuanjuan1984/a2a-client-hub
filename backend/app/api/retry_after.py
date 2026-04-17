"""Shared retry-after policy for transient DB pressure responses."""

from __future__ import annotations

DB_BUSY_RETRY_AFTER_SECONDS = 3


def db_busy_retry_after_headers() -> dict[str, str]:
    return {"Retry-After": str(DB_BUSY_RETRY_AFTER_SECONDS)}


def append_retry_after_hint(reason: str) -> str:
    return f"{reason} Retry in {DB_BUSY_RETRY_AFTER_SECONDS} seconds."
