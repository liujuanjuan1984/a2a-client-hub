from __future__ import annotations

import pytest

from app.api.routers import visions as visions_router
from backend.tests.api_utils import create_test_client
from backend.tests.utils import create_dimension, create_user, create_vision

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_bulk_update_experience_rates_route(
    async_db_session, async_session_maker
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    dimension = await create_dimension(async_db_session, user)
    vision_a = await create_vision(async_db_session, user, dimension=dimension)
    vision_b = await create_vision(async_db_session, user, dimension=dimension)

    payload = {
        "items": [
            {"id": str(vision_a.id), "experience_rate_per_hour": 40},
            {"id": str(vision_b.id), "experience_rate_per_hour": 20},
        ]
    }

    async with create_test_client(
        visions_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        response = await client.put("/visions/experience-rates", json=payload)

    assert response.status_code == 200

    data = response.json()
    returned = {item["id"]: item["experience_rate_per_hour"] for item in data["items"]}
    assert returned[str(vision_a.id)] == 40
    assert returned[str(vision_b.id)] == 20

    await async_db_session.refresh(vision_a)
    await async_db_session.refresh(vision_b)
    assert vision_a.experience_rate_per_hour == 40
    assert vision_b.experience_rate_per_hour == 20


async def test_update_vision_requires_uuid_path(async_db_session, async_session_maker):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    dimension = await create_dimension(async_db_session, user)
    vision = await create_vision(async_db_session, user, dimension=dimension)

    payload = {
        "name": vision.name,
        "description": vision.description,
        "status": vision.status,
    }

    async with create_test_client(
        visions_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        response = await client.put("/visions/not-a-uuid", json=payload)

    assert response.status_code == 404
