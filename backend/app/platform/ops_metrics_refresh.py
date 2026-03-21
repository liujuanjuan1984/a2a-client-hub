"""Helpers for refreshing operational metrics from live runtime state."""

from __future__ import annotations

from typing import Any

from app.platform.ops_metrics import ops_metrics


def refresh_db_pool_checked_out(pool: Any) -> int | None:
    checkedout = getattr(pool, "checkedout", None)
    if not callable(checkedout):
        return None

    value = max(int(checkedout() or 0), 0)
    ops_metrics.set_db_pool_checked_out(value)
    return value


__all__ = ["refresh_db_pool_checked_out"]
