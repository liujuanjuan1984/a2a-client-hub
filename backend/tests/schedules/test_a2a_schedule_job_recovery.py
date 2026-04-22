from __future__ import annotations

from tests.schedules import a2a_schedule_job_support as support
from tests.schedules.a2a_schedule_job_support import (
    A2AScheduleExecution,
    A2AScheduleTask,
    AsyncMock,
    DBAPIError,
    Mock,
    SimpleNamespace,
    _create_agent,
    _create_schedule_task,
    _derive_recovery_timeouts,
    _refresh_ops_metrics,
    _try_hold_dispatch_leader_lock,
    a2a_schedule_service,
    create_user,
    dispatch_due_a2a_schedules,
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


async def test_recover_stale_running_task_finalizes_matching_run(
    async_db_session,
    async_session_maker,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="recover-run")
    now = utc_now()
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        next_run_at=now,
    )
    task_id = task.id
    run_id = uuid4()
    stale_started_at = now - timedelta(minutes=30)
    execution = A2AScheduleExecution(
        user_id=user.id,
        task_id=task.id,
        run_id=run_id,
        scheduled_for=stale_started_at,
        started_at=stale_started_at,
        last_heartbeat_at=stale_started_at,
        status=A2AScheduleExecution.STATUS_RUNNING,
    )
    async_db_session.add(execution)
    await async_db_session.commit()
    execution_id = execution.id

    recovered = await a2a_schedule_service.recover_stale_running_tasks(
        now=now,
        timeout_seconds=60,
    )
    assert recovered == 1
    await async_db_session.rollback()

    async with async_session_maker() as check_db:
        refreshed_task = await check_db.scalar(
            select(A2AScheduleTask).where(A2AScheduleTask.id == task_id)
        )
        refreshed_execution = await check_db.scalar(
            select(A2AScheduleExecution).where(A2AScheduleExecution.id == execution_id)
        )

    assert refreshed_task is not None
    assert refreshed_task.last_run_status == A2AScheduleTask.STATUS_FAILED
    assert refreshed_execution is not None
    assert refreshed_execution.status == A2AScheduleExecution.STATUS_FAILED
    assert refreshed_execution.finished_at is not None


async def test_recover_stale_running_task_soft_deletes_when_delete_was_requested(
    async_db_session,
    async_session_maker,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session,
        user_id=user.id,
        suffix="recover-soft-delete",
    )
    now = utc_now()
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        next_run_at=now,
    )
    task_id = task.id
    run_id = uuid4()
    stale_started_at = now - timedelta(minutes=30)
    task.delete_requested_at = now - timedelta(minutes=1)
    task.enabled = False
    task.next_run_at = None
    execution = A2AScheduleExecution(
        user_id=user.id,
        task_id=task.id,
        run_id=run_id,
        scheduled_for=stale_started_at,
        started_at=stale_started_at,
        last_heartbeat_at=stale_started_at,
        status=A2AScheduleExecution.STATUS_RUNNING,
    )
    async_db_session.add(execution)
    await async_db_session.commit()

    recovered = await a2a_schedule_service.recover_stale_running_tasks(
        now=now,
        timeout_seconds=60,
    )
    assert recovered == 1
    await async_db_session.rollback()

    async with async_session_maker() as check_db:
        refreshed_task = await check_db.scalar(
            select(A2AScheduleTask).where(A2AScheduleTask.id == task_id)
        )
        refreshed_execution = await check_db.scalar(
            select(A2AScheduleExecution).where(
                A2AScheduleExecution.task_id == task_id,
                A2AScheduleExecution.run_id == run_id,
            )
        )

    assert refreshed_task is not None
    assert refreshed_task.deleted_at is not None
    assert refreshed_task.delete_requested_at is None
    assert refreshed_execution is not None
    assert refreshed_execution.status == A2AScheduleExecution.STATUS_FAILED


