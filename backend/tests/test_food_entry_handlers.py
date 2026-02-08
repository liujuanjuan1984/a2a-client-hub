from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.db.models.food_entry import FoodEntry
from app.handlers import food_entries as food_entries_service
from app.handlers.food_entries import InvalidMealTypeError
from app.schemas.food_entry import FoodEntryCreate, FoodEntryUpdate
from backend.tests.utils import create_food, create_user

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.usefixtures("engine"),
]


async def test_create_food_entry_calculates_nutrition(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    food = await create_food(
        async_db_session,
        user=user,
        calories_per_100g=200,
        protein_per_100g=20,
        carbs_per_100g=10,
        fat_per_100g=5,
    )

    entry = await food_entries_service.create_food_entry(
        async_db_session,
        user_id=user.id,
        entry_in=FoodEntryCreate(
            date="2025-01-01",
            consumed_at=datetime(2025, 1, 1, 8, 0, tzinfo=timezone.utc),
            meal_type="breakfast",
            food_id=food.id,
            portion_size_g=50,
        ),
    )

    assert entry.user_id == user.id
    assert entry.calories == pytest.approx(100)
    assert entry.protein == pytest.approx(10)


async def test_update_food_entry_recalculates_on_portion_change(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    food = await create_food(async_db_session, user=user, calories_per_100g=120)

    entry = await food_entries_service.create_food_entry(
        async_db_session,
        user_id=user.id,
        entry_in=FoodEntryCreate(
            date="2025-02-02",
            consumed_at=datetime(2025, 2, 2, 12, 0, tzinfo=timezone.utc),
            meal_type="lunch",
            food_id=food.id,
            portion_size_g=100,
        ),
    )

    updated = await food_entries_service.update_food_entry(
        async_db_session,
        user_id=user.id,
        entry_id=entry.id,
        update_in=FoodEntryUpdate(portion_size_g=200),
    )

    assert updated.portion_size_g == 200
    assert updated.calories == pytest.approx(240)


async def test_list_food_entries_invalid_meal_type_raises(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    with pytest.raises(InvalidMealTypeError):
        await food_entries_service.list_food_entries(
            async_db_session, user_id=user.id, meal_type="brunch"
        )


async def test_delete_food_entry_soft_delete(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    food = await create_food(async_db_session, user=user)

    entry = await food_entries_service.create_food_entry(
        async_db_session,
        user_id=user.id,
        entry_in=FoodEntryCreate(
            date="2025-03-03",
            consumed_at=datetime(2025, 3, 3, 19, 0, tzinfo=timezone.utc),
            meal_type="dinner",
            food_id=food.id,
            portion_size_g=80,
        ),
    )

    await food_entries_service.delete_food_entry(
        async_db_session, user_id=user.id, entry_id=entry.id
    )
    result = await async_db_session.execute(
        select(FoodEntry.deleted_at).where(FoodEntry.id == entry.id)
    )
    assert result.scalar_one() is not None
