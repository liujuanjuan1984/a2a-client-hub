from __future__ import annotations

from typing import Any, Dict

import pytest
from sqlalchemy import select

from app.api.routers import admin_a2a_agents as admin_router
from app.api.routers import hub_a2a_agents as hub_router
from app.core.config import settings
from app.db.models.hub_a2a_agent_allowlist import HubA2AAgentAllowlistEntry
from app.db.models.hub_a2a_agent_credential import HubA2AAgentCredential
from backend.tests.api_utils import create_test_client
from backend.tests.utils import create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class _FakeGateway:
    def __init__(self) -> None:
        self.calls: list[Dict[str, Any]] = []

    async def invoke(self, *, resolved, query: str, context_id=None, metadata=None):
        self.calls.append(
            {
                "resolved": resolved,
                "query": query,
                "context_id": context_id,
                "metadata": metadata,
            }
        )
        return {"success": True, "content": "ok"}

    async def stream(self, *, resolved, query: str, context_id=None, metadata=None):
        self.calls.append(
            {
                "resolved": resolved,
                "query": query,
                "context_id": context_id,
                "metadata": metadata,
                "stream": True,
            }
        )

        class _MockMessage:
            def model_dump(self, **kwargs):
                return {"content": "ok"}

        yield _MockMessage()


class _FakeA2AService:
    def __init__(self, gateway: _FakeGateway) -> None:
        self.gateway = gateway


@pytest.mark.asyncio
async def test_allowlist_agents_are_invisible_and_404_for_non_allowlisted_users(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    admin = await create_user(
        async_db_session, email="admin@example.com", is_superuser=True
    )
    alice = await create_user(
        async_db_session, email="alice@example.com", is_superuser=False
    )

    async with create_test_client(
        admin_router.router,
        async_session_maker=async_session_maker,
        current_user=admin,
        base_prefix=settings.api_v1_prefix,
    ) as admin_client:
        create_payload = {
            "name": "Private Agent",
            "card_url": "https://example.com/.well-known/agent-card.json",
            "availability_policy": "allowlist",
            "auth_type": "bearer",
            "token": "secret-token-1234",
            "enabled": True,
            "tags": ["opencode"],
            "extra_headers": {},
        }
        resp = await admin_client.post(
            f"{settings.api_v1_prefix}/admin/a2a/agents", json=create_payload
        )
        assert resp.status_code == 201
        created = resp.json()
        agent_id = created["id"]
        assert created["has_credential"] is True
        assert created["token_last4"] == "1234"

    async with create_test_client(
        hub_router.router,
        async_session_maker=async_session_maker,
        current_user=alice,
        base_prefix=settings.api_v1_prefix,
    ) as user_client:
        list_resp = await user_client.get(f"{settings.api_v1_prefix}/a2a/agents")
        assert list_resp.status_code == 200
        assert list_resp.json()["items"] == []

        invoke_resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/invoke",
            json={"query": "hi", "metadata": {}},
        )
        assert invoke_resp.status_code == 404


