from __future__ import annotations

from uuid import uuid4

import pytest

from app.api.routers import dimensions as dimensions_router
from backend.tests.api_utils import create_test_client
from backend.tests.utils import create_dimension, create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _dimension_payload(name: str = "Focus") -> dict:
    return {
        "name": name,
        "description": "",
        "color": "#123ABC",
        "icon": None,
        "is_active": True,
        "display_order": 0,
    }


async def test_get_dimensions_returns_active_only(
    async_db_session, async_session_maker
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    dim = await create_dimension(async_db_session, user, name="Wellness")

    async with create_test_client(
        dimensions_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        response = await client.get("/dimensions/")

    assert response.status_code == 200
    data = response.json()
    items = data["items"]
    assert len(items) == 1
    assert items[0]["id"] == str(dim.id)


async def test_create_dimension_conflict_returns_409(
    async_db_session, async_session_maker
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    await create_dimension(async_db_session, user, name="Work")

    async with create_test_client(
        dimensions_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        response = await client.post("/dimensions/", json=_dimension_payload("Work"))

    assert response.status_code == 409


async def test_update_dimension_not_found_returns_404(
    async_db_session, async_session_maker
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)

    async with create_test_client(
        dimensions_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        response = await client.put(
            f"/dimensions/{uuid4()}",
            json={"name": "Updated", "color": "#FFFFFF"},
        )

    assert response.status_code == 404


async def test_set_dimension_order_updates_preference(
    async_db_session, async_session_maker
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    dim_a = await create_dimension(async_db_session, user, name="Health")
    dim_b = await create_dimension(async_db_session, user, name="Career")

    async with create_test_client(
        dimensions_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        response = await client.put(
            "/dimensions/order",
            json=[str(dim_b.id), str(dim_a.id)],
        )
        assert response.status_code == 200
        pref = response.json()
        assert pref["value"] == [str(dim_b.id), str(dim_a.id)]

        get_response = await client.get("/dimensions/order")
        assert get_response.status_code == 200
        assert get_response.json()["value"] == [str(dim_b.id), str(dim_a.id)]
