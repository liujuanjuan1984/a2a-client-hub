from __future__ import annotations

from tests.schedules import a2a_schedule_job_support as support
from tests.schedules.a2a_schedule_job_support import (
    A2AScheduleConflictError,
    A2AScheduleExecution,
    A2AScheduleNotFoundError,
    A2AScheduleServiceBusyError,
    A2AScheduleTask,
    ClaimedA2AScheduleTask,
    DBAPIError,
    User,
    _create_agent,
    _create_schedule_task,
    _mark_task_claimed,
    _schedule_run_heartbeat_loop,
    a2a_schedule_service,
    asyncio,
    create_user,
    logging,
    ops_metrics,
    pytest,
    real_commit_safely,
    select,
    settings,
    timedelta,
    utc_now,
    uuid4,
)

pytestmark = support.pytestmark


async def test_claim_next_pending_execution_obeys_agent_concurrency_limit(
    async_db_session,
    monkeypatch,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent_a = await _create_agent(async_db_session, user_id=user.id, suffix="a")
    agent_b = await _create_agent(async_db_session, user_id=user.id, suffix="b")

    now = utc_now()
    task_a1 = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent_a.id,
        next_run_at=now,
    )
    await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent_a.id,
        next_run_at=now,
    )
    existing_run_id = uuid4()
    async_db_session.add(
        A2AScheduleExecution(
            user_id=user.id,
            task_id=task_a1.id,
            run_id=existing_run_id,
            scheduled_for=now - timedelta(minutes=1),
            started_at=now - timedelta(minutes=1),
            last_heartbeat_at=now - timedelta(seconds=30),
            status=A2AScheduleExecution.STATUS_RUNNING,
        )
    )
    task_b = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent_b.id,
        next_run_at=now,
    )
    await async_db_session.commit()

    monkeypatch.setattr(
        settings,
        "a2a_schedule_agent_concurrency_limit",
        1,
        raising=False,
    )

    await a2a_schedule_service.enqueue_due_tasks(async_db_session, now=now)
    claim = await a2a_schedule_service.claim_next_pending_execution(
        async_db_session, now=now
    )
    assert claim is not None
    assert claim.task_id == task_b.id


async def test_claim_next_pending_execution_obeys_global_concurrency_limit(
    async_db_session,
    monkeypatch,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent_a = await _create_agent(async_db_session, user_id=user.id, suffix="global-a")
    agent_b = await _create_agent(async_db_session, user_id=user.id, suffix="global-b")
    now = utc_now()
    task_a = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent_a.id,
        next_run_at=now,
    )
    await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent_b.id,
        next_run_at=now,
    )
    running_run_id = uuid4()
    async_db_session.add(
        A2AScheduleExecution(
            user_id=user.id,
            task_id=task_a.id,
            run_id=running_run_id,
            scheduled_for=now - timedelta(minutes=1),
            started_at=now - timedelta(minutes=1),
            last_heartbeat_at=now - timedelta(seconds=20),
            status=A2AScheduleExecution.STATUS_RUNNING,
        )
    )
    await async_db_session.commit()

    monkeypatch.setattr(
        settings,
        "a2a_schedule_global_concurrency_limit",
        1,
        raising=False,
    )

    await a2a_schedule_service.enqueue_due_tasks(async_db_session, now=now)
    claim = await a2a_schedule_service.claim_next_pending_execution(
        async_db_session, now=now
    )
    assert claim is None


async def test_claim_next_pending_execution_creates_running_execution_immediately(
    async_db_session,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="claim-exec")
    now = utc_now()
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        next_run_at=now,
    )

    await a2a_schedule_service.enqueue_due_tasks(async_db_session, now=now)
    claim = await a2a_schedule_service.claim_next_pending_execution(
        async_db_session, now=now
    )
    assert claim is not None
    assert claim.task_id == task.id

    execution = await async_db_session.scalar(
        select(A2AScheduleExecution).where(
            A2AScheduleExecution.task_id == task.id,
            A2AScheduleExecution.run_id == claim.run_id,
        )
    )
    assert execution is not None
    assert execution.status == A2AScheduleExecution.STATUS_RUNNING
    assert execution.finished_at is None
    assert execution.scheduled_for == claim.scheduled_for


