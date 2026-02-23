"""In-memory cache for stream events to support resumability."""

import asyncio
import json
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, List, Tuple

_DEFAULT_TTL_SECONDS = 300
_DEFAULT_MAX_KEYS = 512
_DEFAULT_MAX_EVENTS_PER_KEY = 256
_DEFAULT_MAX_TOTAL_EVENTS = 8_000
_DEFAULT_MAX_TOTAL_BYTES = 8 * 1024 * 1024
_CACHE_EVENT_OVERHEAD_BYTES = 64


@dataclass(slots=True)
class _CachedEvent:
    sequence: int
    event: Dict[str, Any]
    estimated_bytes: int


class _CacheEntry:
    __slots__ = ("events", "estimated_bytes", "last_accessed")

    def __init__(self, now: float) -> None:
        self.events: Deque[_CachedEvent] = deque()
        self.estimated_bytes = 0
        self.last_accessed = now


def _estimate_payload_bytes(value: Any) -> int:
    try:
        return len(
            json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
    except (TypeError, ValueError):
        return 256


class MemoryStreamCache:
    """A simple in-memory cache for streaming chunks to support resumability."""

    def __init__(
        self,
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
        max_keys: int = _DEFAULT_MAX_KEYS,
        max_events_per_key: int = _DEFAULT_MAX_EVENTS_PER_KEY,
        max_total_events: int = _DEFAULT_MAX_TOTAL_EVENTS,
        max_total_bytes: int = _DEFAULT_MAX_TOTAL_BYTES,
    ) -> None:
        self._cache: Dict[str, _CacheEntry] = {}
        self._ttl = ttl_seconds
        self._max_keys = max_keys
        self._max_events_per_key = max_events_per_key
        self._max_total_events = max_total_events
        self._max_total_bytes = max_total_bytes
        self._total_events = 0
        self._total_bytes = 0
        self._lock = asyncio.Lock()

    def _estimate_event_size(self, event: Dict[str, Any]) -> int:
        return _estimate_payload_bytes(event) + _CACHE_EVENT_OVERHEAD_BYTES

    def _evict_key(self, cache_key: str) -> None:
        entry = self._cache.pop(cache_key, None)
        if entry is None:
            return
        self._total_events -= len(entry.events)
        self._total_bytes -= entry.estimated_bytes

    def _evict_entries_for_limits(self) -> None:
        while (
            len(self._cache) > self._max_keys
            or self._total_events > self._max_total_events
            or self._total_bytes > self._max_total_bytes
        ):
            if not self._cache:
                break
            oldest_key = min(
                self._cache.items(), key=lambda item: item[1].last_accessed
            )[0]
            self._evict_key(oldest_key)

    async def _pop_oldest_event(self, cache_key: str) -> None:
        entry = self._cache.get(cache_key)
        if entry is None:
            return
        try:
            oldest_event = entry.events.popleft()
        except IndexError:
            return

        entry.estimated_bytes -= oldest_event.estimated_bytes
        self._total_events -= 1
        self._total_bytes -= oldest_event.estimated_bytes
        if not entry.events:
            self._cache.pop(cache_key, None)

    def _cleanup_expired_locked(self, now: float) -> None:
        expired_keys = [
            key
            for key, entry in self._cache.items()
            if now - entry.last_accessed > self._ttl
        ]
        for key in expired_keys:
            self._evict_key(key)

    async def append_event(
        self, cache_key: str, event: Dict[str, Any], sequence: int
    ) -> None:
        """Append an event to the cache for a given key."""
        async with self._lock:
            now = time.time()
            self._cleanup_expired_locked(now)

            entry = self._cache.setdefault(cache_key, _CacheEntry(now))
            entry.last_accessed = now

            event_bytes = self._estimate_event_size(event)
            existing_event = next(
                (cached for cached in entry.events if cached.sequence == sequence),
                None,
            )
            if existing_event is not None:
                entry.events.remove(existing_event)
                entry.estimated_bytes -= existing_event.estimated_bytes
                self._total_bytes -= existing_event.estimated_bytes
                self._total_events -= 1

            entry.events.append(
                _CachedEvent(
                    sequence=sequence,
                    event=event,
                    estimated_bytes=event_bytes,
                )
            )
            entry.estimated_bytes += event_bytes
            self._total_events += 1
            self._total_bytes += event_bytes

            while len(entry.events) > self._max_events_per_key:
                await self._pop_oldest_event(cache_key)

            self._evict_entries_for_limits()

    async def get_events_with_sequence_after(
        self, cache_key: str, sequence: int
    ) -> List[Tuple[int, Dict[str, Any]]]:
        """Get cached events after a specific sequence number with sequence."""
        async with self._lock:
            now = time.time()
            self._cleanup_expired_locked(now)

            entry = self._cache.get(cache_key)
            if entry is None:
                return []

            entry.last_accessed = now
            return [
                (cached.sequence, cached.event)
                for cached in entry.events
                if cached.sequence > sequence
            ]

    async def get_events_after(
        self, cache_key: str, sequence: int
    ) -> List[Dict[str, Any]]:
        """Get cached events after a specific sequence number."""
        events = await self.get_events_with_sequence_after(cache_key, sequence)
        return [event for _, event in events]

    async def mark_completed(self, cache_key: str) -> None:
        """Mark a stream as completed. Can be used for immediate cleanup if needed."""
        async with self._lock:
            self._evict_key(cache_key)

    async def cleanup_expired(self) -> None:
        """Remove expired entries from the cache."""
        async with self._lock:
            self._cleanup_expired_locked(time.time())


# Global instance for the application
global_stream_cache = MemoryStreamCache()
