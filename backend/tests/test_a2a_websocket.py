from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_async_db, get_ws_ticket_user
from app.core.config import settings
from app.db.models.user import User
from app.main import app
from app.services.ws_ticket_service import WsTicketNotFoundError, ws_ticket_service


@pytest.fixture
def mock_user():
    return User(id=uuid4(), email="test@example.com", name="Test User")


async def _override_get_async_db():
    yield MagicMock()


def test_invoke_agent_ws_auth_required():
    """Verify that WS connection fails without a ticket."""
    client = TestClient(app)
    # The get_ws_ticket_user dependency will raise WebSocketException if ticket is missing
    app.dependency_overrides[get_async_db] = _override_get_async_db
    try:
        with pytest.raises(Exception):
            with client.websocket_connect(
                f"{settings.api_v1_prefix}/me/a2a/agents/{uuid4()}/invoke/ws",
                headers={"origin": "http://localhost:5173"},
            ):
                pass
    finally:
        app.dependency_overrides.clear()


def test_invoke_agent_ws_invalid_token(monkeypatch):
    """Verify that WS connection fails with an invalid ticket."""

    async def mock_consume_ticket(*args, **kwargs):
        raise WsTicketNotFoundError("Invalid or expired ticket")

    monkeypatch.setattr(ws_ticket_service, "consume_ticket", mock_consume_ticket)
    client = TestClient(app)
    app.dependency_overrides[get_async_db] = _override_get_async_db
    try:
        with pytest.raises(Exception):
            with client.websocket_connect(
                f"{settings.api_v1_prefix}/me/a2a/agents/{uuid4()}/invoke/ws?ticket=invalid",
                headers={"origin": "http://localhost:5173"},
            ):
                pass
    finally:
        app.dependency_overrides.clear()


def test_invoke_agent_ws_success(monkeypatch, mock_user):
    """Verify successful WS invocation and streaming."""
    # 1. Override the user dependency
    app.dependency_overrides[get_async_db] = _override_get_async_db
    app.dependency_overrides[get_ws_ticket_user] = lambda: mock_user

    # 2. Mock the A2A service and gateway
    mock_gateway = MagicMock()

    class MockMessage:
        def model_dump(self, **kwargs):
            return {"content": "Hello from WS"}

    async def mock_stream(**kwargs):
        yield MockMessage()

    mock_gateway.stream = mock_stream

    mock_service = MagicMock()
    mock_service.gateway = mock_gateway

    monkeypatch.setattr(
        "app.api.routers.a2a_agents.get_a2a_service", lambda: mock_service
    )
    # Also need to mock a2a_runtime_builder
    mock_runtime = MagicMock()
    mock_runtime.resolved.url = "http://agent"
    mock_runtime.resolved.name = "TestAgent"

    async def mock_build(*args, **kwargs):
        return mock_runtime

    monkeypatch.setattr(
        "app.api.routers.a2a_agents.a2a_runtime_builder.build", mock_build
    )

    # Mock validate_message to return empty list
    monkeypatch.setattr("app.api.routers.a2a_agents.validate_message", lambda x: [])

    client = TestClient(app)
    try:
        with client.websocket_connect(
            f"{settings.api_v1_prefix}/me/a2a/agents/{uuid4()}/invoke/ws?ticket=mock",
            headers={"origin": "http://localhost:5173"},
        ) as websocket:
            # Send the request
            websocket.send_json({"query": "ping"})

            # Receive response
            resp1 = websocket.receive_json()
            assert resp1["content"] == "Hello from WS"

            # Receive stream_end
            resp2 = websocket.receive_json()
            assert resp2["event"] == "stream_end"
    finally:
        app.dependency_overrides.clear()