async def test_claim_next_pending_execution_sequential_holds_next_run_until_finalize(
    async_db_session,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="sequential")
    now = utc_now()
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        next_run_at=now,
    )
    task.cycle_type = A2AScheduleTask.CYCLE_SEQUENTIAL
    task.time_point = {"minutes": 15}
    await async_db_session.commit()

    await a2a_schedule_service.enqueue_due_tasks(async_db_session, now=now)
    claim = await a2a_schedule_service.claim_next_pending_execution(
        async_db_session, now=now
    )
    assert claim is not None
    assert claim.task_id == task.id
    await async_db_session.refresh(task)
    assert task.last_run_status == A2AScheduleTask.STATUS_IDLE
    assert task.next_run_at is None


async def test_delete_running_task_marks_deferred_delete_and_hides_from_user_queries(
    async_db_session,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session, user_id=user.id, suffix="deferred-delete"
    )
    now = utc_now()
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        next_run_at=now,
    )
    run_id = await _mark_task_claimed(async_db_session, task=task)

    await a2a_schedule_service.delete_task(
        async_db_session,
        user_id=user.id,
        task_id=task.id,
    )
    await async_db_session.refresh(task)

    assert task.deleted_at is None
    assert task.delete_requested_at is not None
    assert task.enabled is False
    assert task.next_run_at is None
    execution = await async_db_session.scalar(
        select(A2AScheduleExecution).where(
            A2AScheduleExecution.task_id == task.id,
            A2AScheduleExecution.run_id == run_id,
        )
    )
    assert execution is not None
    assert execution.status == A2AScheduleExecution.STATUS_RUNNING

    with pytest.raises(A2AScheduleNotFoundError):
        await a2a_schedule_service.get_task(
            async_db_session,
            user_id=user.id,
            task_id=task.id,
        )


async def test_finalize_task_run_soft_deletes_when_delete_was_requested(
    async_db_session,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session, user_id=user.id, suffix="finalize-delete"
    )
    now = utc_now()
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        next_run_at=now,
    )
    run_id = await _mark_task_claimed(async_db_session, task=task)
    task.delete_requested_at = utc_now()
    task.enabled = False
    task.next_run_at = None
    await async_db_session.commit()

    finalized = await a2a_schedule_service.finalize_task_run(
        async_db_session,
        task_id=task.id,
        user_id=user.id,
        run_id=run_id,
        final_status=A2AScheduleTask.STATUS_SUCCESS,
        finished_at=utc_now(),
    )
    assert finalized is True
    await real_commit_safely(async_db_session)
    await async_db_session.refresh(task)

    assert task.deleted_at is not None
    assert task.enabled is False
    assert task.delete_requested_at is None
    assert task.next_run_at is None