async def test_recover_stale_running_task_skips_when_heartbeat_recent(
    async_db_session,
    async_session_maker,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session, user_id=user.id, suffix="recover-recent-heartbeat"
    )
    now = utc_now()
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        next_run_at=now,
    )
    task_id = task.id
    run_id = uuid4()
    stale_started_at = now - timedelta(minutes=30)
    execution = A2AScheduleExecution(
        user_id=user.id,
        task_id=task.id,
        run_id=run_id,
        scheduled_for=stale_started_at,
        started_at=stale_started_at,
        last_heartbeat_at=now - timedelta(seconds=30),
        status=A2AScheduleExecution.STATUS_RUNNING,
    )
    async_db_session.add(execution)
    await async_db_session.commit()
    execution_id = execution.id

    recovered = await a2a_schedule_service.recover_stale_running_tasks(
        now=now,
        timeout_seconds=60,
        hard_timeout_seconds=3600,
    )
    assert recovered == 0
    await async_db_session.rollback()

    async with async_session_maker() as check_db:
        refreshed_task = await check_db.scalar(
            select(A2AScheduleTask).where(A2AScheduleTask.id == task_id)
        )
        refreshed_execution = await check_db.scalar(
            select(A2AScheduleExecution).where(A2AScheduleExecution.id == execution_id)
        )

    assert refreshed_task is not None
    assert refreshed_task.last_run_status == A2AScheduleTask.STATUS_IDLE
    assert refreshed_execution is not None
    assert refreshed_execution.status == A2AScheduleExecution.STATUS_RUNNING
    assert refreshed_execution.finished_at is None


async def test_recover_stale_running_task_hard_timeout_wins_over_recent_heartbeat(
    async_db_session,
    async_session_maker,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session, user_id=user.id, suffix="recover-hard-timeout"
    )
    now = utc_now()
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        next_run_at=now,
    )
    task_id = task.id
    run_id = uuid4()
    stale_started_at = now - timedelta(minutes=30)
    execution = A2AScheduleExecution(
        user_id=user.id,
        task_id=task.id,
        run_id=run_id,
        scheduled_for=stale_started_at,
        started_at=stale_started_at,
        last_heartbeat_at=now - timedelta(seconds=10),
        status=A2AScheduleExecution.STATUS_RUNNING,
    )
    async_db_session.add(execution)
    await async_db_session.commit()
    execution_id = execution.id

    recovered = await a2a_schedule_service.recover_stale_running_tasks(
        now=now,
        timeout_seconds=60,
        hard_timeout_seconds=60,
    )
    assert recovered == 1
    await async_db_session.rollback()

    async with async_session_maker() as check_db:
        refreshed_task = await check_db.scalar(
            select(A2AScheduleTask).where(A2AScheduleTask.id == task_id)
        )
        refreshed_execution = await check_db.scalar(
            select(A2AScheduleExecution).where(A2AScheduleExecution.id == execution_id)
        )

    assert refreshed_task is not None
    assert refreshed_task.last_run_status == A2AScheduleTask.STATUS_FAILED
    assert refreshed_execution is not None
    assert refreshed_execution.status == A2AScheduleExecution.STATUS_FAILED
    assert refreshed_execution.finished_at is not None


async def test_recover_stale_running_task_requires_execution_row(
    async_db_session,
    async_session_maker,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session, user_id=user.id, suffix="recover-missing-exec"
    )
    now = utc_now()
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        next_run_at=now,
    )
    task_id = task.id

    recovered = await a2a_schedule_service.recover_stale_running_tasks(
        now=now,
        timeout_seconds=60,
    )
    assert recovered == 0
    await async_db_session.rollback()

    async with async_session_maker() as check_db:
        refreshed_task = await check_db.scalar(
            select(A2AScheduleTask).where(A2AScheduleTask.id == task_id)
        )

    assert refreshed_task is not None
    assert refreshed_task.last_run_status == A2AScheduleTask.STATUS_IDLE


