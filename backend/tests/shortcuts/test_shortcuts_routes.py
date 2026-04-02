"""Tests for shortcut persistence routes."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.features.shortcuts import router as shortcuts
from tests.support.api_utils import create_test_client
from tests.support.utils import create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_shortcuts_list_and_mutations(async_db_session, async_session_maker):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)

    async with create_test_client(
        shortcuts.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        list_resp = await client.get("/me/shortcuts")
        assert list_resp.status_code == 200
        list_payload = list_resp.json()
        assert list_payload["pagination"]["total"] == 5
        assert list_payload["items"][0]["id"] == "11111111-1111-1111-1111-111111111111"
        assert list_payload["items"][0]["is_default"] is True
        assert list_payload["items"][0]["created_at"] is None

        create_resp = await client.post(
            "/me/shortcuts",
            json={"title": "My test", "prompt": "Hello from test"},
        )
        assert create_resp.status_code == 201
        custom = create_resp.json()
        assert custom["title"] == "My test"
        assert custom["prompt"] == "Hello from test"
        assert custom["is_default"] is False
        assert custom["created_at"] is not None
        custom_id = custom["id"]

        update_resp = await client.patch(
            f"/me/shortcuts/{custom_id}",
            json={"prompt": "Updated prompt", "order": 10},
        )
        assert update_resp.status_code == 200
        updated = update_resp.json()
        assert updated["prompt"] == "Updated prompt"
        assert updated["order"] == 10

        delete_resp = await client.delete(f"/me/shortcuts/{custom_id}")
        assert delete_resp.status_code == 204

        final_resp = await client.get("/me/shortcuts")
        assert final_resp.status_code == 200
        final_payload = final_resp.json()
        items = final_payload["items"]
        assert len(items) == 5
        assert all(item["id"] != custom_id for item in items)


async def test_shortcuts_default_protection_and_not_found(
    async_db_session,
    async_session_maker,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)

    async with create_test_client(
        shortcuts.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        create_resp = await client.post(
            "/me/shortcuts",
            json={"title": "Custom", "prompt": "Custom value"},
        )
        assert create_resp.status_code == 201
        custom = create_resp.json()
        assert custom["title"] == "Custom"
        assert custom["prompt"] == "Custom value"

        default_resp = await client.patch(
            "/me/shortcuts/11111111-1111-1111-1111-111111111111",
            json={"title": "should-not-change"},
        )
        assert default_resp.status_code == 403

        not_found_resp = await client.delete(f"/me/shortcuts/{uuid4()}")
        assert not_found_resp.status_code == 404

        delete_custom_resp = await client.delete(f"/me/shortcuts/{custom['id']}")
        assert delete_custom_resp.status_code == 204
