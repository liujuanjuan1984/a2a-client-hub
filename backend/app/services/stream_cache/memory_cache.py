"""In-memory cache for stream events to support resumability."""

import asyncio
import time
from typing import Any, Dict, List


class MemoryStreamCache:
    """A simple in-memory cache for streaming chunks to support resumability."""

    def __init__(self, ttl_seconds: int = 300) -> None:
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._ttl = ttl_seconds
        self._lock = asyncio.Lock()

    async def append_event(
        self, cache_key: str, event: Dict[str, Any], sequence: int
    ) -> None:
        """Append an event to the cache for a given key."""
        async with self._lock:
            now = time.time()
            if cache_key not in self._cache:
                self._cache[cache_key] = {
                    "events": [],
                    "last_accessed": now,
                    "completed": False,
                }

            self._cache[cache_key]["events"].append(
                {"sequence": sequence, "event": event}
            )
            self._cache[cache_key]["last_accessed"] = now

    async def get_events_after(
        self, cache_key: str, sequence: int
    ) -> List[Dict[str, Any]]:
        """Get all cached events after a specific sequence number."""
        async with self._lock:
            if cache_key not in self._cache:
                return []

            entry = self._cache[cache_key]
            entry["last_accessed"] = time.time()
            return [e["event"] for e in entry["events"] if e["sequence"] > sequence]

    async def mark_completed(self, cache_key: str) -> None:
        """Mark a stream as completed. Can be used for immediate cleanup if needed."""
        async with self._lock:
            if cache_key in self._cache:
                del self._cache[cache_key]

    async def cleanup_expired(self) -> None:
        """Remove expired entries from the cache."""
        async with self._lock:
            now = time.time()
            expired_keys = [
                key
                for key, entry in self._cache.items()
                if now - entry["last_accessed"] > self._ttl
            ]
            for key in expired_keys:
                del self._cache[key]


# Global instance for the application
global_stream_cache = MemoryStreamCache()
