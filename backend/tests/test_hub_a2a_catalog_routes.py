from __future__ import annotations

from typing import Any, Dict
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.api.routers import admin_a2a_agents as admin_router
from app.api.routers import hub_a2a_agents as hub_router
from app.core.config import settings
from app.db.models.a2a_agent_credential import A2AAgentCredential
from app.db.models.conversation_thread import ConversationThread
from app.db.models.hub_a2a_agent_allowlist import HubA2AAgentAllowlistEntry
from tests.api_utils import create_test_client
from tests.utils import create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class _FakeGateway:
    def __init__(self) -> None:
        self.calls: list[Dict[str, Any]] = []
        self.invoke_response: Dict[str, Any] = {"success": True, "content": "ok"}
        self.stream_events: list[Dict[str, Any]] = [{"content": "ok"}]

    async def invoke(self, *, resolved, query: str, context_id=None, metadata=None):
        self.calls.append(
            {
                "resolved": resolved,
                "query": query,
                "context_id": context_id,
                "metadata": metadata,
            }
        )
        return dict(self.invoke_response)

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
            def __init__(self, payload: Dict[str, Any]) -> None:
                self._payload = payload

            def model_dump(self, **kwargs):
                return dict(self._payload)

        for event_payload in self.stream_events:
            yield _MockMessage(event_payload)


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
    fake_gateway.stream_events = [
        {
            "content": "ok",
            "contextId": "ctx-upstream-1",
            "metadata": {
                "provider": "opencode",
                "externalSessionId": "upstream-session-1",
            },
        }
    ]
    monkeypatch.setattr(
        hub_router, "get_a2a_service", lambda: _FakeA2AService(fake_gateway)
    )
    conversation_id = str(uuid4())
    agent_uuid = UUID(agent_id)

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
            json={"query": "hi", "conversationId": conversation_id, "metadata": {}},
        )
        assert invoke_resp.status_code == 200
        assert invoke_resp.json()["success"] is True

    assert len(fake_gateway.calls) == 1
    resolved = fake_gateway.calls[0]["resolved"]
    assert resolved.headers["Authorization"].endswith("secret-token-9999")
    external_binding = await async_db_session.scalar(
        select(ConversationThread).where(
            ConversationThread.user_id == alice.id,
            ConversationThread.id == UUID(conversation_id),
            ConversationThread.external_provider == "opencode",
            ConversationThread.agent_id == agent_uuid,
            ConversationThread.agent_source == "shared",
            ConversationThread.external_session_id == "upstream-session-1",
        )
    )
    assert external_binding is not None
    assert external_binding.context_id == "ctx-upstream-1"


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
    fake_gateway.stream_events = [
        {
            "content": "ok",
            "contextId": "ctx-stream-1",
            "metadata": {
                "provider": "opencode",
                "externalSessionId": "upstream-stream-1",
            },
        }
    ]
    monkeypatch.setattr(
        hub_router, "get_a2a_service", lambda: _FakeA2AService(fake_gateway)
    )
    monkeypatch.setattr(hub_router, "validate_message", lambda payload: [])
    conversation_id = str(uuid4())
    agent_uuid = UUID(agent_id)

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
            json={
                "query": "hi",
                "conversationId": conversation_id,
                "metadata": {},
            },
        ) as stream_resp:
            assert stream_resp.status_code == 200
            assert stream_resp.headers["content-type"].startswith("text/event-stream")
            body = (await stream_resp.aread()).decode("utf-8")
            assert "data:" in body
            assert "event: stream_end" in body

    # Ensure we injected the system-managed Authorization header.
    resolved = fake_gateway.calls[0]["resolved"]
    assert resolved.headers["Authorization"].endswith("secret-token-stream")
    external_binding = await async_db_session.scalar(
        select(ConversationThread).where(
            ConversationThread.user_id == alice.id,
            ConversationThread.id == UUID(conversation_id),
            ConversationThread.external_provider == "opencode",
            ConversationThread.agent_id == agent_uuid,
            ConversationThread.agent_source == "shared",
            ConversationThread.external_session_id == "upstream-stream-1",
        )
    )
    assert external_binding is not None
    assert external_binding.context_id == "ctx-stream-1"


@pytest.mark.asyncio
async def test_admin_replace_allowlist_is_atomic(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    admin = await create_user(
        async_db_session, email="admin_replace_allowlist@example.com", is_superuser=True
    )
    alice = await create_user(
        async_db_session,
        email="alice_replace_allowlist@example.com",
        is_superuser=False,
    )
    bob = await create_user(
        async_db_session, email="bob_replace_allowlist@example.com", is_superuser=False
    )

    async with create_test_client(
        admin_router.router,
        async_session_maker=async_session_maker,
        current_user=admin,
        base_prefix=settings.api_v1_prefix,
    ) as admin_client:
        create_payload = {
            "name": "Replace Allowlist Agent",
            "card_url": "https://example.com/.well-known/agent-card.json",
            "availability_policy": "allowlist",
            "auth_type": "none",
            "enabled": True,
            "tags": [],
            "extra_headers": {},
        }
        create_resp = await admin_client.post(
            f"{settings.api_v1_prefix}/admin/a2a/agents", json=create_payload
        )
        assert create_resp.status_code == 201
        agent_id = create_resp.json()["id"]

        allow_resp = await admin_client.post(
            f"{settings.api_v1_prefix}/admin/a2a/agents/{agent_id}/allowlist",
            json={"email": alice.email},
        )
        assert allow_resp.status_code == 201

        replace_fail_resp = await admin_client.put(
            f"{settings.api_v1_prefix}/admin/a2a/agents/{agent_id}/allowlist:replace",
            json={
                "entries": [
                    {"email": bob.email},
                    {"email": "missing-user@example.com"},
                ]
            },
        )
        assert replace_fail_resp.status_code == 404

        # Atomicity check: failed replace should not mutate existing allowlist.
        list_after_fail = await admin_client.get(
            f"{settings.api_v1_prefix}/admin/a2a/agents/{agent_id}/allowlist"
        )
        assert list_after_fail.status_code == 200
        fail_items = list_after_fail.json()["items"]
        assert len(fail_items) == 1
        assert fail_items[0]["user_id"] == str(alice.id)

        replace_success_resp = await admin_client.put(
            f"{settings.api_v1_prefix}/admin/a2a/agents/{agent_id}/allowlist:replace",
            json={"entries": [{"email": bob.email}]},
        )
        assert replace_success_resp.status_code == 200
        success_items = replace_success_resp.json()["items"]
        assert len(success_items) == 1
        assert success_items[0]["user_id"] == str(bob.id)

        list_after_success = await admin_client.get(
            f"{settings.api_v1_prefix}/admin/a2a/agents/{agent_id}/allowlist"
        )
        assert list_after_success.status_code == 200
        final_items = list_after_success.json()["items"]
        assert len(final_items) == 1
        assert final_items[0]["user_id"] == str(bob.id)


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
        select(A2AAgentCredential).where(A2AAgentCredential.agent_id == agent_id)
    )
    assert credential is None

    allow_entry = await async_db_session.scalar(
        select(HubA2AAgentAllowlistEntry).where(
            HubA2AAgentAllowlistEntry.agent_id == agent_id
        )
    )
    assert allow_entry is None
