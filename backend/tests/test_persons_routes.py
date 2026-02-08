from __future__ import annotations

import pytest

from app.api.routers import persons as persons_router
from backend.tests.api_utils import create_test_client
from backend.tests.utils import create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_persons_create_and_list(async_db_session, async_session_maker):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)

    async with create_test_client(
        persons_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        create_resp = await client.post("/persons/", json={"name": "Alice"})

        assert create_resp.status_code == 201
        created = create_resp.json()
        assert created["name"] == "Alice"

        list_resp = await client.get("/persons/", params={"page": 1, "size": 10})

        assert list_resp.status_code == 200
        payload = list_resp.json()
        assert payload["pagination"]["total"] >= 1
        assert any(item["id"] == created["id"] for item in payload["items"])
