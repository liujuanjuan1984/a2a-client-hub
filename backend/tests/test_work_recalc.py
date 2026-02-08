from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.models.work_recalc_job import WorkRecalcJob
from app.services import work_recalc
from app.utils.timezone_util import utc_now
from backend.tests.utils import (
    create_dimension,
    create_task,
    create_user,
    create_vision,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _stub_task_recompute(monkeypatch):
    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "app.handlers.metrics.effort_async.recompute_task_self_minutes",
        _noop,
    )


async def _create_task_fixture(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    dimension = await create_dimension(async_db_session, user)
    vision = await create_vision(async_db_session, user, dimension=dimension)
    task = await create_task(async_db_session, user, vision)
    return user, vision, task


async def _get_task_job(async_db_session, task_id):
    result = await async_db_session.execute(
        select(WorkRecalcJob).where(
            WorkRecalcJob.entity_type == WorkRecalcJob.ENTITY_TASK,
            WorkRecalcJob.entity_id == task_id,
        )
    )
    return result.scalar_one()


async def test_schedule_recalc_jobs_requeues_completed_job(async_db_session):
    user, _, task = await _create_task_fixture(async_db_session)
    await work_recalc.schedule_recalc_jobs(
        async_db_session,
        user_id=user.id,
        task_ids=[task.id],
        reason="first-run",
        run_async=True,
    )

    job = await _get_task_job(async_db_session, task.id)
    initial_created_at = job.created_at

    job.status = WorkRecalcJob.STATUS_DONE
    job.retry_count = 3
    job.last_attempt_at = utc_now()
    await async_db_session.commit()

    await work_recalc.schedule_recalc_jobs(
        async_db_session,
        user_id=user.id,
        task_ids=[task.id],
        reason="second-run",
        run_async=True,
    )

    job = await _get_task_job(async_db_session, task.id)

    assert job.status == WorkRecalcJob.STATUS_PENDING
    assert job.retry_count == 0
    assert job.last_attempt_at is None
    assert job.reason == "second-run"
    assert job.created_at == initial_created_at
    assert job.available_at is not None


async def test_schedule_during_processing_preserves_pending_state(
    async_db_session, monkeypatch
):
    user, _, task = await _create_task_fixture(async_db_session)

    await work_recalc.schedule_recalc_jobs(
        async_db_session,
        user_id=user.id,
        task_ids=[task.id],
        reason="initial",
        run_async=True,
    )

    trigger = {"called": False}

    async def fake_recompute(db, task_id):
        if not trigger["called"]:
            trigger["called"] = True
            await work_recalc.schedule_recalc_jobs(
                db,
                user_id=user.id,
                task_ids=[task_id],
                reason="during-processing",
                run_async=True,
            )
        return None

    monkeypatch.setattr(
        "app.handlers.metrics.effort_async.recompute_task_self_minutes",
        fake_recompute,
    )

    job = await _get_task_job(async_db_session, task.id)

    await work_recalc.process_jobs_for_user(user_id=user.id, db=async_db_session)

    await async_db_session.refresh(job)
    assert job.status == WorkRecalcJob.STATUS_PENDING
    assert job.reason == "during-processing"
    assert job.available_at is not None


async def test_failed_job_sets_backoff(async_db_session, monkeypatch):
    user, _, task = await _create_task_fixture(async_db_session)

    await work_recalc.schedule_recalc_jobs(
        async_db_session,
        user_id=user.id,
        task_ids=[task.id],
        reason="needs-backoff",
        run_async=True,
    )

    async def failing_recompute(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(work_recalc, "_recompute_tasks", failing_recompute)
    monkeypatch.setattr(work_recalc, "_calculate_backoff", lambda _retry: 5)

    job = await _get_task_job(async_db_session, task.id)

    await work_recalc.process_jobs_for_user(user_id=user.id, db=async_db_session)

    await async_db_session.refresh(job)

    assert job.status == WorkRecalcJob.STATUS_PENDING
    assert job.retry_count == 1
    assert job.reason == "boom"
    assert job.available_at is not None
    assert job.available_at > utc_now()


async def test_job_reaches_max_retries_and_fails(async_db_session, monkeypatch):
    user, _, task = await _create_task_fixture(async_db_session)

    await work_recalc.schedule_recalc_jobs(
        async_db_session,
        user_id=user.id,
        task_ids=[task.id],
        reason="hit-max",
        run_async=True,
    )

    async def failing_recompute(*args, **kwargs):
        raise RuntimeError("still boom")

    monkeypatch.setattr(work_recalc, "_recompute_tasks", failing_recompute)
    monkeypatch.setattr(work_recalc, "_MAX_RETRIES", 1)

    job = await _get_task_job(async_db_session, task.id)

    await work_recalc.process_jobs_for_user(user_id=user.id, db=async_db_session)

    await async_db_session.refresh(job)

    assert job.status == WorkRecalcJob.STATUS_FAILED
    assert job.retry_count == 1
    assert job.available_at is None
    assert job.reason == "still boom"