@pytest.mark.parametrize(
    ("cycle_type", "time_point"),
    [
        (
            A2AScheduleTask.CYCLE_DAILY,
            {"time": "09:00"},
        ),
        (
            A2AScheduleTask.CYCLE_WEEKLY,
            {"time": "09:00", "weekday": 1},
        ),
        (
            A2AScheduleTask.CYCLE_MONTHLY,
            {"time": "09:00", "day": 1},
        ),
        (
            A2AScheduleTask.CYCLE_INTERVAL,
            {"minutes": 60},
        ),
    ],
    ids=["daily", "weekly", "monthly", "interval"],
)
async def test_finalize_task_run_keeps_precomputed_next_run_for_non_sequential_task(
    async_db_session,
    async_session_maker,
    cycle_type: str,
    time_point: dict[str, object],
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session,
        user_id=user.id,
        suffix="finalize-preserve-next-run",
    )
    now = utc_now()
    current_run_at = now
    projected_next_run_at = now + timedelta(days=1)
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        next_run_at=current_run_at,
        cycle_type=cycle_type,
        time_point=time_point,
    )
    run_id = await _mark_task_claimed(async_db_session, task=task)
    task.next_run_at = projected_next_run_at
    await async_db_session.commit()

    finalized = await a2a_schedule_service.finalize_task_run(
        async_db_session,
        task_id=task.id,
        user_id=user.id,
        run_id=run_id,
        final_status=A2AScheduleTask.STATUS_SUCCESS,
        finished_at=now + timedelta(minutes=1),
    )
    assert finalized is True
    await real_commit_safely(async_db_session)

    async with async_session_maker() as check_db:
        refreshed_task = await check_db.scalar(
            select(A2AScheduleTask).where(A2AScheduleTask.id == task.id)
        )

    assert refreshed_task is not None
    assert refreshed_task.last_run_status == A2AScheduleTask.STATUS_SUCCESS
    assert refreshed_task.next_run_at == projected_next_run_at


async def test_finalize_task_run_clears_next_run_when_failure_threshold_disables_task(
    async_db_session,
    async_session_maker,
    monkeypatch,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session,
        user_id=user.id,
        suffix="finalize-disable-next-run",
    )
    now = utc_now()
    projected_next_run_at = now + timedelta(days=1)
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        next_run_at=now,
    )
    run_id = await _mark_task_claimed(async_db_session, task=task)
    task.next_run_at = projected_next_run_at
    await async_db_session.commit()

    monkeypatch.setattr(
        settings,
        "a2a_schedule_task_failure_threshold",
        1,
        raising=False,
    )

    finalized = await a2a_schedule_service.finalize_task_run(
        async_db_session,
        task_id=task.id,
        user_id=user.id,
        run_id=run_id,
        final_status=A2AScheduleTask.STATUS_FAILED,
        finished_at=now + timedelta(minutes=1),
        error_message="run failed",
        error_code="task_failed",
    )
    assert finalized is True
    await real_commit_safely(async_db_session)

    async with async_session_maker() as check_db:
        refreshed_task = await check_db.scalar(
            select(A2AScheduleTask).where(A2AScheduleTask.id == task.id)
        )

    assert refreshed_task is not None
    assert refreshed_task.last_run_status == A2AScheduleTask.STATUS_FAILED
    assert refreshed_task.enabled is False
    assert refreshed_task.next_run_at is None


async def test_delete_task_returns_conflict_when_row_locked(
    async_db_session,
    async_session_maker,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="delete-lock")
    now = utc_now()
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        next_run_at=now,
    )

    async with async_session_maker() as lock_db:
        await lock_db.scalar(
            select(A2AScheduleTask)
            .where(A2AScheduleTask.id == task.id)
            .with_for_update(nowait=True)
            .limit(1)
        )
        async with async_session_maker() as actor_db:
            with pytest.raises(A2AScheduleConflictError):
                await a2a_schedule_service.delete_task(
                    actor_db,
                    user_id=user.id,
                    task_id=task.id,
                )
        await lock_db.rollback()


async def test_set_enabled_is_not_blocked_by_user_row_lock(
    async_db_session,
    async_session_maker,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session, user_id=user.id, suffix="set-enabled-user-lock"
    )
    now = utc_now()
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        enabled=False,
        next_run_at=now,
    )

    async with async_session_maker() as lock_db:
        await lock_db.scalar(
            select(User.id)
            .where(User.id == user.id)
            .with_for_update(nowait=True)
            .limit(1)
        )
        async with async_session_maker() as actor_db:
            updated = await a2a_schedule_service.set_enabled(
                actor_db,
                user_id=user.id,
                task_id=task.id,
                enabled=True,
                is_superuser=False,
                timezone_str="UTC",
            )
            assert updated.enabled is True
        await lock_db.rollback()


