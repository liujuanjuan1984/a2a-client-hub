"""Job queue management for note auto-ingest."""

from __future__ import annotations

import asyncio
import time
from datetime import timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.note_ingest_job import NoteIngestJob
from app.db.session import AsyncSessionLocal
from app.db.transaction import commit_safely
from app.services.note_ingest_extractor import note_ingest_extractor
from app.utils.timezone_util import utc_now
from app.workflows.note_ingest_executor import note_ingest_executor

logger = get_logger(__name__)

_MAX_BATCH = 5
_MAX_RETRIES = 5
_BACKOFF_BASE_SECONDS = 30
_MAX_BACKOFF_SECONDS = 1800


class NoteIngestJobError(Exception):
    """Raised when job enqueueing fails."""


async def enqueue_note_ingest_job(
    db: AsyncSession,
    *,
    user_id: UUID,
    note_id: UUID,
) -> NoteIngestJob:
    """Create a pending note ingest job并触发异步处理。"""

    job = NoteIngestJob(
        user_id=user_id,
        note_id=note_id,
        status=NoteIngestJob.STATUS_PENDING,
        available_at=utc_now(),
    )
    db.add(job)
    await commit_safely(db)
    await db.refresh(job)

    _schedule_processing_task(user_id=user_id)

    return job


async def process_jobs_for_user(*, user_id: UUID) -> None:
    """Consume pending note ingest jobs for a user until the queue drains."""

    async with AsyncSessionLocal() as session:
        while True:
            jobs = await _fetch_pending_jobs(session, user_id)
            if not jobs:
                logger.debug("No pending note ingest jobs for user=%s", user_id)
                break

            for job in jobs:
                job_id = job.id
                job_user_id = job.user_id
                task_name = f"note-ingest-{job_user_id}"
                started_at = time.perf_counter()
                try:
                    await _process_single_job(session, job)
                except Exception as exc:  # noqa: BLE001
                    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
                    logger.exception(
                        "Note ingest job failed user=%s job=%s task_name=%s elapsed_ms=%s err=%s",
                        job_user_id,
                        job_id,
                        task_name,
                        elapsed_ms,
                        exc,
                    )
                    await session.rollback()
                    await _mark_job_failure(session, job_id, str(exc))
                else:
                    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
                    logger.info(
                        "Note ingest job succeeded user=%s job=%s task_name=%s elapsed_ms=%s",
                        job_user_id,
                        job_id,
                        task_name,
                        elapsed_ms,
                    )


async def _fetch_pending_jobs(
    session: AsyncSession, user_id: UUID
) -> list[NoteIngestJob]:
    now = utc_now()
    stmt = (
        select(NoteIngestJob)
        .where(
            NoteIngestJob.user_id == user_id,
            NoteIngestJob.status == NoteIngestJob.STATUS_PENDING,
            or_(
                NoteIngestJob.available_at.is_(None),
                NoteIngestJob.available_at <= now,
            ),
        )
        .order_by(NoteIngestJob.created_at.asc())
        .limit(_MAX_BATCH)
        .with_for_update(skip_locked=True)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def _process_single_job(session: AsyncSession, job: NoteIngestJob) -> None:
    logger.info(
        "Starting note ingest job user=%s job=%s status=%s",
        job.user_id,
        job.id,
        job.status,
    )
    job.status = NoteIngestJob.STATUS_EXTRACTING
    job.last_attempt_at = utc_now()
    job.error = None
    await commit_safely(session)

    extraction_result = await note_ingest_extractor.extract(
        session, user_id=job.user_id, note_id=job.note_id
    )
    job.extraction_payload = extraction_result.extraction.model_dump(mode="json")
    job.record_llm_usage(
        prompt_tokens=int(extraction_result.prompt_tokens or 0),
        completion_tokens=int(extraction_result.completion_tokens or 0),
        total_tokens=int(extraction_result.total_tokens or 0),
        cost_usd=extraction_result.cost_usd,
    )

    job.status = NoteIngestJob.STATUS_EXECUTING
    await commit_safely(session)

    result_payload = await note_ingest_executor.execute(
        session,
        user_id=job.user_id,
        note_id=job.note_id,
        extraction=extraction_result.extraction,
    )

    job.result_payload = result_payload
    job.status = NoteIngestJob.STATUS_SUCCEEDED
    job.retry_count = 0
    job.available_at = None
    job.error = None
    await commit_safely(session)


async def _mark_job_failure(
    session: AsyncSession, job_id: UUID, error_message: str
) -> None:
    stmt = select(NoteIngestJob).where(NoteIngestJob.id == job_id).with_for_update()
    job = (await session.execute(stmt)).scalars().first()
    if job is None:
        logger.warning(
            "Failed to mark missing note ingest job as failed job_id=%s", job_id
        )
        return

    now = utc_now()
    message = (error_message or "Unknown error")[:500]
    job.error = message
    job.last_attempt_at = now
    job.retry_count = int(job.retry_count or 0) + 1
    task_name = f"note-ingest-{job.user_id}"

    if job.retry_count >= _MAX_RETRIES:
        job.status = NoteIngestJob.STATUS_FAILED
        job.available_at = None
        logger.error(
            "Note ingest job permanently failed user=%s job=%s task_name=%s",
            job.user_id,
            job.id,
            task_name,
        )
    else:
        job.status = NoteIngestJob.STATUS_PENDING
        delay_seconds = _calculate_backoff(job.retry_count)
        job.available_at = now + timedelta(seconds=delay_seconds)
        logger.info(
            "Requeue note ingest job user=%s job=%s task_name=%s retry=%d eta=%s",
            job.user_id,
            job.id,
            task_name,
            job.retry_count,
            job.available_at,
        )

    await commit_safely(session)


def _calculate_backoff(retry_count: int) -> int:
    exponent = max(0, retry_count - 1)
    delay = _BACKOFF_BASE_SECONDS * (2**exponent)
    return min(delay, _MAX_BACKOFF_SECONDS)


def _schedule_processing_task(*, user_id: UUID) -> None:
    loop = asyncio.get_running_loop()
    task = loop.create_task(
        process_jobs_for_user(user_id=user_id),
        name=f"note-ingest-{user_id}",
    )
    task.add_done_callback(lambda t: _log_processing_failure(t, user_id))


def _log_processing_failure(task: asyncio.Task[None], user_id: UUID) -> None:
    try:
        task.result()
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Background note ingest task crashed user=%s task_name=%s err=%s",
            user_id,
            task.get_name(),
            exc,
        )


__all__ = [
    "enqueue_note_ingest_job",
    "process_jobs_for_user",
    "NoteIngestJobError",
]
