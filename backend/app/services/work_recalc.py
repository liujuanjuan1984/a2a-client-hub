"""Utilities for scheduling and processing work recalculation jobs."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Iterable, Sequence
from uuid import UUID, uuid4

from sqlalchemy import select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.task import Task
from app.db.models.work_recalc_job import WorkRecalcJob
from app.db.session import AsyncSessionLocal
from app.db.transaction import commit_safely
from app.handlers import visions as vision_handlers
from app.handlers.metrics import effort_async as effort_handlers_async
from app.utils.timezone_util import utc_now

logger = logging.getLogger(__name__)

_MAX_BATCH = 20
_MAX_RETRIES = 5
_BACKOFF_BASE_SECONDS = 60
_MAX_BACKOFF_SECONDS = 3600


@dataclass(frozen=True)
class PendingJob:
    """Lightweight representation of a work_recalc job row."""

    id: UUID
    entity_type: str
    entity_id: UUID
    retry_count: int
    reason: str | None


def _schedule_job_processing(user_id: UUID) -> None:
    async def _runner() -> None:
        await process_jobs_for_user(user_id=user_id)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(_runner())
    else:
        loop.create_task(_runner())


def _calculate_backoff(retry_count: int) -> int:
    """Return retry delay (seconds) using exponential backoff with an upper bound."""
    exponent = max(0, retry_count - 1)
    delay = _BACKOFF_BASE_SECONDS * (2**exponent)
    return min(delay, _MAX_BACKOFF_SECONDS)


def _summarize_ids(values: Iterable[UUID], *, limit: int = 5) -> str:
    """Return a human-readable representation of UUID collections for logging."""
    items = [str(value) for value in values if value is not None]
    if not items:
        return "[]"
    if len(items) > limit:
        head = ", ".join(items[:limit])
        remainder = len(items) - limit
        return f"[{head}, … +{remainder}]"
    return f"[{', '.join(items)}]"


def _deduplicate_ids(values: Sequence[UUID] | None) -> list[UUID]:
    """Return a unique, None-free list preserving no particular ordering."""

    if not values:
        return []
    return list({value for value in values if value is not None})


def _build_job_rows(
    *,
    user_id: UUID,
    task_ids: Sequence[UUID],
    vision_ids: Sequence[UUID],
    reason: str | None,
) -> list[dict[str, Any]]:
    now = utc_now()
    rows: list[dict[str, Any]] = []
    for task_id in task_ids:
        rows.append(
            dict(
                id=uuid4(),
                user_id=user_id,
                entity_type=WorkRecalcJob.ENTITY_TASK,
                entity_id=task_id,
                status=WorkRecalcJob.STATUS_PENDING,
                priority=0,
                retry_count=0,
                reason=reason,
                last_attempt_at=None,
                created_at=now,
                available_at=now,
            )
        )
    for vision_id in vision_ids:
        rows.append(
            dict(
                id=uuid4(),
                user_id=user_id,
                entity_type=WorkRecalcJob.ENTITY_VISION,
                entity_id=vision_id,
                status=WorkRecalcJob.STATUS_PENDING,
                priority=0,
                retry_count=0,
                reason=reason,
                last_attempt_at=None,
                created_at=now,
                available_at=now,
            )
        )
    return rows


async def schedule_recalc_jobs(
    db: AsyncSession | None,
    *,
    user_id: UUID,
    task_ids: Sequence[UUID] | None = None,
    vision_ids: Sequence[UUID] | None = None,
    reason: str | None = None,
    run_async: bool = False,
) -> None:
    """Enqueue recalculation jobs, defaulting to an isolated AsyncSession."""

    if db is not None:
        await _schedule_recalc_jobs(
            db,
            user_id=user_id,
            task_ids=task_ids,
            vision_ids=vision_ids,
            reason=reason,
            run_async=run_async,
        )
        if not run_async:
            await process_jobs_for_user(user_id=user_id, db=db)
        return

    async with AsyncSessionLocal() as session:
        await _schedule_recalc_jobs(
            session,
            user_id=user_id,
            task_ids=task_ids,
            vision_ids=vision_ids,
            reason=reason,
            run_async=run_async,
        )
        if run_async:
            _schedule_job_processing(user_id)
            return

        await process_jobs_for_user(user_id=user_id, db=session)


async def _schedule_recalc_jobs(
    db: AsyncSession,
    *,
    user_id: UUID,
    task_ids: Sequence[UUID] | None,
    vision_ids: Sequence[UUID] | None,
    reason: str | None,
    run_async: bool,
) -> None:
    normalized_task_ids = _deduplicate_ids(task_ids)
    normalized_vision_ids = _deduplicate_ids(vision_ids)
    if not normalized_task_ids and not normalized_vision_ids:
        logger.debug(
            "Skip scheduling work recalc jobs because no entities were provided for user_id=%s",
            user_id,
        )
        return

    rows = _build_job_rows(
        user_id=user_id,
        task_ids=normalized_task_ids,
        vision_ids=normalized_vision_ids,
        reason=reason,
    )
    logger.info(
        "Scheduling %d work recalculation jobs user_id=%s task_ids=%s vision_ids=%s reason=%s trigger=%s",
        len(rows),
        user_id,
        _summarize_ids(normalized_task_ids),
        _summarize_ids(normalized_vision_ids),
        reason or "unspecified",
        "background" if run_async else "inline",
    )

    updates: dict[tuple[str, UUID], dict[str, Any]] = {}
    for row in rows:
        insert_stmt = insert(WorkRecalcJob).values(**row)
        update_values = {
            "status": WorkRecalcJob.STATUS_PENDING,
            "priority": insert_stmt.excluded.priority,
            "reason": insert_stmt.excluded.reason,
            "retry_count": 0,
            "user_id": insert_stmt.excluded.user_id,
            "last_attempt_at": None,
            "available_at": insert_stmt.excluded.available_at,
        }
        stmt = insert_stmt.on_conflict_do_update(
            index_elements=["entity_type", "entity_id"],
            set_=update_values,
        )
        await db.execute(stmt)
        updates[(row["entity_type"], row["entity_id"])] = {
            "status": WorkRecalcJob.STATUS_PENDING,
            "priority": row["priority"],
            "reason": row["reason"],
            "retry_count": 0,
            "last_attempt_at": None,
            "available_at": row["available_at"],
        }
    await commit_safely(db)
    await _refresh_upserted_jobs(db, updates)

    # 调度函数负责决定是否立即处理或交由后台任务执行。


async def process_jobs_for_user(
    *, user_id: UUID, db: AsyncSession | None = None
) -> None:
    """Consume pending recalculation jobs for a given user in batches."""

    if db is not None:
        await _process_jobs_for_user(db, user_id=user_id)
        return

    async with AsyncSessionLocal() as session:
        await _process_jobs_for_user(session, user_id=user_id)


async def _process_jobs_for_user(db: AsyncSession, *, user_id: UUID) -> None:
    requeued_job_ids: set[UUID] = set()
    try:
        while True:
            jobs = await _fetch_pending_jobs(
                db, user_id=user_id, excluded_job_ids=requeued_job_ids
            )
            if not jobs:
                logger.debug(
                    "No pending work recalculation jobs found for user_id=%s",
                    user_id,
                )
                break

            logger.info(
                "Processing work recalculation batch user_id=%s batch_size=%d job_ids=%s",
                user_id,
                len(jobs),
                _summarize_ids((job.id for job in jobs), limit=8),
            )

            job_ids = [job.id for job in jobs]
            await _mark_jobs_processing(db, job_ids)

            processed_jobs: set[UUID] = set()
            failed_jobs: dict[UUID, str] = {}
            task_ids: set[UUID] = {
                job.entity_id
                for job in jobs
                if job.entity_type == WorkRecalcJob.ENTITY_TASK
            }
            vision_ids: set[UUID] = {
                job.entity_id
                for job in jobs
                if job.entity_type == WorkRecalcJob.ENTITY_VISION
            }

            if task_ids:
                try:
                    vision_ids.update(
                        await _recompute_tasks(db, user_id=user_id, task_ids=task_ids)
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Task recompute failed for user %s", user_id)
                    for job in jobs:
                        if job.entity_type == WorkRecalcJob.ENTITY_TASK:
                            failed_jobs[job.id] = str(exc)

            if vision_ids:
                try:
                    await _recompute_visions(db, user_id=user_id, vision_ids=vision_ids)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Vision recompute failed for user %s", user_id)
                    for job in jobs:
                        if job.entity_type == WorkRecalcJob.ENTITY_VISION:
                            failed_jobs[job.id] = str(exc)

            for job in jobs:
                if job.id in failed_jobs:
                    await _mark_failed(db, job, failed_jobs[job.id], user_id=user_id)
                    continue

                current_status = await _fetch_job_status(db, job.id)
                if current_status is None:
                    logger.debug(
                        "Skip marking work recalculation job as done because row disappeared user_id=%s job_id=%s",
                        user_id,
                        job.id,
                    )
                    continue
                if current_status != WorkRecalcJob.STATUS_PROCESSING:
                    logger.debug(
                        "Skip marking work recalculation job as done because status changed user_id=%s job_id=%s status=%s",
                        user_id,
                        job.id,
                        current_status,
                    )
                    requeued_job_ids.add(job.id)
                    continue

                processed_jobs.add(job.id)

            if processed_jobs:
                await _mark_jobs_done(db, processed_jobs, user_id=user_id)
    finally:
        logger.debug(
            "Finished processing work recalculation queue for user_id=%s", user_id
        )


async def _fetch_pending_jobs(
    db: AsyncSession,
    *,
    user_id: UUID,
    excluded_job_ids: set[UUID],
) -> list[PendingJob]:
    now = utc_now()
    stmt = (
        select(
            WorkRecalcJob.id,
            WorkRecalcJob.entity_type,
            WorkRecalcJob.entity_id,
            WorkRecalcJob.retry_count,
            WorkRecalcJob.reason,
        )
        .where(
            WorkRecalcJob.user_id == user_id,
            WorkRecalcJob.status == WorkRecalcJob.STATUS_PENDING,
            WorkRecalcJob.available_at <= now,
        )
        .order_by(
            WorkRecalcJob.priority.desc(),
            WorkRecalcJob.created_at.asc(),
        )
        .limit(_MAX_BATCH)
        .with_for_update(skip_locked=True)
    )
    if excluded_job_ids:
        stmt = stmt.where(~WorkRecalcJob.id.in_(tuple(excluded_job_ids)))
    result = await db.execute(stmt)
    return [
        PendingJob(
            id=row.id,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            retry_count=row.retry_count or 0,
            reason=row.reason,
        )
        for row in result.all()
    ]


async def _mark_jobs_processing(db: AsyncSession, job_ids: Sequence[UUID]) -> None:
    if not job_ids:
        return

    stmt = (
        update(WorkRecalcJob)
        .where(WorkRecalcJob.id.in_(list(job_ids)))
        .values(
            status=WorkRecalcJob.STATUS_PROCESSING,
            last_attempt_at=utc_now(),
        )
    )
    await db.execute(stmt)
    await commit_safely(db)


async def _fetch_job_status(db: AsyncSession, job_id: UUID) -> str | None:
    stmt = select(WorkRecalcJob.status).where(WorkRecalcJob.id == job_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _mark_jobs_done(
    db: AsyncSession, job_ids: set[UUID], *, user_id: UUID
) -> None:
    stmt = (
        update(WorkRecalcJob)
        .where(
            WorkRecalcJob.id.in_(list(job_ids)),
            WorkRecalcJob.status == WorkRecalcJob.STATUS_PROCESSING,
        )
        .values(status=WorkRecalcJob.STATUS_DONE)
    )
    result = await db.execute(stmt)
    if result.rowcount:
        await commit_safely(db)
        logger.info(
            "Marked work recalculation jobs as done user_id=%s job_ids=%s",
            user_id,
            _summarize_ids(job_ids, limit=8),
        )


async def _mark_failed(
    db: AsyncSession, job: PendingJob, details: str, *, user_id: UUID
) -> None:
    retry_count = job.retry_count + 1
    attempt_time = utc_now()
    logger.warning(
        "Work recalculation job failed user_id=%s job_id=%s entity_type=%s entity_id=%s retry_count=%d details=%s",
        user_id,
        job.id,
        job.entity_type,
        job.entity_id,
        retry_count,
        details,
    )

    if retry_count >= _MAX_RETRIES:
        stmt = (
            update(WorkRecalcJob)
            .where(WorkRecalcJob.id == job.id)
            .values(
                status=WorkRecalcJob.STATUS_FAILED,
                retry_count=retry_count,
                reason=details or job.reason,
                last_attempt_at=attempt_time,
                available_at=None,
            )
        )
        await db.execute(stmt)
        await commit_safely(db)
        logger.error(
            "Work recalculation job permanently failed user_id=%s job_id=%s retries=%d details=%s",
            user_id,
            job.id,
            retry_count,
            details,
        )
        return

    delay_seconds = _calculate_backoff(retry_count)
    next_attempt_at = attempt_time + timedelta(seconds=delay_seconds)
    stmt = (
        update(WorkRecalcJob)
        .where(WorkRecalcJob.id == job.id)
        .values(
            status=WorkRecalcJob.STATUS_PENDING,
            retry_count=retry_count,
            reason=details or job.reason,
            last_attempt_at=attempt_time,
            available_at=next_attempt_at,
        )
    )
    await db.execute(stmt)
    await commit_safely(db)


async def _refresh_upserted_jobs(
    db: AsyncSession, updates: dict[tuple[str, UUID], dict[str, Any]]
) -> None:
    """Ensure ORM identity map reflects the latest upserted job state."""

    if not updates:
        return

    stmt = select(WorkRecalcJob).where(
        tuple_(WorkRecalcJob.entity_type, WorkRecalcJob.entity_id).in_(
            list(updates.keys())
        )
    )
    result = await db.execute(stmt)
    for job in result.scalars():
        payload = updates.get((job.entity_type, job.entity_id))
        if not payload:
            continue
        job.status = payload["status"]
        job.priority = payload["priority"]
        job.reason = payload["reason"]
        job.retry_count = payload["retry_count"]
        job.last_attempt_at = payload["last_attempt_at"]
        job.available_at = payload["available_at"]


async def _recompute_tasks(
    db: AsyncSession, *, user_id: UUID, task_ids: Iterable[UUID]
) -> set[UUID]:
    affected_visions: set[UUID] = set()
    unique_ids = {tid for tid in task_ids if tid is not None}
    if not unique_ids:
        return affected_visions

    for task_id in unique_ids:
        stmt = (
            select(Task)
            .where(
                Task.user_id == user_id,
                Task.id == task_id,
                Task.deleted_at.is_(None),
            )
            .limit(1)
        )
        task = (await db.execute(stmt)).scalar_one_or_none()
        if not task:
            continue
        try:
            await effort_handlers_async.recompute_task_self_minutes(db, task.id)
            await effort_handlers_async.recompute_totals_upwards(db, task.id)
            await commit_safely(db)
        except SQLAlchemyError:
            await db.rollback()
            raise

        if task.vision_id:
            affected_visions.add(task.vision_id)

    return affected_visions


async def _recompute_visions(
    db: AsyncSession, *, user_id: UUID, vision_ids: Iterable[UUID]
) -> None:
    unique_ids = {vid for vid in vision_ids if vid is not None}
    for vision_id in unique_ids:
        try:
            await vision_handlers.sync_vision_experience(
                db, user_id=user_id, vision_id=vision_id
            )
        except SQLAlchemyError:
            await db.rollback()
            raise
