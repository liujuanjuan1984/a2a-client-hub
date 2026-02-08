from __future__ import annotations

import pytest

from app.api.routers import foods as foods_router
from backend.tests.api_utils import create_test_client
from backend.tests.utils import create_food, create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_create_food_and_list(async_db_session, async_session_maker):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    payload = {
        "name": "Greek Yogurt",
        "calories_per_100g": 60,
        "is_common": False,
    }

    async with create_test_client(
        foods_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        db_session=async_db_session,
    ) as client:
        create_response = await client.post("/foods/", json=payload)
        assert create_response.status_code == 201
        created = create_response.json()
        assert created["name"] == "Greek Yogurt"

        list_response = await client.get("/foods/")

    assert list_response.status_code == 200
    foods = list_response.json()["items"]
    assert any(item["name"] == "Greek Yogurt" for item in foods)


async def test_create_food_duplicate_name_returns_400(
    async_db_session, async_session_maker
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    await create_food(async_db_session, user=user, name="Protein Shake")

    async with create_test_client(
        foods_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        db_session=async_db_session,
    ) as client:
        response = await client.post(
            "/foods/",
            json={"name": "Protein Shake", "calories_per_100g": 100},
        )

    assert response.status_code == 400


async def test_get_food_permission_denied_for_private_food(
    async_db_session, async_session_maker
):
    owner = await create_user(async_db_session, skip_onboarding_defaults=True)
    other_user = await create_user(async_db_session, skip_onboarding_defaults=True)
    private_food = await create_food(async_db_session, user=owner, name="Secret Recipe")

    async with create_test_client(
        foods_router.router,
        async_session_maker=async_session_maker,
        current_user=other_user,
        db_session=async_db_session,
    ) as client:
        response = await client.get(f"/foods/{private_food.id}")

    assert response.status_code == 403


async def test_update_food_requires_ownership(async_db_session, async_session_maker):
    owner = await create_user(async_db_session, skip_onboarding_defaults=True)
    other_user = await create_user(async_db_session, skip_onboarding_defaults=True)
    private_food = await create_food(async_db_session, user=owner, name="Family Dish")

    async with create_test_client(
        foods_router.router,
        async_session_maker=async_session_maker,
        current_user=other_user,
        db_session=async_db_session,
    ) as client:
        response = await client.put(
            f"/foods/{private_food.id}",
            json={"name": "Modified Dish"},
        )

    assert response.status_code == 403