@pytest.mark.asyncio
async def test_allowlisted_user_can_invoke_and_headers_include_system_token(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    admin = await create_user(
        async_db_session, email="admin2@example.com", is_superuser=True
    )
    alice = await create_user(
        async_db_session, email="alice2@example.com", is_superuser=False
    )

    async with create_test_client(
        admin_router.router,
        async_session_maker=async_session_maker,
        current_user=admin,
        base_prefix=settings.api_v1_prefix,
    ) as admin_client:
        create_payload = {
            "name": "Private Agent",
            "card_url": "https://example.com/.well-known/agent-card.json",
            "availability_policy": "allowlist",
            "auth_type": "bearer",
            "token": "secret-token-9999",
            "enabled": True,
            "tags": [],
            "extra_headers": {},
        }
        resp = await admin_client.post(
            f"{settings.api_v1_prefix}/admin/a2a/agents", json=create_payload
        )
        assert resp.status_code == 201
        agent_id = resp.json()["id"]

        allow_resp = await admin_client.post(
            f"{settings.api_v1_prefix}/admin/a2a/agents/{agent_id}/allowlist",
            json={"email": alice.email},
        )
        assert allow_resp.status_code == 201
        assert allow_resp.json()["user_id"] == str(alice.id)

    fake_gateway = _FakeGateway()
    monkeypatch.setattr(
        hub_router, "get_a2a_service", lambda: _FakeA2AService(fake_gateway)
    )

    async with create_test_client(
        hub_router.router,
        async_session_maker=async_session_maker,
        current_user=alice,
        base_prefix=settings.api_v1_prefix,
    ) as user_client:
        list_resp = await user_client.get(f"{settings.api_v1_prefix}/a2a/agents")
        assert list_resp.status_code == 200
        items = list_resp.json()["items"]
        assert len(items) == 1
        assert items[0]["id"] == agent_id
        assert "token_last4" not in items[0]

        invoke_resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/invoke",
            json={"query": "hi", "metadata": {}},
        )
        assert invoke_resp.status_code == 200
        assert invoke_resp.json()["success"] is True

    assert len(fake_gateway.calls) == 1
    resolved = fake_gateway.calls[0]["resolved"]
    assert resolved.headers["Authorization"].endswith("secret-token-9999")