async def test_recover_stale_sequential_task_reschedules_next_run(
    async_db_session,
    async_session_maker,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session,
        user_id=user.id,
        suffix="recover-sequential",
    )
    now = utc_now()
    task = await _create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        next_run_at=now,
    )
    task_id = task.id
    run_id = uuid4()
    stale_started_at = now - timedelta(minutes=30)
    task.cycle_type = A2AScheduleTask.CYCLE_SEQUENTIAL
    task.time_point = {"minutes": 60}
    task.next_run_at = None
    execution = A2AScheduleExecution(
        user_id=user.id,
        task_id=task.id,
        run_id=run_id,
        scheduled_for=stale_started_at,
        started_at=stale_started_at,
        last_heartbeat_at=stale_started_at,
        status=A2AScheduleExecution.STATUS_RUNNING,
    )
    async_db_session.add(execution)
    await async_db_session.commit()

    recovered = await a2a_schedule_service.recover_stale_running_tasks(
        now=now,
        timeout_seconds=60,
    )
    assert recovered == 1
    await async_db_session.rollback()

    async with async_session_maker() as check_db:
        refreshed_task = await check_db.scalar(
            select(A2AScheduleTask).where(A2AScheduleTask.id == task_id)
        )

    assert refreshed_task is not None
    assert refreshed_task.last_run_status == A2AScheduleTask.STATUS_FAILED
    assert refreshed_task.next_run_at is not None
    assert refreshed_task.next_run_at >= now + timedelta(minutes=59)


async def test_recover_stale_running_tasks_commits_per_recovered_task(
    async_db_session,
    async_session_maker,
    monkeypatch,
) -> None:
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    now = utc_now()
    stale_started_at = now - timedelta(minutes=30)

    for suffix in ("recover-commit-a", "recover-commit-b"):
        agent = await _create_agent(async_db_session, user_id=user.id, suffix=suffix)
        task = await _create_schedule_task(
            async_db_session,
            user_id=user.id,
            agent_id=agent.id,
            next_run_at=now,
        )
        run_id = uuid4()
        execution = A2AScheduleExecution(
            user_id=user.id,
            task_id=task.id,
            run_id=run_id,
            scheduled_for=stale_started_at,
            started_at=stale_started_at,
            last_heartbeat_at=stale_started_at,
            status=A2AScheduleExecution.STATUS_RUNNING,
        )
        async_db_session.add(execution)
    await async_db_session.commit()

    commit_call_count = 0
    timeout_apply_call_count = 0
    session_entries = 0

    async def _counting_commit(db):
        nonlocal commit_call_count
        commit_call_count += 1
        await real_commit_safely(db)

    async def _counting_set_timeouts(*_args, **_kwargs):
        nonlocal timeout_apply_call_count
        timeout_apply_call_count += 1

    class _CountingSessionContext:
        def __init__(self) -> None:
            self._context = async_session_maker()

        async def __aenter__(self):
            nonlocal session_entries
            session_entries += 1
            return await self._context.__aenter__()

        async def __aexit__(self, exc_type, exc, tb):
            return await self._context.__aexit__(exc_type, exc, tb)

    monkeypatch.setattr(
        "app.features.schedules.dispatch.commit_safely",
        _counting_commit,
    )
    monkeypatch.setattr(
        "app.features.schedules.dispatch.AsyncSessionLocal",
        lambda: _CountingSessionContext(),
    )
    monkeypatch.setattr(
        "app.features.schedules.support.set_postgres_local_timeouts",
        _counting_set_timeouts,
    )

    recovered = await a2a_schedule_service.recover_stale_running_tasks(
        now=now,
        timeout_seconds=60,
    )
    assert recovered == 2
    assert commit_call_count >= recovered
    # One short-lived session per recovered task plus one terminating loop iteration.
    assert session_entries == recovered + 1
    # Two recovered tasks plus one terminating loop iteration (no row found).
    assert timeout_apply_call_count >= recovered + 1