async def test_create_task_surfaces_service_busy_when_user_fk_check_is_blocked(
    async_db_session,
    async_session_maker,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session, user_id=user.id, suffix="create-user-lock"
    )

    async with async_session_maker() as lock_db:
        await lock_db.scalar(
            select(User.id)
            .where(User.id == user.id)
            .with_for_update(nowait=True)
            .limit(1)
        )
        async with async_session_maker() as actor_db:
            with pytest.raises(A2AScheduleServiceBusyError):
                await a2a_schedule_service.create_task(
                    actor_db,
                    user_id=user.id,
                    is_superuser=False,
                    timezone_str="UTC",
                    name="quota-lock-create",
                    agent_id=agent.id,
                    prompt="hello",
                    cycle_type=A2AScheduleTask.CYCLE_DAILY,
                    time_point={"time": "09:00"},
                    enabled=True,
                )
        await lock_db.rollback()


async def test_schedule_run_heartbeat_loop_classifies_lock_contention(
    monkeypatch,
    caplog,
) -> None:
    claim = ClaimedA2AScheduleTask(
        task_id=uuid4(),
        user_id=uuid4(),
        agent_id=uuid4(),
        conversation_id=None,
        name="heartbeat-lock",
        prompt="hello",
        cycle_type=A2AScheduleTask.CYCLE_DAILY,
        time_point={"time": "09:00"},
        scheduled_for=utc_now(),
        run_id=uuid4(),
    )
    stop_event = asyncio.Event()

    class _LockNotAvailableError(Exception):
        sqlstate = "55P03"

    async def _raise_lock_contention(*_args, **_kwargs):
        stop_event.set()
        raise DBAPIError(
            statement="UPDATE ... FOR UPDATE",
            params={},
            orig=_LockNotAvailableError("could not obtain lock on row"),
        )

    monkeypatch.setattr(
        "app.features.schedules.job._touch_schedule_run_heartbeat",
        _raise_lock_contention,
    )
    monkeypatch.setattr(
        settings,
        "a2a_schedule_run_heartbeat_interval_seconds",
        0.1,
        raising=False,
    )

    with caplog.at_level(logging.WARNING, logger="app.features.schedules.job"):
        await _schedule_run_heartbeat_loop(claim=claim, stop_event=stop_event)

    assert "lock contention" in caplog.text
    assert "Schedule heartbeat update failed" not in caplog.text


async def test_schedule_run_heartbeat_loop_classifies_statement_timeout(
    monkeypatch,
    caplog,
) -> None:
    before = ops_metrics.snapshot().get("schedule_db_query_timeouts", 0)
    claim = ClaimedA2AScheduleTask(
        task_id=uuid4(),
        user_id=uuid4(),
        agent_id=uuid4(),
        conversation_id=None,
        name="heartbeat-timeout",
        prompt="hello",
        cycle_type=A2AScheduleTask.CYCLE_DAILY,
        time_point={"time": "09:00"},
        scheduled_for=utc_now(),
        run_id=uuid4(),
    )
    stop_event = asyncio.Event()

    class _StatementTimeoutError(Exception):
        sqlstate = "57014"

    async def _raise_statement_timeout(*_args, **_kwargs):
        stop_event.set()
        raise DBAPIError(
            statement="UPDATE ...",
            params={},
            orig=_StatementTimeoutError("canceling statement due to statement timeout"),
        )

    monkeypatch.setattr(
        "app.features.schedules.job._touch_schedule_run_heartbeat",
        _raise_statement_timeout,
    )
    monkeypatch.setattr(
        settings,
        "a2a_schedule_run_heartbeat_interval_seconds",
        0.1,
        raising=False,
    )

    with caplog.at_level(logging.WARNING, logger="app.features.schedules.job"):
        await _schedule_run_heartbeat_loop(claim=claim, stop_event=stop_event)

    after = ops_metrics.snapshot().get("schedule_db_query_timeouts", 0)
    assert "database statement timeout" in caplog.text
    assert "Schedule heartbeat update failed" not in caplog.text
    assert int(after) >= int(before) + 1