@pytest.mark.asyncio
async def test_allowlisted_user_can_stream_sse(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    admin = await create_user(
        async_db_session, email="admin_stream@example.com", is_superuser=True
    )
    alice = await create_user(
        async_db_session, email="alice_stream@example.com", is_superuser=False
    )

    async with create_test_client(
        admin_router.router,
        async_session_maker=async_session_maker,
        current_user=admin,
        base_prefix=settings.api_v1_prefix,
    ) as admin_client:
        create_payload = {
            "name": "Stream Agent",
            "card_url": "https://example.com/.well-known/agent-card.json",
            "availability_policy": "allowlist",
            "auth_type": "bearer",
            "token": "secret-token-stream",
            "enabled": True,
            "tags": [],
            "extra_headers": {},
        }
        resp = await admin_client.post(
            f"{settings.api_v1_prefix}/admin/a2a/agents", json=create_payload
        )
        assert resp.status_code == 201
        agent_id = resp.json()["id"]

        allow_resp = await admin_client.post(
            f"{settings.api_v1_prefix}/admin/a2a/agents/{agent_id}/allowlist",
            json={"email": alice.email},
        )
        assert allow_resp.status_code == 201

    fake_gateway = _FakeGateway()
    monkeypatch.setattr(
        hub_router, "get_a2a_service", lambda: _FakeA2AService(fake_gateway)
    )
    monkeypatch.setattr(hub_router, "validate_message", lambda payload: [])

    async with create_test_client(
        hub_router.router,
        async_session_maker=async_session_maker,
        current_user=alice,
        base_prefix=settings.api_v1_prefix,
    ) as user_client:
        async with user_client.stream(
            "POST",
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/invoke",
            params={"stream": "true"},
            json={"query": "hi", "metadata": {}},
        ) as stream_resp:
            assert stream_resp.status_code == 200
            assert stream_resp.headers["content-type"].startswith("text/event-stream")
            body = (await stream_resp.aread()).decode("utf-8")
            assert "data:" in body
            assert "event: stream_end" in body

    # Ensure we injected the system-managed Authorization header.
    resolved = fake_gateway.calls[0]["resolved"]
    assert resolved.headers["Authorization"].endswith("secret-token-stream")


@pytest.mark.asyncio
async def test_ws_token_404_for_non_allowlisted_user(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    admin = await create_user(
        async_db_session, email="admin_ws_token@example.com", is_superuser=True
    )
    alice = await create_user(
        async_db_session, email="alice_ws_token@example.com", is_superuser=False
    )

    async with create_test_client(
        admin_router.router,
        async_session_maker=async_session_maker,
        current_user=admin,
        base_prefix=settings.api_v1_prefix,
    ) as admin_client:
        create_payload = {
            "name": "Private Agent",
            "card_url": "https://example.com/.well-known/agent-card.json",
            "availability_policy": "allowlist",
            "auth_type": "none",
            "enabled": True,
            "tags": [],
            "extra_headers": {},
        }
        resp = await admin_client.post(
            f"{settings.api_v1_prefix}/admin/a2a/agents", json=create_payload
        )
        assert resp.status_code == 201
        agent_id = resp.json()["id"]

    async with create_test_client(
        hub_router.router,
        async_session_maker=async_session_maker,
        current_user=alice,
        base_prefix=settings.api_v1_prefix,
    ) as user_client:
        ws_token_resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/invoke/ws-token"
        )
        assert ws_token_resp.status_code == 404


@pytest.mark.asyncio
async def test_ws_token_200_for_allowlisted_user(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    admin = await create_user(
        async_db_session, email="admin_ws_token2@example.com", is_superuser=True
    )
    alice = await create_user(
        async_db_session, email="alice_ws_token2@example.com", is_superuser=False
    )

    async with create_test_client(
        admin_router.router,
        async_session_maker=async_session_maker,
        current_user=admin,
        base_prefix=settings.api_v1_prefix,
    ) as admin_client:
        create_payload = {
            "name": "Private Agent",
            "card_url": "https://example.com/.well-known/agent-card.json",
            "availability_policy": "allowlist",
            "auth_type": "none",
            "enabled": True,
            "tags": [],
            "extra_headers": {},
        }
        resp = await admin_client.post(
            f"{settings.api_v1_prefix}/admin/a2a/agents", json=create_payload
        )
        assert resp.status_code == 201
        agent_id = resp.json()["id"]

        allow_resp = await admin_client.post(
            f"{settings.api_v1_prefix}/admin/a2a/agents/{agent_id}/allowlist",
            json={"email": alice.email},
        )
        assert allow_resp.status_code == 201

    async with create_test_client(
        hub_router.router,
        async_session_maker=async_session_maker,
        current_user=alice,
        base_prefix=settings.api_v1_prefix,
    ) as user_client:
        ws_token_resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/invoke/ws-token"
        )
        assert ws_token_resp.status_code == 200
        payload = ws_token_resp.json()
        assert payload["token"]
        assert payload["expires_at"]
        assert payload["expires_in"] > 0


@pytest.mark.asyncio
async def test_admin_delete_purges_allowlist_and_credentials(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    admin = await create_user(
        async_db_session, email="admin3@example.com", is_superuser=True
    )
    alice = await create_user(
        async_db_session, email="alice3@example.com", is_superuser=False
    )

    async with create_test_client(
        admin_router.router,
        async_session_maker=async_session_maker,
        current_user=admin,
        base_prefix=settings.api_v1_prefix,
    ) as admin_client:
        create_payload = {
            "name": "Private Agent",
            "card_url": "https://example.com/.well-known/agent-card.json",
            "availability_policy": "allowlist",
            "auth_type": "bearer",
            "token": "secret-token-0001",
            "enabled": True,
            "tags": [],
            "extra_headers": {},
        }
        resp = await admin_client.post(
            f"{settings.api_v1_prefix}/admin/a2a/agents", json=create_payload
        )
        assert resp.status_code == 201
        agent_id = resp.json()["id"]

        allow_resp = await admin_client.post(
            f"{settings.api_v1_prefix}/admin/a2a/agents/{agent_id}/allowlist",
            json={"email": alice.email},
        )
        assert allow_resp.status_code == 201

        delete_resp = await admin_client.delete(
            f"{settings.api_v1_prefix}/admin/a2a/agents/{agent_id}"
        )
        assert delete_resp.status_code == 204

    # Credentials/allowlist rows should be purged on delete.
    credential = await async_db_session.scalar(
        select(HubA2AAgentCredential).where(HubA2AAgentCredential.agent_id == agent_id)
    )
    assert credential is None

    allow_entry = await async_db_session.scalar(
        select(HubA2AAgentAllowlistEntry).where(
            HubA2AAgentAllowlistEntry.agent_id == agent_id
        )
    )
    assert allow_entry is None
