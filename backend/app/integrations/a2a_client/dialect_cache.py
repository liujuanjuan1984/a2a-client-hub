"""In-memory cache for protocol dialect probes."""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic


@dataclass(slots=True)
class _DialectEntry:
    dialect: str
    expires_at: float


class DialectCache:
    """Small TTL cache keyed by peer URL and card fingerprint."""

    def __init__(self, *, ttl_seconds: float = 3600.0) -> None:
        self._ttl_seconds = max(float(ttl_seconds), 1.0)
        self._entries: dict[tuple[str, str], _DialectEntry] = {}

    def get(self, *, agent_url: str, card_fingerprint: str) -> str | None:
        key = (agent_url, card_fingerprint)
        entry = self._entries.get(key)
        if entry is None:
            return None
        if entry.expires_at <= monotonic():
            self._entries.pop(key, None)
            return None
        return entry.dialect

    def set(self, *, agent_url: str, card_fingerprint: str, dialect: str) -> None:
        self._entries[(agent_url, card_fingerprint)] = _DialectEntry(
            dialect=dialect,
            expires_at=monotonic() + self._ttl_seconds,
        )


global_dialect_cache = DialectCache()
