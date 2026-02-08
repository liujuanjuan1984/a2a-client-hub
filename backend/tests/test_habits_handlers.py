from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.core.constants import HABIT_EDITABLE_DAYS
from app.db.models.habit_action import HabitAction
from app.handlers import habits as habits_service
from app.handlers.habits import InvalidOperationError, ValidationError
from app.schemas.habit import HabitCreate, HabitUpdate
from backend.tests.utils import create_user

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.usefixtures("engine"),
]


TEST_HABIT_LIMIT = 5


def _set_habit_limit(monkeypatch, limit: int = TEST_HABIT_LIMIT) -> int:
    """Reduce MAX_ACTIVE_HABITS for tests to avoid创建大量样本, 并跳过庞大的 action 生成。"""

    monkeypatch.setattr("app.core.constants.MAX_ACTIVE_HABITS", limit, raising=False)
    monkeypatch.setattr("app.handlers.habits.MAX_ACTIVE_HABITS", limit, raising=False)

    async def _noop_generate_actions(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "app.handlers.habits._generate_habit_actions",
        _noop_generate_actions,
        raising=False,
    )
    return limit


async def test_create_habit_rejects_old_start_date(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    too_old = date.today() - timedelta(days=HABIT_EDITABLE_DAYS + 1)

    with pytest.raises(ValidationError):
        await habits_service.create_habit(
            async_db_session,
            user_id=user.id,
            habit_in=HabitCreate(
                title="Morning Run",
                description="",
                start_date=too_old,
                duration_days=7,
            ),
        )


async def test_create_habit_generates_actions(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    habit = await habits_service.create_habit(
        async_db_session,
        user_id=user.id,
        habit_in=HabitCreate(
            title="Read",
            description="",
            start_date=date.today(),
            duration_days=7,
        ),
    )

    result = await async_db_session.execute(
        select(HabitAction).where(
            HabitAction.habit_id == habit.id,
            HabitAction.deleted_at.is_(None),
        )
    )
    actions = result.scalars().all()
    assert len(actions) == 7


async def test_create_habit_enforces_active_limit(async_db_session, monkeypatch):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    today = date.today()
    limit = _set_habit_limit(monkeypatch)

    for i in range(limit):
        await habits_service.create_habit(
            async_db_session,
            user_id=user.id,
            habit_in=HabitCreate(
                title=f"Habit {i}",
                description="",
                start_date=today + timedelta(days=i),
                duration_days=7,
            ),
        )

    with pytest.raises(InvalidOperationError):
        await habits_service.create_habit(
            async_db_session,
            user_id=user.id,
            habit_in=HabitCreate(
                title="Overflow Habit",
                description="",
                start_date=today + timedelta(days=limit),
                duration_days=7,
            ),
        )


async def test_update_habit_cannot_exceed_active_limit(async_db_session, monkeypatch):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    today = date.today()
    limit = _set_habit_limit(monkeypatch)

    for i in range(limit - 1):
        await habits_service.create_habit(
            async_db_session,
            user_id=user.id,
            habit_in=HabitCreate(
                title=f"Seed Habit {i}",
                description="",
                start_date=today + timedelta(days=i),
                duration_days=7,
            ),
        )

    target_habit = await habits_service.create_habit(
        async_db_session,
        user_id=user.id,
        habit_in=HabitCreate(
            title="Target Habit",
            description="",
            start_date=today,
            duration_days=7,
        ),
    )
    target_habit.status = "paused"
    await async_db_session.commit()

    await habits_service.create_habit(
        async_db_session,
        user_id=user.id,
        habit_in=HabitCreate(
            title="Final Habit",
            description="",
            start_date=today + timedelta(days=limit + 1),
            duration_days=7,
        ),
    )

    with pytest.raises(InvalidOperationError):
        await habits_service.update_habit(
            async_db_session,
            user_id=user.id,
            habit_id=target_habit.id,
            habit_update=HabitUpdate(status="active"),
        )


async def test_get_habit_actions_supports_date_window(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    start = date.today() - timedelta(days=10)
    habit = await habits_service.create_habit(
        async_db_session,
        user_id=user.id,
        habit_in=HabitCreate(
            title="Windowed Habit",
            description="",
            start_date=start,
            duration_days=21,
        ),
    )

    actions, total = await habits_service.get_habit_actions(
        async_db_session,
        user_id=user.id,
        habit_id=habit.id,
        center_date=date.today(),
        days_before=3,
        days_after=1,
    )

    assert total == 5
    assert actions[0].action_date == date.today() - timedelta(days=3)
    assert actions[-1].action_date == date.today() + timedelta(days=1)


async def test_get_habit_actions_window_rejects_large_ranges(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    habit = await habits_service.create_habit(
        async_db_session,
        user_id=user.id,
        habit_in=HabitCreate(
            title="Large Window Habit",
            description="",
            start_date=date.today(),
            duration_days=365,
        ),
    )

    with pytest.raises(ValidationError):
        await habits_service.get_habit_actions(
            async_db_session,
            user_id=user.id,
            habit_id=habit.id,
            center_date=date.today(),
            days_before=60,
            days_after=60,
        )


async def test_get_habit_overview_includes_stats(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    habit = await habits_service.create_habit(
        async_db_session,
        user_id=user.id,
        habit_in=HabitCreate(
            title="Meditation",
            description="",
            start_date=date.today(),
            duration_days=7,
        ),
    )

    overview = await habits_service.get_habit_overview(
        async_db_session,
        user_id=user.id,
        habit_id=habit.id,
    )

    assert overview["habit"].id == habit.id
    stats = overview["stats"]
    assert stats["habit_id"] == habit.id
    assert "total_actions" in stats


async def test_list_habit_overviews_returns_total(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    today = date.today()

    for idx in range(2):
        await habits_service.create_habit(
            async_db_session,
            user_id=user.id,
            habit_in=HabitCreate(
                title=f"Habit {idx}",
                description="",
                start_date=today,
                duration_days=7,
            ),
        )

    overviews, total = await habits_service.list_habit_overviews(
        async_db_session,
        user_id=user.id,
        skip=0,
        limit=10,
        status_filter="active",
    )

    assert total == 2
    assert len(overviews) == 2
    assert all("stats" in entry for entry in overviews)
