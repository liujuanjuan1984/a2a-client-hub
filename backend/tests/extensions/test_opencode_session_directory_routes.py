from __future__ import annotations

from typing import Any, Dict, List

import pytest
from sqlalchemy import event, select

from app.core.secret_vault import hub_a2a_secret_vault, user_llm_secret_vault
from app.db.models.a2a_agent import A2AAgent
from app.db.models.external_session_directory_cache import (
    ExternalSessionDirectoryCacheEntry,
)
from app.features.agents_shared.common import upsert_agent_credential
from app.features.hub_agents.runtime import HubA2ARuntimeValidationError
from app.features.opencode_sessions import router as opencode_session_directory
from app.features.personal_agents.runtime import A2ARuntimeValidationError
from app.integrations.a2a_extensions.service import ExtensionCallResult
from tests.support.api_utils import create_test_client
from tests.support.utils import create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _task(session_id: str, *, title: str, last_active_at: str) -> Dict[str, Any]:
    return {
        "kind": "task",
        "contextId": f"ctx:opencode-session:{session_id}",
        "last_active_at": last_active_at,
        "metadata": {
            "opencode": {
                "session_id": session_id,
                "title": title,
            }
        },
    }


async def _create_personal_agent(
    async_db_session, *, user_id, card_url: str, auth_type: str = "none"
) -> A2AAgent:
    agent = A2AAgent(
        user_id=user_id,
        name="Personal Agent",
        card_url=card_url,
        auth_type=auth_type,
        enabled=True,
    )
    async_db_session.add(agent)
    await async_db_session.commit()
    await async_db_session.refresh(agent)
    return agent


