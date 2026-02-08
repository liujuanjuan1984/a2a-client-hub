from __future__ import annotations

import pytest

from app.api.routers import tasks as tasks_router
from backend.tests.api_utils import create_test_client
from backend.tests.utils import create_user, create_vision

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_tasks_create_and_list(async_db_session, async_session_maker):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    vision = await create_vision(async_db_session, user)

    async with create_test_client(
        tasks_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        create_resp = await client.post(
            "/tasks/",
            json={"content": "Route task", "vision_id": str(vision.id)},
        )

        assert create_resp.status_code == 201
        created = create_resp.json()
        assert created["content"] == "Route task"
        assert created["vision_id"] == str(vision.id)

        list_resp = await client.get(
            "/tasks/",
            params={"page": 1, "size": 10, "vision_id": str(vision.id)},
        )

        assert list_resp.status_code == 200
        payload = list_resp.json()
        assert payload["pagination"]["total"] >= 1
        assert any(item["id"] == created["id"] for item in payload["items"])


async def test_tasks_query_with_vision_ids(async_db_session, async_session_maker):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    vision_one = await create_vision(async_db_session, user)
    vision_two = await create_vision(async_db_session, user)

    async with create_test_client(
        tasks_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        task_one = await client.post(
            "/tasks/",
            json={"content": "Vision one task", "vision_id": str(vision_one.id)},
        )
        task_two = await client.post(
            "/tasks/",
            json={"content": "Vision two task", "vision_id": str(vision_two.id)},
        )

        assert task_one.status_code == 201
        assert task_two.status_code == 201

        query_resp = await client.post(
            "/tasks/query",
            json={"vision_ids": [str(vision_one.id)], "page": 1, "size": 10},
        )

        assert query_resp.status_code == 200
        payload = query_resp.json()
        assert payload["meta"]["vision_in"] == str(vision_one.id)
        assert payload["pagination"]["total"] == 1
        assert all(item["vision_id"] == str(vision_one.id) for item in payload["items"])


async def test_tasks_query_rejects_mixed_vision_filters(
    async_db_session, async_session_maker
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    vision = await create_vision(async_db_session, user)

    async with create_test_client(
        tasks_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(
            "/tasks/query",
            json={
                "vision_id": str(vision.id),
                "vision_ids": [str(vision.id)],
            },
        )

        assert resp.status_code == 400
