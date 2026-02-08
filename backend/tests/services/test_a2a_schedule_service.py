from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db.models.a2a_agent import A2AAgent
from app.db.models.a2a_schedule_execution import A2AScheduleExecution
from app.db.models.a2a_schedule_task import A2AScheduleTask
from app.services.a2a_schedule_service import (
    A2AScheduleService,
    A2AScheduleValidationError,
    a2a_schedule_service,
)
from app.utils.timezone_util import utc_now
from backend.tests.utils import create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _create_agent(async_db_session, *, user_id, suffix: str = "x") -> A2AAgent:
    agent = A2AAgent(
        user_id=user_id,
        name=f"Agent {suffix}",
        card_url=f"https://example.com/{suffix}",
        auth_type="none",
        enabled=True,
    )
    async_db_session.add(agent)
    await async_db_session.commit()
    await async_db_session.refresh(agent)
    return agent


async def test_compute_next_run_monthly_clamps_day() -> None:
    service = A2AScheduleService()
    result = service.compute_next_run_at(
        cycle_type="monthly",
        time_point={"day": 31, "time": "08:30"},
        timezone_str="UTC",
        after_utc=datetime(2026, 2, 1, 7, 0, tzinfo=timezone.utc),
    )
    assert result == datetime(2026, 2, 28, 8, 30, tzinfo=timezone.utc)


async def test_compute_next_run_interval_rounds_up_and_respects_guard() -> None:
    service = A2AScheduleService()
    result = service.compute_next_run_at(
        cycle_type="interval",
        time_point={"minutes": 6},
        timezone_str="UTC",
        after_utc=datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc),
        not_before_utc=datetime(2026, 2, 1, 10, 7, tzinfo=timezone.utc),
    )
    # 6 minutes -> 10 minutes, and next run must be strictly after guard (10:07).
    assert result == datetime(2026, 2, 1, 10, 10, tzinfo=timezone.utc)


async def test_compute_next_run_weekly_uses_iso_weekday() -> None:
    service = A2AScheduleService()
    # ISO weekday: 1=Monday ... 7=Sunday
    result = service.compute_next_run_at(
        cycle_type="weekly",
        time_point={"weekday": 1, "time": "08:30"},
        timezone_str="UTC",
        after_utc=datetime(2026, 2, 2, 7, 0, tzinfo=timezone.utc),  # Monday
    )
    assert result == datetime(2026, 2, 2, 8, 30, tzinfo=timezone.utc)


async def test_compute_next_run_weekly_rolls_to_next_week_when_time_passed() -> None:
    service = A2AScheduleService()
    # After Monday 09:00, schedule Monday 08:30 -> next Monday.
    result = service.compute_next_run_at(
        cycle_type="weekly",
        time_point={"weekday": 1, "time": "08:30"},
        timezone_str="UTC",
        after_utc=datetime(2026, 2, 2, 9, 0, tzinfo=timezone.utc),  # Monday
    )
    assert result == datetime(2026, 2, 9, 8, 30, tzinfo=timezone.utc)


@pytest.mark.parametrize("weekday", [0, 8])
async def test_compute_next_run_weekly_rejects_out_of_range_weekday(weekday) -> None:
    service = A2AScheduleService()
    with pytest.raises(A2AScheduleValidationError):
        service.compute_next_run_at(
            cycle_type="weekly",
            time_point={"weekday": weekday, "time": "08:30"},
            timezone_str="UTC",
            after_utc=datetime(2026, 2, 2, 7, 0, tzinfo=timezone.utc),
        )


@pytest.mark.parametrize(
    "raw_minutes, expected_minutes",
    [
        (-7, 5),
        (0, 5),
        (1, 5),
        (5, 5),
        (6, 10),
        (9, 10),
        (10, 10),
        (1439, 1440),
        (1440, 1440),
        (2000, 1440),
    ],
)
async def test_create_task_interval_normalizes_minutes(
    async_db_session,
    raw_minutes,
    expected_minutes,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="interval")

    task = await a2a_schedule_service.create_task(
        async_db_session,
        user_id=user.id,
        name="Interval",
        agent_id=agent.id,
        prompt="ping",
        cycle_type="interval",
        time_point={"minutes": raw_minutes},
        enabled=False,
    )
    assert task.time_point == {"minutes": expected_minutes}


async def test_create_task_rejects_unowned_agent(async_db_session):
    owner = await create_user(async_db_session, skip_onboarding_defaults=True)
    other_user = await create_user(async_db_session, skip_onboarding_defaults=True)
    other_agent = await _create_agent(
        async_db_session,
        user_id=other_user.id,
        suffix="other",
    )

    with pytest.raises(A2AScheduleValidationError):
        await a2a_schedule_service.create_task(
            async_db_session,
            user_id=owner.id,
            name="Daily check",
            agent_id=other_agent.id,
            prompt="ping",
            cycle_type="daily",
            time_point={"time": "09:00"},
            enabled=True,
        )


async def test_create_task_rejects_disabled_agent(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="disabled")
    agent.enabled = False
    await async_db_session.commit()

    with pytest.raises(A2AScheduleValidationError):
        await a2a_schedule_service.create_task(
            async_db_session,
            user_id=user.id,
            name="Daily check",
            agent_id=agent.id,
            prompt="ping",
            cycle_type="daily",
            time_point={"time": "09:00"},
            enabled=True,
        )


async def test_claim_due_task_advances_next_run(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="claim")

    task = await a2a_schedule_service.create_task(
        async_db_session,
        user_id=user.id,
        name="Daily run",
        agent_id=agent.id,
        prompt="hello",
        cycle_type="daily",
        time_point={"time": "00:00"},
        enabled=True,
    )

    now = utc_now()
    task.next_run_at = now - timedelta(minutes=1)
    await async_db_session.commit()

    claim = await a2a_schedule_service.claim_next_due_task(async_db_session, now=now)

    assert claim is not None
    assert claim.task_id == task.id
    assert claim.scheduled_for <= now

    refreshed = await a2a_schedule_service.get_task(
        async_db_session,
        user_id=user.id,
        task_id=task.id,
    )
    assert refreshed.last_run_status == "running"
    assert refreshed.next_run_at is not None
    assert refreshed.next_run_at > now


async def test_recover_stale_running_task_marks_failed(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="recovery")

    task = await a2a_schedule_service.create_task(
        async_db_session,
        user_id=user.id,
        name="Recover me",
        agent_id=agent.id,
        prompt="hello",
        cycle_type="daily",
        time_point={"time": "00:00"},
        enabled=True,
    )

    old = datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc)
    task.last_run_status = A2AScheduleTask.STATUS_RUNNING
    task.last_run_at = old
    await async_db_session.commit()

    recovered = await a2a_schedule_service.recover_stale_running_tasks(
        async_db_session,
        now=datetime(2026, 2, 1, 0, 20, tzinfo=timezone.utc),
        timeout_seconds=600,
    )
    assert recovered == 1

    refreshed = await a2a_schedule_service.get_task(
        async_db_session, user_id=user.id, task_id=task.id
    )
    assert refreshed.last_run_status == A2AScheduleTask.STATUS_FAILED

    exec_rows = await async_db_session.execute(
        A2AScheduleExecution.__table__.select().where(
            A2AScheduleExecution.task_id == task.id
        )
    )
    assert exec_rows.first() is not None
