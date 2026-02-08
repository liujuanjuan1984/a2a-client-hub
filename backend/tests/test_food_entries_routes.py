from __future__ import annotations

import pytest

from app.api.routers import food_entries as food_entries_router
from backend.tests.api_utils import create_test_client
from backend.tests.utils import create_food, create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_create_and_list_food_entries(async_db_session, async_session_maker):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    food = await create_food(async_db_session, user=user)

    payload = {
        "date": "2025-07-01",
        "consumed_at": "2025-07-01T08:00:00Z",
        "meal_type": "breakfast",
        "food_id": str(food.id),
        "portion_size_g": 80,
    }

    async with create_test_client(
        food_entries_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        create_response = await client.post("/food-entries/", json=payload)
        assert create_response.status_code == 201
        created = create_response.json()
        assert created["meal_type"] == "breakfast"
        assert created["food"]["id"] == str(food.id)

        list_response = await client.get("/food-entries/")

    assert list_response.status_code == 200
    entries = list_response.json()["items"]
    assert entries
    assert entries[0]["food_name"] == food.name


async def test_get_food_entries_invalid_meal_type(
    async_db_session, async_session_maker
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)

    async with create_test_client(
        food_entries_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        response = await client.get("/food-entries/", params={"meal_type": "brunch"})

    assert response.status_code == 400
