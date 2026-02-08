"""
Scheduled health check notifications for administrators.

This module registers a recurring job that executes the backend health probes
and delivers the outcome to all active admin users via the existing system
notification pipeline. It doubles as an automated heartbeat to verify that
notifications continue to work as expected.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

import anyio
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.agent_message import AgentMessage
from app.db.models.user import User
from app.db.session import AsyncSessionLocal
from app.services.health import run_health_checks
from app.services.notifications import NotificationServiceError, send_notification
from app.services.scheduler import get_scheduler
from app.utils.timezone_util import utc_now, utc_now_iso

logger = get_logger(__name__)

_HEALTH_CHECK_JOB_ID = "system-health-hourly"


async def _list_admin_user_ids(db: AsyncSession) -> list[UUID]:
    """Return active admin user IDs."""

    stmt = (
        select(User.id)
        .where(User.is_superuser.is_(True))
        .where(User.disabled_at.is_(None))
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


def _format_notification_body(overall_status: str, checks: list[dict]) -> str:
    """Build a concise, human-readable notification body."""

    timestamp = utc_now_iso()
    status_line = f"System health status: {overall_status.upper()} @ {timestamp}"

    summary_line = _build_summary_line(checks)
    detail_lines = _build_detail_lines(checks)

    parts = [status_line]
    if summary_line:
        parts.append(summary_line)
    if detail_lines:
        parts.append(detail_lines)

    return "\n\n".join(parts)


def _build_summary_line(checks: list[dict]) -> str | None:
    """Summarise the number of healthy/degraded/unhealthy checks."""

    if not checks:
        return None

    status_counts: dict[str, int] = {}
    for check in checks:
        status = str(check.get("status", "unknown")).lower()
        status_counts[status] = status_counts.get(status, 0) + 1

    total = sum(status_counts.values())
    healthy = status_counts.get("healthy", 0)
    degraded = status_counts.get("degraded", 0)
    unhealthy = status_counts.get("unhealthy", 0)

    summary = [f"{healthy}/{total} checks healthy"]
    if degraded:
        summary.append(f"{degraded} degraded")
    if unhealthy:
        summary.append(f"{unhealthy} unhealthy")

    return ", ".join(summary)


def _build_detail_lines(checks: list[dict]) -> str | None:
    """Return a detail section only when there are non-healthy checks."""

    interesting = [
        check
        for check in checks
        if str(check.get("status", "healthy")).lower() != "healthy"
    ]
    if not interesting:
        return None

    lines: list[str] = []
    for check in interesting:
        name = check.get("name", "unknown")
        status = str(check.get("status", "unknown")).upper()
        latency = check.get("latency_ms")
        detail_line = f"- {name}: {status}"
        if isinstance(latency, (int, float)):
            detail_line += f" ({latency:.1f} ms)"
        detail = check.get("detail")
        if detail:
            detail_line += f" – {detail}"
        lines.append(detail_line)

    return "\n".join(lines) if lines else None


def _determine_severity(overall_status: str) -> str:
    """Map health status to notification severity."""

    if overall_status == "unhealthy":
        return AgentMessage.SEVERITY_CRITICAL
    if overall_status == "degraded":
        return AgentMessage.SEVERITY_WARNING
    return AgentMessage.SEVERITY_INFO


async def dispatch_health_notification() -> None:
    overall_status, checks = await anyio.to_thread.run_sync(run_health_checks)
    severity = _determine_severity(overall_status)
    body = _format_notification_body(overall_status, checks)

    async with AsyncSessionLocal() as db:
        admin_ids = await _list_admin_user_ids(db)
        if not admin_ids:
            logger.info(
                "Skipping system health notification; no active admin users found."
            )
            return

        try:
            await send_notification(
                db,
                user_ids=admin_ids,
                body=body,
                title="System Health Check",
                severity=severity,
                metadata={
                    "overall_status": overall_status,
                    "checks": checks,
                },
            )
            logger.info(
                "Dispatched system health notification to %d admin users.",
                len(admin_ids),
            )
        except NotificationServiceError as exc:
            logger.error(
                "Failed to send system health notification: %s", exc, exc_info=exc
            )


def ensure_health_check_job() -> None:
    """Register the hourly system health notification job if absent."""

    scheduler = get_scheduler()
    if scheduler.get_job(_HEALTH_CHECK_JOB_ID):
        return

    scheduler.add_job(
        dispatch_health_notification,
        trigger=CronTrigger(minute=0),  # every hour on the hour
        id=_HEALTH_CHECK_JOB_ID,
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )
    logger.info("Registered hourly system health notification job.")

    # Run once shortly after startup to verify the pipeline.
    scheduler.add_job(
        dispatch_health_notification,
        trigger=DateTrigger(run_date=utc_now() + timedelta(seconds=10)),
        id=f"{_HEALTH_CHECK_JOB_ID}-initial",
        replace_existing=True,
        misfire_grace_time=60,
        coalesce=True,
        max_instances=1,
    )
    logger.info("Scheduled warm-up system health notification run.")