async def test_dispatch_due_a2a_schedules_skips_cycle_when_db_connection_refused(
    async_db_session,
    monkeypatch,
    caplog,
) -> None:
    ensure_workers_mock = AsyncMock()
    refresh_metrics_mock = AsyncMock()

    async def _raise_connection_refused(*_args, **_kwargs):
        raise ConnectionRefusedError("db unavailable")

    monkeypatch.setattr(
        "app.features.schedules.job._ensure_schedule_workers_started",
        ensure_workers_mock,
    )
    monkeypatch.setattr(
        "app.features.schedules.job._refresh_ops_metrics",
        refresh_metrics_mock,
    )
    monkeypatch.setattr(
        "app.features.schedules.job.a2a_schedule_service.recover_stale_running_tasks",
        _raise_connection_refused,
    )

    with caplog.at_level(logging.WARNING, logger="app.features.schedules.job"):
        await dispatch_due_a2a_schedules(batch_size=1)

    assert ensure_workers_mock.await_count == 0
    assert refresh_metrics_mock.await_count == 0
    assert "database connectivity issue during stale-task recovery." in caplog.text


async def test_dispatch_due_a2a_schedules_continues_when_recovery_hits_lock_contention(
    async_db_session,
    monkeypatch,
    caplog,
) -> None:
    ensure_workers_mock = AsyncMock()
    refresh_metrics_mock = AsyncMock()
    enqueue_mock = AsyncMock(return_value=0)

    class _LockNotAvailableError(Exception):
        sqlstate = "55P03"

    async def _raise_lock_contention(*_args, **_kwargs):
        raise DBAPIError(
            statement="SELECT ... FOR UPDATE SKIP LOCKED",
            params={},
            orig=_LockNotAvailableError("could not obtain lock on row"),
        )

    monkeypatch.setattr(
        "app.features.schedules.job._ensure_schedule_workers_started",
        ensure_workers_mock,
    )
    monkeypatch.setattr(
        "app.features.schedules.job._refresh_ops_metrics",
        refresh_metrics_mock,
    )
    monkeypatch.setattr(
        "app.features.schedules.job.a2a_schedule_service.recover_stale_running_tasks",
        _raise_lock_contention,
    )
    monkeypatch.setattr(
        "app.features.schedules.job.a2a_schedule_service.enqueue_due_tasks",
        enqueue_mock,
    )

    with caplog.at_level(logging.WARNING, logger="app.features.schedules.job"):
        await dispatch_due_a2a_schedules(batch_size=1)

    assert ensure_workers_mock.await_count == 1
    assert enqueue_mock.await_count == 1
    assert refresh_metrics_mock.await_count == 1
    assert (
        "Skip stale-task recovery this cycle due to lock contention; continue dispatch."
        in caplog.text
    )


async def test_dispatch_due_a2a_schedules_skips_when_leader_lock_not_acquired(
    async_db_session,
    monkeypatch,
) -> None:
    ensure_workers_mock = AsyncMock()
    refresh_metrics_mock = AsyncMock()
    recover_mock = AsyncMock(return_value=0)
    enqueue_mock = AsyncMock(return_value=0)

    class _NoLeaderLockContext:
        async def __aenter__(self):
            return False

        async def __aexit__(self, _exc_type, _exc, _tb):
            return False

    monkeypatch.setattr(
        "app.features.schedules.job._try_hold_dispatch_leader_lock",
        lambda: _NoLeaderLockContext(),
    )
    monkeypatch.setattr(
        "app.features.schedules.job._ensure_schedule_workers_started",
        ensure_workers_mock,
    )
    monkeypatch.setattr(
        "app.features.schedules.job._refresh_ops_metrics",
        refresh_metrics_mock,
    )
    monkeypatch.setattr(
        "app.features.schedules.job.a2a_schedule_service.recover_stale_running_tasks",
        recover_mock,
    )
    monkeypatch.setattr(
        "app.features.schedules.job.a2a_schedule_service.enqueue_due_tasks",
        enqueue_mock,
    )

    await dispatch_due_a2a_schedules(batch_size=1)

    assert recover_mock.await_count == 0
    assert enqueue_mock.await_count == 0
    assert ensure_workers_mock.await_count == 0
    assert refresh_metrics_mock.await_count == 0


