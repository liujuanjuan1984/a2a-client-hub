"""In-memory operational metrics for scheduler and DB runtime health."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any


@dataclass
class _LatencyStats:
    count: int = 0
    total_ms: float = 0.0
    max_ms: float = 0.0
    last_ms: float = 0.0


class _OpsMetricsStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._db_idle_in_tx_count: int = 0
        self._db_pool_checked_out: int = 0
        self._schedule_running_task_count: int = 0
        self._schedule_finalize_latency = _LatencyStats()

    def set_db_idle_in_tx_count(self, value: int) -> None:
        with self._lock:
            self._db_idle_in_tx_count = max(int(value), 0)

    def set_db_pool_checked_out(self, value: int) -> None:
        with self._lock:
            self._db_pool_checked_out = max(int(value), 0)

    def increment_db_pool_checked_out(self) -> None:
        with self._lock:
            self._db_pool_checked_out += 1

    def decrement_db_pool_checked_out(self) -> None:
        with self._lock:
            self._db_pool_checked_out = max(self._db_pool_checked_out - 1, 0)

    def set_schedule_running_task_count(self, value: int) -> None:
        with self._lock:
            self._schedule_running_task_count = max(int(value), 0)

    def observe_schedule_run_finalize_latency(self, latency_ms: float) -> None:
        if latency_ms < 0:
            return
        with self._lock:
            stats = self._schedule_finalize_latency
            stats.count += 1
            stats.total_ms += float(latency_ms)
            stats.last_ms = float(latency_ms)
            if latency_ms > stats.max_ms:
                stats.max_ms = float(latency_ms)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            latency = self._schedule_finalize_latency
            avg_ms = latency.total_ms / latency.count if latency.count > 0 else 0.0
            return {
                "db_idle_in_tx_count": self._db_idle_in_tx_count,
                "db_pool_checked_out": self._db_pool_checked_out,
                "schedule_running_task_count": self._schedule_running_task_count,
                "schedule_run_finalize_latency": {
                    "count": latency.count,
                    "avg_ms": round(avg_ms, 3),
                    "max_ms": round(latency.max_ms, 3),
                    "last_ms": round(latency.last_ms, 3),
                },
            }


ops_metrics = _OpsMetricsStore()


__all__ = ["ops_metrics"]
