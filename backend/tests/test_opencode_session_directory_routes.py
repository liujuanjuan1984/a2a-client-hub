from __future__ import annotations

from typing import Any, Dict, List

import pytest
from sqlalchemy import select

from app.api.routers import opencode_session_directory
from app.db.models.a2a_agent import A2AAgent
from app.db.models.hub_a2a_agent import HubA2AAgent
from app.db.models.opencode_session_cache import OpencodeSessionCacheEntry
from app.integrations.a2a_extensions.service import ExtensionCallResult
from tests.api_utils import create_test_client
from tests.utils import create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _task(session_id: str, *, title: str, updated_ms: int) -> Dict[str, Any]:
    return {
        "kind": "task",
        "contextId": session_id,
        "metadata": {
            "opencode": {
                "title": title,
                "raw": {"time": {"updated": updated_ms}},
            }
        },
    }


async def _create_personal_agent(
    async_db_session, *, user_id, card_url: str
) -> A2AAgent:
    agent = A2AAgent(
        user_id=user_id,
        name="Personal Agent",
        card_url=card_url,
        auth_type="none",
        enabled=True,
    )
    async_db_session.add(agent)
    await async_db_session.commit()
    await async_db_session.refresh(agent)
    return agent


async def _create_hub_agent(
    async_db_session, *, admin_user_id, card_url: str
) -> HubA2AAgent:
    agent = HubA2AAgent(
        name="Shared Agent",
        card_url=card_url,
        availability_policy="public",
        auth_type="none",
        enabled=True,
        tags=None,
        extra_headers=None,
        created_by_user_id=admin_user_id,
        updated_by_user_id=None,
    )
    async_db_session.add(agent)
    await async_db_session.commit()
    await async_db_session.refresh(agent)
    return agent


async def test_opencode_sessions_directory_caches_and_sorts(
    async_db_session,
    async_session_maker,
    monkeypatch,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    personal = await _create_personal_agent(
        async_db_session, user_id=user.id, card_url="https://personal.example.com"
    )
    shared = await _create_hub_agent(
        async_db_session, admin_user_id=user.id, card_url="https://shared.example.com"
    )

    class FakeExtensionsService:
        def __init__(self) -> None:
            self.calls: List[str] = []

        async def opencode_list_sessions(self, *, runtime, page: int, size: int, query):
            url = getattr(getattr(runtime, "resolved", None), "url", "")
            self.calls.append(str(url))
            if "personal" in str(url):
                items = [
                    _task(
                        "ses_personal",
                        title="Personal older",
                        updated_ms=1_700_000_000_000,
                    )
                ]
            else:
                items = [
                    _task(
                        "ses_shared", title="Shared newer", updated_ms=1_700_000_100_000
                    )
                ]
            return ExtensionCallResult(
                success=True,
                result={"items": items, "pagination": {"page": page, "size": size}},
                error_code=None,
                upstream_error=None,
                meta=None,
            )

    fake = FakeExtensionsService()
    monkeypatch.setattr(
        "app.services.opencode_session_directory.get_a2a_extensions_service",
        lambda: fake,
    )

    async with create_test_client(
        opencode_session_directory.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(
            "/me/a2a/opencode/sessions:query",
            json={"page": 1, "size": 50, "refresh": False},
        )
        assert resp.status_code == 200
        payload = resp.json()

        assert payload["meta"]["total_agents"] == 2
        assert payload["pagination"]["total"] == 2

        items = payload["items"]
        assert items[0]["session_id"] == "ses_shared"
        assert items[0]["agent_id"] == str(shared.id)
        assert items[0]["agent_source"] == "shared"
        assert items[0]["agent_name"] == "Shared Agent"
        assert items[0]["title"] == "Shared newer"

        assert items[1]["session_id"] == "ses_personal"
        assert items[1]["agent_id"] == str(personal.id)
        assert items[1]["agent_source"] == "personal"
        assert items[1]["agent_name"] == "Personal Agent"
        assert items[1]["title"] == "Personal older"

        assert len(fake.calls) == 2

        stmt = select(OpencodeSessionCacheEntry)
        result = await async_db_session.execute(stmt)
        cached = list(result.scalars().all())
        assert len(cached) == 2

        # Second call within TTL should not refresh.
        resp2 = await client.post(
            "/me/a2a/opencode/sessions:query",
            json={"page": 1, "size": 50, "refresh": False},
        )
        assert resp2.status_code == 200
        assert len(fake.calls) == 2

        # Explicit refresh should bypass TTL.
        resp3 = await client.post(
            "/me/a2a/opencode/sessions:query",
            json={"page": 1, "size": 50, "refresh": True},
        )
        assert resp3.status_code == 200
        assert len(fake.calls) == 4


async def test_opencode_sessions_directory_deduplicates_across_same_upstream(
    async_db_session,
    async_session_maker,
    monkeypatch,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    # Two agents (personal + shared) that point to the same upstream.
    personal = await _create_personal_agent(
        async_db_session, user_id=user.id, card_url="https://same.example.com"
    )
    await _create_hub_agent(
        async_db_session, admin_user_id=user.id, card_url="https://same.example.com"
    )

    class FakeExtensionsService:
        async def opencode_list_sessions(self, *, runtime, page: int, size: int, query):
            items = [_task("ses_dup", title="Duplicated", updated_ms=1_700_000_000_000)]
            return ExtensionCallResult(
                success=True,
                result={"items": items, "pagination": {"page": page, "size": size}},
                error_code=None,
                upstream_error=None,
                meta=None,
            )

    monkeypatch.setattr(
        "app.services.opencode_session_directory.get_a2a_extensions_service",
        lambda: FakeExtensionsService(),
    )

    async with create_test_client(
        opencode_session_directory.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(
            "/me/a2a/opencode/sessions:query",
            json={"page": 1, "size": 50, "refresh": False},
        )
        assert resp.status_code == 200
        payload = resp.json()

        # Deduped: one session item even though it appears under two agents.
        assert payload["pagination"]["total"] == 1
        item = payload["items"][0]
        assert item["session_id"] == "ses_dup"
        # Prefer personal agent record when timestamps are equal.
        assert item["agent_id"] == str(personal.id)
        assert item["agent_source"] == "personal"
        assert item["agent_name"] == "Personal Agent"
