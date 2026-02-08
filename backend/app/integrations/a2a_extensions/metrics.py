"""In-memory counters for tracking A2A extension calls."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from threading import Lock
from typing import Any, Dict, Optional

from app.utils.timezone_util import utc_now_iso


@dataclass
class _ExtensionCounters:
    total: int = 0
    success: int = 0
    failures: int = 0
    last_error: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "success": self.success,
            "failures": self.failures,
            "last_error": deepcopy(self.last_error),
        }


class _A2AExtensionMetricsStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._stats: Dict[str, _ExtensionCounters] = {}

    def record_call(
        self,
        key: str,
        *,
        success: bool,
        error_code: Optional[str] = None,
    ) -> None:
        with self._lock:
            counters = self._stats.setdefault(key, _ExtensionCounters())
            counters.total += 1
            if success:
                counters.success += 1
            else:
                counters.failures += 1
                counters.last_error = {
                    "code": error_code,
                    "occurred_at": utc_now_iso(),
                }

    def snapshot(self, key: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            data = {name: counters.to_dict() for name, counters in self._stats.items()}

        if key is not None:
            return data.get(
                key,
                {
                    "total": 0,
                    "success": 0,
                    "failures": 0,
                    "last_error": None,
                },
            )
        return data


a2a_extension_metrics = _A2AExtensionMetricsStore()

__all__ = ["a2a_extension_metrics"]