async def _create_hub_agent(
    async_db_session, *, admin_user_id, card_url: str, auth_type: str = "none"
) -> A2AAgent:
    agent = A2AAgent(
        user_id=admin_user_id,
        name="Shared Agent",
        card_url=card_url,
        agent_scope=A2AAgent.SCOPE_SHARED,
        availability_policy="public",
        auth_type=auth_type,
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


async def _set_agent_credential(
    async_db_session,
    *,
    agent_id,
    user_id,
    token: str,
    shared: bool,
) -> None:
    await upsert_agent_credential(
        async_db_session,
        vault=hub_a2a_secret_vault if shared else user_llm_secret_vault,
        agent_id=agent_id,
        user_id=user_id,
        token=token,
        validation_error_cls=(
            HubA2ARuntimeValidationError if shared else A2ARuntimeValidationError
        ),
    )
    await async_db_session.commit()


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

        async def list_sessions(self, *, runtime, page: int, size: int, query):
            url = getattr(getattr(runtime, "resolved", None), "url", "")
            self.calls.append(str(url))
            if "personal" in str(url):
                items = [
                    _task(
                        "ses_personal",
                        title="Personal older",
                        last_active_at="2024-01-01T00:00:00+00:00",
                    )
                ]
            else:
                items = [
                    _task(
                        "ses_shared",
                        title="Shared newer",
                        last_active_at="2024-01-02T00:00:00+00:00",
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
        "app.features.opencode_sessions.service.get_a2a_extensions_service",
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

        stmt = select(ExternalSessionDirectoryCacheEntry)
        result = await async_db_session.execute(stmt)
        cached = list(result.scalars().all())
        assert len(cached) == 2
        assert all(item.provider == "opencode" for item in cached)
        for cache_item in cached:
            cached_items = cache_item.payload.get("items", [])
            assert isinstance(cached_items, list)
            for task in cached_items:
                opencode_meta = (
                    ((task.get("metadata") or {}).get("opencode") or {})
                    if isinstance(task, dict)
                    else {}
                )
                assert "raw" not in opencode_meta

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
        async def list_sessions(self, *, runtime, page: int, size: int, query):
            items = [
                _task(
                    "ses_dup",
                    title="Duplicated",
                    last_active_at="2024-01-01T00:00:00+00:00",
                )
            ]
            return ExtensionCallResult(
                success=True,
                result={"items": items, "pagination": {"page": page, "size": size}},
                error_code=None,
                upstream_error=None,
                meta=None,
            )

    monkeypatch.setattr(
        "app.features.opencode_sessions.service.get_a2a_extensions_service",
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


async def test_opencode_sessions_directory_does_not_treat_context_id_as_session_id(
    async_db_session,
    async_session_maker,
    monkeypatch,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    await _create_personal_agent(
        async_db_session, user_id=user.id, card_url="https://personal.example.com"
    )

    class FakeExtensionsService:
        async def list_sessions(self, *, runtime, page: int, size: int, query):
            items = [
                {
                    "kind": "task",
                    "contextId": "ctx:opencode-session:ses_only_in_context",
                    "last_active_at": "2024-01-01T00:00:00+00:00",
                    "metadata": {"opencode": {"title": "No binding id"}},
                }
            ]
            return ExtensionCallResult(
                success=True,
                result={"items": items, "pagination": {"page": page, "size": size}},
                error_code=None,
                upstream_error=None,
                meta=None,
            )

    monkeypatch.setattr(
        "app.features.opencode_sessions.service.get_a2a_extensions_service",
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
        assert payload["items"] == []
        assert payload["pagination"]["total"] == 0


async def test_opencode_sessions_directory_ignores_legacy_external_session_id_aliases(
    async_db_session,
    async_session_maker,
    monkeypatch,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    await _create_personal_agent(
        async_db_session, user_id=user.id, card_url="https://personal.example.com"
    )

    class FakeExtensionsService:
        async def list_sessions(self, *, runtime, page: int, size: int, query):
            items = [
                {
                    "kind": "task",
                    "last_active_at": "2024-01-01T00:00:00+00:00",
                    "metadata": {
                        "opencode": {
                            "external_session_id": "legacy-external-session",
                            "title": "Legacy only",
                        }
                    },
                }
            ]
            return ExtensionCallResult(
                success=True,
                result={"items": items, "pagination": {"page": page, "size": size}},
                error_code=None,
                upstream_error=None,
                meta=None,
            )

    monkeypatch.setattr(
        "app.features.opencode_sessions.service.get_a2a_extensions_service",
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
        assert payload["items"] == []
        assert payload["pagination"]["total"] == 0


async def test_opencode_sessions_directory_refresh_avoids_n_plus_one_runtime_queries(
    async_db_session,
    async_session_maker,
    async_engine,
    monkeypatch,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)

    for idx in range(3):
        personal = await _create_personal_agent(
            async_db_session,
            user_id=user.id,
            card_url=f"https://personal-{idx}.example.com",
            auth_type="bearer",
        )
        await _set_agent_credential(
            async_db_session,
            agent_id=personal.id,
            user_id=user.id,
            token=f"personal-token-{idx}",
            shared=False,
        )

    for idx in range(3):
        shared = await _create_hub_agent(
            async_db_session,
            admin_user_id=user.id,
            card_url=f"https://shared-{idx}.example.com",
            auth_type="bearer",
        )
        await _set_agent_credential(
            async_db_session,
            agent_id=shared.id,
            user_id=user.id,
            token=f"shared-token-{idx}",
            shared=True,
        )

    class FakeExtensionsService:
        async def list_sessions(self, *, runtime, page: int, size: int, query):
            return ExtensionCallResult(
                success=True,
                result={"items": [], "pagination": {"page": page, "size": size}},
                error_code=None,
                upstream_error=None,
                meta=None,
            )

    monkeypatch.setattr(
        "app.features.opencode_sessions.service.get_a2a_extensions_service",
        lambda: FakeExtensionsService(),
    )

    select_statements: list[str] = []

    def _count_selects(
        conn, cursor, statement, parameters, context, executemany
    ):  # noqa: ARG001
        if statement.lstrip().upper().startswith("SELECT"):
            select_statements.append(statement.lower())

    def _where_clause(statement: str) -> str:
        if "where" not in statement:
            return ""
        return statement.split("where", 1)[1]

    async with create_test_client(
        opencode_session_directory.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        event.listen(
            async_engine.sync_engine,
            "before_cursor_execute",
            _count_selects,
        )
        try:
            resp = await client.post(
                "/me/a2a/opencode/sessions:query",
                json={"page": 1, "size": 50, "refresh": False},
            )
        finally:
            event.remove(
                async_engine.sync_engine,
                "before_cursor_execute",
                _count_selects,
            )

    assert resp.status_code == 200
    credential_batch_selects = [
        stmt
        for stmt in select_statements
        if "a2a_agent_credentials" in stmt and " in (" in stmt
    ]
    per_agent_credential_selects = [
        stmt
        for stmt in select_statements
        if "a2a_agent_credentials.agent_id =" in _where_clause(stmt)
        and " in (" not in _where_clause(stmt)
    ]
    per_agent_agent_selects = [
        stmt
        for stmt in select_statements
        if "a2a_agents.id =" in _where_clause(stmt)
        and " in (" not in _where_clause(stmt)
    ]

    assert len(credential_batch_selects) == 1
    assert per_agent_credential_selects == []
    assert per_agent_agent_selects == []
    assert len(select_statements) <= 6
