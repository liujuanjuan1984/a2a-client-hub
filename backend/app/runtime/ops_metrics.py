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
        self._db_connection_hold = _LatencyStats()
        self._db_connection_long_hold_count: int = 0
        self._db_connection_last_long_hold_ms: float = 0.0
        self._db_connection_last_long_hold_source: str = ""
        self._db_connection_longest_hold_ms: float = 0.0
        self._db_connection_longest_hold_source: str = ""
        self._schedule_running_task_count: int = 0
        self._schedule_finalize_lock_conflicts: int = 0
        self._schedule_recovery_lock_skipped_tasks: int = 0
        self._schedule_leader_lock_contentions: int = 0
        self._schedule_leader_lock_release_failures: int = 0
        self._schedule_db_query_timeouts: int = 0
        self._ws_ticket_lock_conflicts: int = 0
        self._ws_ticket_query_timeouts: int = 0
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

    def reset_db_connection_hold_metrics(self) -> None:
        with self._lock:
            self._db_connection_hold = _LatencyStats()
            self._db_connection_long_hold_count = 0
            self._db_connection_last_long_hold_ms = 0.0
            self._db_connection_last_long_hold_source = ""
            self._db_connection_longest_hold_ms = 0.0
            self._db_connection_longest_hold_source = ""

    def observe_db_connection_hold(
        self,
        *,
        latency_ms: float,
        source: str,
        long_hold_threshold_ms: float,
    ) -> None:
        if latency_ms < 0:
            return
        normalized_source = str(source or "unknown")
        with self._lock:
            stats = self._db_connection_hold
            stats.count += 1
            stats.total_ms += float(latency_ms)
            stats.last_ms = float(latency_ms)
            if latency_ms > stats.max_ms:
                stats.max_ms = float(latency_ms)

            if latency_ms > self._db_connection_longest_hold_ms:
                self._db_connection_longest_hold_ms = float(latency_ms)
                self._db_connection_longest_hold_source = normalized_source

            if latency_ms >= float(long_hold_threshold_ms):
                self._db_connection_long_hold_count += 1
                self._db_connection_last_long_hold_ms = float(latency_ms)
                self._db_connection_last_long_hold_source = normalized_source

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

    def increment_schedule_finalize_lock_conflicts(self, value: int = 1) -> None:
        with self._lock:
            self._schedule_finalize_lock_conflicts += max(int(value), 0)

    def increment_schedule_recovery_lock_skipped_tasks(self, value: int = 1) -> None:
        with self._lock:
            self._schedule_recovery_lock_skipped_tasks += max(int(value), 0)

    def increment_schedule_leader_lock_contentions(self, value: int = 1) -> None:
        with self._lock:
            self._schedule_leader_lock_contentions += max(int(value), 0)

    def increment_schedule_leader_lock_release_failures(self, value: int = 1) -> None:
        with self._lock:
            self._schedule_leader_lock_release_failures += max(int(value), 0)

    def increment_schedule_db_query_timeouts(self, value: int = 1) -> None:
        with self._lock:
            self._schedule_db_query_timeouts += max(int(value), 0)

    def increment_ws_ticket_lock_conflicts(self, value: int = 1) -> None:
        with self._lock:
            self._ws_ticket_lock_conflicts += max(int(value), 0)

    def increment_ws_ticket_query_timeouts(self, value: int = 1) -> None:
        with self._lock:
            self._ws_ticket_query_timeouts += max(int(value), 0)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            connection_hold = self._db_connection_hold
            connection_hold_avg_ms = (
                connection_hold.total_ms / connection_hold.count
                if connection_hold.count > 0
                else 0.0
            )
            latency = self._schedule_finalize_latency
            avg_ms = latency.total_ms / latency.count if latency.count > 0 else 0.0
            return {
                "db_idle_in_tx_count": self._db_idle_in_tx_count,
                "db_pool_checked_out": self._db_pool_checked_out,
                "db_connection_hold": {
                    "count": connection_hold.count,
                    "avg_ms": round(connection_hold_avg_ms, 3),
                    "max_ms": round(connection_hold.max_ms, 3),
                    "last_ms": round(connection_hold.last_ms, 3),
                    "long_hold_count": self._db_connection_long_hold_count,
                    "last_long_hold_ms": round(
                        self._db_connection_last_long_hold_ms, 3
                    ),
                    "last_long_hold_source": self._db_connection_last_long_hold_source,
                    "longest_hold_ms": round(self._db_connection_longest_hold_ms, 3),
                    "longest_hold_source": self._db_connection_longest_hold_source,
                },
                "schedule_running_task_count": self._schedule_running_task_count,
                "schedule_finalize_lock_conflicts": self._schedule_finalize_lock_conflicts,
                "schedule_recovery_lock_skipped_tasks": self._schedule_recovery_lock_skipped_tasks,
                "schedule_leader_lock_contentions": self._schedule_leader_lock_contentions,
                "schedule_leader_lock_release_failures": self._schedule_leader_lock_release_failures,
                "schedule_db_query_timeouts": self._schedule_db_query_timeouts,
                "ws_ticket_lock_conflicts": self._ws_ticket_lock_conflicts,
                "ws_ticket_query_timeouts": self._ws_ticket_query_timeouts,
                "schedule_run_finalize_latency": {
                    "count": latency.count,
                    "avg_ms": round(avg_ms, 3),
                    "max_ms": round(latency.max_ms, 3),
                    "last_ms": round(latency.last_ms, 3),
                },
            }


ops_metrics = _OpsMetricsStore()
