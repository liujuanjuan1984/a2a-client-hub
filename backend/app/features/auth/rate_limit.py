"""Process-local auth rate limiting helpers."""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimitDecision:
    """Result of one rate limit check."""

    allowed: bool
    retry_after_seconds: int
    current_count: int


class SlidingWindowRateLimiter:
    """Small in-process sliding window limiter for auth endpoints.

    This intentionally remains process-local. It improves burst control and
    documents the shared-store boundary without introducing new infra.
    """

    def __init__(self) -> None:
        self._entries: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check_and_record(
        self,
        *,
        scope: str,
        key: str,
        max_attempts: int,
        window_seconds: int,
    ) -> RateLimitDecision:
        now = time.monotonic()
        bucket_key = f"{scope}:{key}"
        with self._lock:
            history = self._entries.setdefault(bucket_key, deque())
            cutoff = now - float(window_seconds)
            while history and history[0] <= cutoff:
                history.popleft()

            if len(history) >= max_attempts:
                retry_after = max(1, int(history[0] + float(window_seconds) - now))
                return RateLimitDecision(
                    allowed=False,
                    retry_after_seconds=retry_after,
                    current_count=len(history),
                )

            history.append(now)
            return RateLimitDecision(
                allowed=True,
                retry_after_seconds=0,
                current_count=len(history),
            )


auth_rate_limiter = SlidingWindowRateLimiter()


__all__ = ["RateLimitDecision", "SlidingWindowRateLimiter", "auth_rate_limiter"]
