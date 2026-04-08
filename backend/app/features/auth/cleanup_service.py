"""Retention cleanup helpers for auth persistence tables."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import CursorResult, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models.auth_audit_event import AuthAuditEvent
from app.db.models.auth_legacy_refresh_revocation import AuthLegacyRefreshRevocation
from app.db.models.auth_refresh_session import AuthRefreshSession
from app.db.session import AsyncSessionLocal
from app.db.transaction import commit_safely, run_with_new_session
from app.runtime.scheduler import get_scheduler
from app.utils.timezone_util import ensure_utc, utc_now

logger = get_logger(__name__)

_AUTH_CLEANUP_BATCH_SIZE = 500
_AUTH_CLEANUP_JOB_ID = "auth-cleanup-daily"


@dataclass(frozen=True)
class AuthCleanupResult:
    """Per-batch cleanup counts for auth persistence tables."""

    refresh_sessions_deleted: int
    legacy_revocations_deleted: int
    audit_events_deleted: int

    @property
    def total_deleted(self) -> int:
        return (
            self.refresh_sessions_deleted
            + self.legacy_revocations_deleted
            + self.audit_events_deleted
        )


class AuthCleanupService:
    """Delete old auth persistence rows in bounded batches."""

    async def cleanup_auth_records(
        self,
        db: AsyncSession,
        *,
        now: datetime | None = None,
        refresh_session_retention_days: int | None = None,
        audit_retention_days: int | None = None,
        batch_size: int = _AUTH_CLEANUP_BATCH_SIZE,
    ) -> AuthCleanupResult:
        limited_batch_size = max(int(batch_size), 0)
        if limited_batch_size == 0:
            return AuthCleanupResult(0, 0, 0)

        now_utc = ensure_utc(now or utc_now())
        refresh_retention_days = (
            settings.auth_refresh_session_retention_days
            if refresh_session_retention_days is None
            else int(refresh_session_retention_days)
        )
        audit_retention_window_days = (
            settings.auth_audit_event_retention_days
            if audit_retention_days is None
            else int(audit_retention_days)
        )

        refresh_deleted = await self._cleanup_refresh_sessions(
            db,
            now=now_utc,
            retention_days=refresh_retention_days,
            batch_size=limited_batch_size,
        )
        if refresh_deleted >= limited_batch_size:
            return AuthCleanupResult(refresh_deleted, 0, 0)

        legacy_deleted = await self._cleanup_legacy_refresh_revocations(
            db,
            now=now_utc,
            batch_size=limited_batch_size,
        )
        if legacy_deleted >= limited_batch_size:
            return AuthCleanupResult(refresh_deleted, legacy_deleted, 0)

        audit_deleted = await self._cleanup_audit_events(
            db,
            now=now_utc,
            retention_days=audit_retention_window_days,
            batch_size=limited_batch_size,
        )
        return AuthCleanupResult(refresh_deleted, legacy_deleted, audit_deleted)

    async def _cleanup_refresh_sessions(
        self,
        db: AsyncSession,
        *,
        now: datetime,
        retention_days: int,
        batch_size: int,
    ) -> int:
        if retention_days <= 0:
            return 0

        cutoff = now - timedelta(days=retention_days)
        stale_session_ids = (
            select(AuthRefreshSession.id)
            .where(
                or_(
                    AuthRefreshSession.expires_at < cutoff,
                    AuthRefreshSession.revoked_at < cutoff,
                )
            )
            .order_by(
                AuthRefreshSession.revoked_at.asc().nullsfirst(),
                AuthRefreshSession.expires_at.asc(),
                AuthRefreshSession.id.asc(),
            )
            .limit(batch_size)
        )
        return await self._delete_batch(
            db,
            delete(AuthRefreshSession).where(
                AuthRefreshSession.id.in_(stale_session_ids)
            ),
        )

    async def _cleanup_legacy_refresh_revocations(
        self,
        db: AsyncSession,
        *,
        now: datetime,
        batch_size: int,
    ) -> int:
        stale_revocation_ids = (
            select(AuthLegacyRefreshRevocation.id)
            .where(AuthLegacyRefreshRevocation.expires_at < now)
            .order_by(
                AuthLegacyRefreshRevocation.expires_at.asc(),
                AuthLegacyRefreshRevocation.id.asc(),
            )
            .limit(batch_size)
        )
        return await self._delete_batch(
            db,
            delete(AuthLegacyRefreshRevocation).where(
                AuthLegacyRefreshRevocation.id.in_(stale_revocation_ids)
            ),
        )

    async def _cleanup_audit_events(
        self,
        db: AsyncSession,
        *,
        now: datetime,
        retention_days: int,
        batch_size: int,
    ) -> int:
        if retention_days <= 0:
            return 0

        cutoff = now - timedelta(days=retention_days)
        stale_event_ids = (
            select(AuthAuditEvent.id)
            .where(AuthAuditEvent.occurred_at < cutoff)
            .order_by(AuthAuditEvent.occurred_at.asc(), AuthAuditEvent.id.asc())
            .limit(batch_size)
        )
        return await self._delete_batch(
            db,
            delete(AuthAuditEvent).where(AuthAuditEvent.id.in_(stale_event_ids)),
        )

    async def _delete_batch(self, db: AsyncSession, statement: Any) -> int:
        result = cast(CursorResult[Any], await db.execute(statement))
        deleted_count = int(result.rowcount or 0)
        if deleted_count <= 0:
            await db.rollback()
            return 0
        await commit_safely(db)
        return deleted_count


auth_cleanup_service = AuthCleanupService()


async def cleanup_auth_records_job() -> None:
    """Scheduled job to clean up old auth persistence rows in bounded batches."""

    total_deleted = 0
    batches = 0
    while True:
        result = await run_with_new_session(
            lambda db: auth_cleanup_service.cleanup_auth_records(
                db,
                batch_size=_AUTH_CLEANUP_BATCH_SIZE,
            ),
            session_factory=AsyncSessionLocal,
        )
        if result.total_deleted <= 0:
            break
        total_deleted += result.total_deleted
        batches += 1
        if (
            max(
                result.refresh_sessions_deleted,
                result.legacy_revocations_deleted,
                result.audit_events_deleted,
            )
            < _AUTH_CLEANUP_BATCH_SIZE
        ):
            break

    if total_deleted > 0:
        logger.info(
            "Cleaned up %d auth persistence record(s) across %d batch(es).",
            total_deleted,
            batches,
        )


def ensure_auth_cleanup_job() -> None:
    """Register the daily auth cleanup job."""

    scheduler = get_scheduler()
    if scheduler.get_job(_AUTH_CLEANUP_JOB_ID):
        return

    scheduler.add_job(
        cleanup_auth_records_job,
        trigger=CronTrigger(hour=3, minute=9),
        id=_AUTH_CLEANUP_JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    logger.info("Registered daily auth cleanup job.")


__all__ = [
    "AuthCleanupResult",
    "AuthCleanupService",
    "auth_cleanup_service",
    "cleanup_auth_records_job",
    "ensure_auth_cleanup_job",
]
