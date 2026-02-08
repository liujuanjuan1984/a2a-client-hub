from __future__ import annotations

import pytest

from app.api.routers import tags as tags_router
from backend.tests.api_utils import create_test_client
from backend.tests.utils import create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_tags_create_and_list(async_db_session, async_session_maker):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)

    async with create_test_client(
        tags_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        create_resp = await client.post(
            "/tags/",
            json={"name": "Test Tag", "entity_type": "general"},
        )

        assert create_resp.status_code == 201
        created = create_resp.json()
        assert created["name"] == "test tag"
        assert created["entity_type"] == "general"

        list_resp = await client.get("/tags/", params={"page": 1, "size": 10})

        assert list_resp.status_code == 200
        payload = list_resp.json()
        assert payload["pagination"]["total"] >= 1
        assert any(item["id"] == created["id"] for item in payload["items"])


async def test_tags_categories(async_db_session, async_session_maker):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)

    async with create_test_client(
        tags_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.get("/tags/categories/")

        assert resp.status_code == 200
        payload = resp.json()
        values = {item["value"] for item in payload}
        assert "general" in values


async def test_tags_update_null_category_defaults(
    async_db_session, async_session_maker
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)

    async with create_test_client(
        tags_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        create_resp = await client.post(
            "/tags/",
            json={
                "name": "Location Tag",
                "entity_type": "person",
                "category": "location",
            },
        )
        assert create_resp.status_code == 201
        created = create_resp.json()

        update_resp = await client.put(
            f"/tags/{created['id']}",
            json={"category": None},
        )

        assert update_resp.status_code == 200
        updated = update_resp.json()
        assert updated["category"] == "general"
