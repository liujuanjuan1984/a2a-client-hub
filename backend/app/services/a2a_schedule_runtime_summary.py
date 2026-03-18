"""Helpers for scheduled task runtime summaries and shared timeout policy."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from app.core.config import settings
from app.db.models.a2a_schedule_execution import A2AScheduleExecution
from app.utils.timezone_util import ensure_utc, utc_now


def derive_schedule_recovery_timeouts() -> tuple[int, int]:
    """Derive heartbeat stale and hard timeout from invoke timeout."""

    invoke_timeout_seconds = max(
        int(math.ceil(float(settings.a2a_schedule_task_invoke_timeout))),
        1,
    )
    heartbeat_interval_seconds = max(
        float(settings.a2a_schedule_run_heartbeat_interval_seconds),
        0.1,
    )
    heartbeat_stale_seconds = max(
        int(math.ceil(heartbeat_interval_seconds * 3)),
        30,
    )
    heartbeat_stale_seconds = min(heartbeat_stale_seconds, invoke_timeout_seconds)
    return heartbeat_stale_seconds, invoke_timeout_seconds


def build_schedule_status_summary(
    *,
    running_execution: A2AScheduleExecution | None,
    latest_execution: A2AScheduleExecution | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a lightweight read-model summary for jobs list and detail views."""

    now_utc = ensure_utc(now or utc_now())
    heartbeat_stale_seconds, _hard_timeout_seconds = derive_schedule_recovery_timeouts()

    if running_execution is not None:
        started_at = ensure_utc(
            running_execution.started_at or running_execution.scheduled_for
        )
        heartbeat_at = ensure_utc(
            running_execution.last_heartbeat_at
            or running_execution.started_at
            or running_execution.scheduled_for
        )
        running_duration_seconds = max(
            int((now_utc - started_at).total_seconds()),
            0,
        )
        heartbeat_age_seconds = max(
            int((now_utc - heartbeat_at).total_seconds()),
            0,
        )
        return {
            "state": "running",
            "manual_intervention_recommended": (
                heartbeat_age_seconds >= heartbeat_stale_seconds
            ),
            "running_started_at": started_at,
            "running_duration_seconds": running_duration_seconds,
            "last_heartbeat_at": heartbeat_at,
            "heartbeat_age_seconds": heartbeat_age_seconds,
            "heartbeat_stale_after_seconds": heartbeat_stale_seconds,
            "recent_failure_message": None,
            "recent_failure_error_code": None,
            "last_finished_at": None,
        }

    recent_failure_message = None
    recent_failure_error_code = None
    last_finished_at = None
    if latest_execution is not None:
        last_finished_at = (
            latest_execution.finished_at
            or latest_execution.started_at
            or latest_execution.scheduled_for
        )
        if last_finished_at is not None:
            last_finished_at = ensure_utc(last_finished_at)
        if latest_execution.status == A2AScheduleExecution.STATUS_FAILED:
            recent_failure_message = (
                latest_execution.error_message or ""
            ).strip() or None
            recent_failure_error_code = (
                latest_execution.error_code or ""
            ).strip() or None

    has_recent_failure = (
        recent_failure_message is not None or recent_failure_error_code is not None
    )

    return {
        "state": ("recent_failed" if has_recent_failure else "idle"),
        "manual_intervention_recommended": False,
        "running_started_at": None,
        "running_duration_seconds": None,
        "last_heartbeat_at": None,
        "heartbeat_age_seconds": None,
        "heartbeat_stale_after_seconds": heartbeat_stale_seconds,
        "recent_failure_message": recent_failure_message,
        "recent_failure_error_code": recent_failure_error_code,
        "last_finished_at": last_finished_at,
    }


__all__ = [
    "build_schedule_status_summary",
    "derive_schedule_recovery_timeouts",
]
