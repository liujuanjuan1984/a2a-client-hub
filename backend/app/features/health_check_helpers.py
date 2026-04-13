"""Shared helpers for agent health check result assembly."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def build_health_snapshot_update(
    *,
    health_status: str,
    healthy_status: str,
    checked_at: datetime,
    consecutive_failures: int,
    previous_last_successful_at: datetime | None,
    error_message: str | None,
    reason_code: str | None,
) -> dict[str, Any]:
    return {
        "health_status": health_status,
        "consecutive_health_check_failures": consecutive_failures,
        "last_health_check_at": checked_at,
        "last_successful_health_check_at": (
            checked_at
            if health_status == healthy_status
            else previous_last_successful_at
        ),
        "last_health_check_error": error_message,
        "last_health_check_reason_code": reason_code,
    }


def build_health_check_item_fields(
    *,
    health_status: str,
    checked_at: datetime,
    skipped_cooldown: bool,
    error: str | None,
    reason_code: str | None,
) -> dict[str, Any]:
    return {
        "health_status": health_status,
        "checked_at": checked_at,
        "skipped_cooldown": skipped_cooldown,
        "error": error,
        "reason_code": reason_code,
    }
