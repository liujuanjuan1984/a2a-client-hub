from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.core.config import settings
from app.features.personal_agents import router as personal_router
from app.features.personal_agents.service import a2a_agent_service
from tests.support.api_utils import create_test_client
from tests.support.utils import create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class _FakeGateway:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.invoke_response: dict[str, Any] = {"success": True, "content": "ok"}
        self.stream_events: list[dict[str, Any]] = [{"content": "ok"}]

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

    async def stream(
        self, *, session=None, resolved, query: str, context_id=None, metadata=None
    ):
        self.calls.append(
            {
                "session": session,
                "resolved": resolved,
                "query": query,
                "context_id": context_id,
                "metadata": metadata,
                "stream": True,
            }
        )

        class _MockMessage:
            def __init__(self, payload: dict[str, Any]) -> None:
                self._payload = payload

            def model_dump(self, **kwargs):
                return dict(self._payload)

        for event_payload in self.stream_events:
            yield _MockMessage(event_payload)


class _FakeA2AService:
    def __init__(self, gateway: _FakeGateway) -> None:
        self.gateway = gateway


@pytest.mark.asyncio
async def test_personal_agent_http_invoke_works_with_dependency_injected_db(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])
    user = await create_user(async_db_session, email="personal-http@example.com")
    record = await a2a_agent_service.create_agent(
        async_db_session,
        user_id=user.id,
        name="Personal HTTP Agent",
        card_url="https://example.com/.well-known/agent-card.json",
        auth_type="none",
        enabled=True,
        tags=[],
        extra_headers={},
    )
    fake_gateway = _FakeGateway()
    monkeypatch.setattr(
        personal_router, "get_a2a_service", lambda: _FakeA2AService(fake_gateway)
    )

    async with create_test_client(
        personal_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as client:
        response = await client.post(
            f"{settings.api_v1_prefix}/me/a2a/agents/{record.id}/invoke",
            json={"query": "hello", "metadata": {}},
        )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert len(fake_gateway.calls) == 1


@pytest.mark.asyncio
async def test_personal_agent_sse_invoke_streams_with_dependency_injected_db(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])
    user = await create_user(async_db_session, email="personal-sse@example.com")
    record = await a2a_agent_service.create_agent(
        async_db_session,
        user_id=user.id,
        name="Personal Stream Agent",
        card_url="https://example.com/.well-known/agent-card.json",
        auth_type="none",
        enabled=True,
        tags=[],
        extra_headers={},
    )
    fake_gateway = _FakeGateway()
    fake_gateway.stream_events = [
        {
            "content": "ok",
            "contextId": f"ctx-{uuid4()}",
            "metadata": {"provider": "opencode", "externalSessionId": f"ext-{uuid4()}"},
        }
    ]
    monkeypatch.setattr(
        personal_router, "get_a2a_service", lambda: _FakeA2AService(fake_gateway)
    )
    monkeypatch.setattr(personal_router, "validate_message", lambda payload: [])

    async with create_test_client(
        personal_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as client:
        async with client.stream(
            "POST",
            f"{settings.api_v1_prefix}/me/a2a/agents/{record.id}/invoke",
            params={"stream": "true"},
            json={
                "query": "hello",
                "conversationId": str(uuid4()),
                "metadata": {},
            },
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            body = (await response.aread()).decode("utf-8")
            assert "data:" in body
            assert "event: stream_end" in body

    assert len(fake_gateway.calls) == 1
    assert fake_gateway.calls[0]["stream"] is True