async def test_try_hold_dispatch_leader_lock_rolls_back_open_transaction(
    monkeypatch,
) -> None:
    class _FakeConn:
        def __init__(self) -> None:
            self.scalar_calls = 0
            self.rollback_calls = 0
            self.invalidate_calls = 0
            self.dialect = SimpleNamespace(name="postgresql")

        async def scalar(self, *_args, **_kwargs):
            self.scalar_calls += 1
            return True

        async def rollback(self):
            self.rollback_calls += 1

        async def invalidate(self, *_args, **_kwargs):
            self.invalidate_calls += 1

    fake_conn = _FakeConn()

    class _FakeConnContext:
        async def __aenter__(self):
            return fake_conn

        async def __aexit__(self, _exc_type, _exc, _tb):
            return False

    monkeypatch.setattr(
        "app.features.schedules.job.async_engine",
        SimpleNamespace(connect=lambda: _FakeConnContext()),
    )

    async with _try_hold_dispatch_leader_lock() as has_leader_lock:
        assert has_leader_lock is True

    assert fake_conn.scalar_calls == 2
    assert fake_conn.rollback_calls >= 2
    assert fake_conn.invalidate_calls == 0


async def test_try_hold_dispatch_leader_lock_invalidates_connection_on_unlock_failure(
    monkeypatch,
    caplog,
) -> None:
    class _FakeConn:
        def __init__(self) -> None:
            self.scalar_calls = 0
            self.rollback_calls = 0
            self.invalidate_calls = 0
            self.dialect = SimpleNamespace(name="postgresql")

        async def scalar(self, *_args, **_kwargs):
            self.scalar_calls += 1
            if self.scalar_calls == 1:
                return True
            return False

        async def rollback(self):
            self.rollback_calls += 1

        async def invalidate(self, *_args, **_kwargs):
            self.invalidate_calls += 1

    fake_conn = _FakeConn()

    class _FakeConnContext:
        async def __aenter__(self):
            return fake_conn

        async def __aexit__(self, _exc_type, _exc, _tb):
            return False

    monkeypatch.setattr(
        "app.features.schedules.job.async_engine",
        SimpleNamespace(connect=lambda: _FakeConnContext()),
    )

    with caplog.at_level(logging.ERROR, logger="app.features.schedules.job"):
        async with _try_hold_dispatch_leader_lock() as has_leader_lock:
            assert has_leader_lock is True

    assert fake_conn.invalidate_calls == 1
    assert (
        "Failed to release A2A schedule advisory leader lock because lock was no longer held."
        in caplog.text
    )


async def test_dispatch_due_a2a_schedules_skips_cycle_when_enqueue_db_connection_refused(
    async_db_session,
    monkeypatch,
    caplog,
) -> None:
    ensure_workers_mock = AsyncMock()
    refresh_metrics_mock = AsyncMock()

    async def _recover_ok(*_args, **_kwargs):
        return 0

    async def _enqueue_raises(*_args, **_kwargs):
        raise ConnectionRefusedError("db unavailable")

    monkeypatch.setattr(
        "app.features.schedules.job._ensure_schedule_workers_started",
        ensure_workers_mock,
    )
    monkeypatch.setattr(
        "app.features.schedules.job._refresh_ops_metrics",
        refresh_metrics_mock,
    )
    monkeypatch.setattr(
        "app.features.schedules.job.a2a_schedule_service.recover_stale_running_tasks",
        _recover_ok,
    )
    monkeypatch.setattr(
        "app.features.schedules.job.a2a_schedule_service.enqueue_due_tasks",
        _enqueue_raises,
    )

    with caplog.at_level(logging.WARNING, logger="app.features.schedules.job"):
        await dispatch_due_a2a_schedules(batch_size=1)

    assert ensure_workers_mock.await_count == 1
    assert refresh_metrics_mock.await_count == 0
    assert "database connectivity issue while enqueuing due tasks." in caplog.text


