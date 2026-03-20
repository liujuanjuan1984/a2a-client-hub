from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import WebSocket
from fastapi.testclient import TestClient

from app.api.deps import get_async_db, get_ws_ticket_user_hub
from app.core.config import settings
from app.db.models.user import User
from app.main import app
from app.services.ws_ticket_service import WsTicketNotFoundError, ws_ticket_service


@pytest.fixture
def mock_user():
    return User(id=uuid4(), email="hub-ws@example.com", name="Hub WS User")


async def _override_get_async_db():
    yield MagicMock()


def test_invoke_hub_agent_ws_auth_required():
    """Verify that hub WS connection fails without a ticket."""
    client = TestClient(app)
    app.dependency_overrides[get_async_db] = _override_get_async_db
    try:
        with pytest.raises(Exception):
            with client.websocket_connect(
                f"{settings.api_v1_prefix}/a2a/agents/{uuid4()}/invoke/ws",
                headers={"origin": "http://localhost:5173"},
            ):
                pass
    finally:
        app.dependency_overrides.clear()


def test_invoke_hub_agent_ws_invalid_token(monkeypatch):
    """Verify that hub WS connection fails with an invalid ticket."""

    async def mock_consume_ticket(*args, **kwargs):
        raise WsTicketNotFoundError("Invalid or expired ticket")

    monkeypatch.setattr(ws_ticket_service, "consume_ticket", mock_consume_ticket)
    client = TestClient(app)
    app.dependency_overrides[get_async_db] = _override_get_async_db
    try:
        with pytest.raises(Exception):
            with client.websocket_connect(
                f"{settings.api_v1_prefix}/a2a/agents/{uuid4()}/invoke/ws",
                headers={"origin": "http://localhost:5173"},
                subprotocols=["a" * settings.ws_ticket_length],
            ):
                pass
    finally:
        app.dependency_overrides.clear()


def test_invoke_hub_agent_ws_success(monkeypatch, mock_user):
    """Verify successful hub WS invocation and streaming."""
    ticket = "mock-ticket-length-48-chars-minimum-1234567890"

    async def _override_ws_ticket_user_hub(websocket: WebSocket):
        websocket.state.selected_subprotocol = None
        return mock_user

    app.dependency_overrides[get_async_db] = _override_get_async_db
    app.dependency_overrides[get_ws_ticket_user_hub] = _override_ws_ticket_user_hub

    mock_gateway = MagicMock()

    class MockMessage:
        def model_dump(self, **kwargs):
            return {"content": "Hello from Hub WS"}

    async def mock_stream(**kwargs):
        yield MockMessage()

    mock_gateway.stream = mock_stream
    mock_service = MagicMock()
    mock_service.gateway = mock_gateway
    monkeypatch.setattr(
        "app.features.hub_agents.router.get_a2a_service", lambda: mock_service
    )

    mock_runtime = MagicMock()
    mock_runtime.resolved.url = "http://hub-agent"
    mock_runtime.resolved.name = "HubAgent"

    async def mock_build(*args, **kwargs):
        return mock_runtime

    monkeypatch.setattr(
        "app.features.hub_agents.router.hub_a2a_runtime_builder.build", mock_build
    )
    monkeypatch.setattr("app.features.hub_agents.router.validate_message", lambda x: [])

    client = TestClient(app)
    try:
        with client.websocket_connect(
            f"{settings.api_v1_prefix}/a2a/agents/{uuid4()}/invoke/ws",
            headers={"origin": "http://localhost:5173"},
            subprotocols=[ticket],
        ) as websocket:
            assert websocket.accepted_subprotocol is None
            websocket.send_json({"query": "ping"})

            resp1 = websocket.receive_json()
            assert resp1["content"] == "Hello from Hub WS"

            resp2 = websocket.receive_json()
            assert resp2["event"] == "stream_end"
    finally:
        app.dependency_overrides.clear()


def test_invoke_hub_agent_ws_invalid_conversation_id_returns_error_event(
    monkeypatch, mock_user
):
    """Verify hub WS preflight errors use the unified error event envelope."""
    app.dependency_overrides[get_async_db] = _override_get_async_db
    app.dependency_overrides[get_ws_ticket_user_hub] = lambda: mock_user

    mock_runtime = MagicMock()
    mock_runtime.resolved.url = "http://hub-agent"
    mock_runtime.resolved.name = "HubAgent"

    async def mock_build(*args, **kwargs):
        return mock_runtime

    monkeypatch.setattr(
        "app.features.hub_agents.router.hub_a2a_runtime_builder.build", mock_build
    )

    client = TestClient(app)
    try:
        with client.websocket_connect(
            f"{settings.api_v1_prefix}/a2a/agents/{uuid4()}/invoke/ws",
            headers={"origin": "http://localhost:5173"},
            subprotocols=["mock-ticket-length-48-chars-minimum-1234567890"],
        ) as websocket:
            websocket.send_json({"query": "ping", "conversationId": "invalid"})
            error_event = websocket.receive_json()
            assert error_event["event"] == "error"
            assert error_event["data"]["error_code"] == "invalid_conversation_id"
            assert error_event["data"]["message"] == "invalid_conversation_id"
    finally:
        app.dependency_overrides.clear()