async def test_dispatch_due_a2a_schedules_stops_enqueue_when_enqueue_hits_statement_timeout(
    async_db_session,
    monkeypatch,
    caplog,
) -> None:
    ensure_workers_mock = AsyncMock()
    refresh_metrics_mock = AsyncMock()

    async def _recover_ok(*_args, **_kwargs):
        return 0

    class _StatementTimeoutError(Exception):
        sqlstate = "57014"

    async def _enqueue_timeout(*_args, **_kwargs):
        raise DBAPIError(
            statement="SET LOCAL statement_timeout = '5000ms'",
            params={},
            orig=_StatementTimeoutError("canceling statement due to statement timeout"),
        )

    monkeypatch.setattr(
        "app.features.schedules.job._ensure_schedule_workers_started",
        ensure_workers_mock,
    )
    monkeypatch.setattr(
        "app.features.schedules.job._refresh_ops_metrics",
        refresh_metrics_mock,
    )
    monkeypatch.setattr(
        "app.features.schedules.job.a2a_schedule_service.recover_stale_running_tasks",
        _recover_ok,
    )
    monkeypatch.setattr(
        "app.features.schedules.job.a2a_schedule_service.enqueue_due_tasks",
        _enqueue_timeout,
    )

    with caplog.at_level(logging.WARNING, logger="app.features.schedules.job"):
        await dispatch_due_a2a_schedules(batch_size=2)

    assert ensure_workers_mock.await_count == 1
    assert refresh_metrics_mock.await_count == 1
    assert (
        "Stop enqueuing due tasks this cycle due to database statement timeout."
        in caplog.text
    )


async def test_dispatch_due_a2a_schedules_reraises_non_connectivity_errors(
    async_db_session,
    monkeypatch,
) -> None:
    async def _raise_unexpected(*_args, **_kwargs):
        raise RuntimeError("unexpected recovery failure")

    monkeypatch.setattr(
        "app.features.schedules.job.a2a_schedule_service.recover_stale_running_tasks",
        _raise_unexpected,
    )

    with pytest.raises(RuntimeError, match="unexpected recovery failure"):
        await dispatch_due_a2a_schedules(batch_size=1)


async def test_derive_recovery_timeouts_clamps_heartbeat_stale_to_invoke_timeout(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        settings,
        "a2a_schedule_task_invoke_timeout",
        45.0,
        raising=False,
    )
    monkeypatch.setattr(
        settings,
        "a2a_schedule_run_heartbeat_interval_seconds",
        20.0,
        raising=False,
    )

    heartbeat_timeout_seconds, hard_timeout_seconds = _derive_recovery_timeouts()

    assert heartbeat_timeout_seconds == 45
    assert hard_timeout_seconds == 45


async def test_dispatch_due_a2a_schedules_passes_heartbeat_and_hard_timeout(
    async_db_session,
    monkeypatch,
) -> None:
    ensure_workers_mock = AsyncMock()
    refresh_metrics_mock = AsyncMock()
    recover_mock = AsyncMock(return_value=0)
    enqueue_mock = AsyncMock(return_value=0)

    monkeypatch.setattr(
        settings,
        "a2a_schedule_task_invoke_timeout",
        200.0,
        raising=False,
    )
    monkeypatch.setattr(
        settings,
        "a2a_schedule_run_heartbeat_interval_seconds",
        20.0,
        raising=False,
    )
    monkeypatch.setattr(
        "app.features.schedules.job._ensure_schedule_workers_started",
        ensure_workers_mock,
    )
    monkeypatch.setattr(
        "app.features.schedules.job._refresh_ops_metrics",
        refresh_metrics_mock,
    )
    monkeypatch.setattr(
        "app.features.schedules.job.a2a_schedule_service.recover_stale_running_tasks",
        recover_mock,
    )
    monkeypatch.setattr(
        "app.features.schedules.job.a2a_schedule_service.enqueue_due_tasks",
        enqueue_mock,
    )

    await dispatch_due_a2a_schedules(batch_size=1)

    assert recover_mock.await_count == 1
    call_kwargs = recover_mock.await_args.kwargs
    assert call_kwargs["timeout_seconds"] == 60
    assert call_kwargs["hard_timeout_seconds"] == 200
    assert ensure_workers_mock.await_count == 1
    assert refresh_metrics_mock.await_count == 1


async def test_dispatch_due_a2a_schedules_clamps_stale_timeout_to_invoke_timeout(
    async_db_session,
    monkeypatch,
) -> None:
    ensure_workers_mock = AsyncMock()
    refresh_metrics_mock = AsyncMock()
    recover_mock = AsyncMock(return_value=0)
    enqueue_mock = AsyncMock(return_value=0)

    monkeypatch.setattr(
        settings,
        "a2a_schedule_task_invoke_timeout",
        45.0,
        raising=False,
    )
    monkeypatch.setattr(
        settings,
        "a2a_schedule_run_heartbeat_interval_seconds",
        20.0,
        raising=False,
    )
    monkeypatch.setattr(
        "app.features.schedules.job._ensure_schedule_workers_started",
        ensure_workers_mock,
    )
    monkeypatch.setattr(
        "app.features.schedules.job._refresh_ops_metrics",
        refresh_metrics_mock,
    )
    monkeypatch.setattr(
        "app.features.schedules.job.a2a_schedule_service.recover_stale_running_tasks",
        recover_mock,
    )
    monkeypatch.setattr(
        "app.features.schedules.job.a2a_schedule_service.enqueue_due_tasks",
        enqueue_mock,
    )

    await dispatch_due_a2a_schedules(batch_size=1)

    assert recover_mock.await_count == 1
    call_kwargs = recover_mock.await_args.kwargs
    assert call_kwargs["timeout_seconds"] == 45
    assert call_kwargs["hard_timeout_seconds"] == 45
    assert ensure_workers_mock.await_count == 1
    assert refresh_metrics_mock.await_count == 1


async def test_refresh_ops_metrics_skips_when_db_connection_refused(
    monkeypatch,
    caplog,
) -> None:
    class _RefusedSessionContext:
        async def __aenter__(self):
            raise ConnectionRefusedError("db unavailable")

        async def __aexit__(self, _exc_type, _exc, _tb):
            return False

    monkeypatch.setattr(
        "app.features.schedules.job.AsyncSessionLocal",
        lambda: _RefusedSessionContext(),
    )

    with caplog.at_level(logging.WARNING, logger="app.features.schedules.job"):
        await _refresh_ops_metrics()

    assert (
        "Skip schedule ops metrics refresh due to database connectivity issue."
        in caplog.text
    )


async def test_refresh_ops_metrics_refreshes_db_pool_checked_out(
    monkeypatch,
) -> None:
    class _HealthySession:
        async def scalar(self, statement):
            statement_sql = str(statement)
            if "pg_stat_activity" in statement_sql:
                return 1
            return 2

    class _HealthySessionContext:
        async def __aenter__(self):
            return _HealthySession()

        async def __aexit__(self, _exc_type, _exc, _tb):
            return False

    fake_pool = object()
    refresh_mock = Mock()

    monkeypatch.setattr(
        "app.features.schedules.job.AsyncSessionLocal",
        lambda: _HealthySessionContext(),
    )
    monkeypatch.setattr(
        "app.features.schedules.job.async_engine",
        SimpleNamespace(sync_engine=SimpleNamespace(pool=fake_pool)),
    )
    monkeypatch.setattr(
        "app.features.schedules.job.refresh_db_pool_checked_out",
        refresh_mock,
    )

    await _refresh_ops_metrics()

    assert ops_metrics.snapshot()["schedule_running_task_count"] == 2
    assert ops_metrics.snapshot()["db_idle_in_tx_count"] == 1
    refresh_mock.assert_called_once_with(fake_pool)
