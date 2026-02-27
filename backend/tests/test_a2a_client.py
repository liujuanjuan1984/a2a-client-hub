"""Tests for A2A client lifecycle behaviors."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from a2a.client.errors import A2AClientHTTPError
from a2a.types import Message, Role, TextPart

from app.integrations.a2a_client.client import A2AClient, ClientCacheEntry


@pytest.mark.asyncio
async def test_a2a_client_close_does_not_close_shared_transport_when_http_client_is_owned() -> (
    None
):
    a2a_client = A2AClient("http://example-agent.internal:24020")
    close_mock = AsyncMock()
    a2a_client._agent_card = Mock()
    a2a_client._clients[True] = ClientCacheEntry(
        config=Mock(),
        client=SimpleNamespace(close=close_mock),
    )

    await a2a_client.close()

    close_mock.assert_not_called()
    assert a2a_client._agent_card is None
    assert a2a_client._clients == {}


@pytest.mark.asyncio
async def test_a2a_client_close_releases_owned_http_client_resources() -> None:
    http_client = AsyncMock()
    transport_close = AsyncMock()
    a2a_client = A2AClient(
        "http://example-agent.internal:24020",
        http_client=http_client,
        owns_http_client=True,
    )
    a2a_client._agent_card = Mock()
    a2a_client._clients[True] = ClientCacheEntry(
        config=Mock(),
        client=SimpleNamespace(close=transport_close),
    )

    await a2a_client.close()

    transport_close.assert_awaited_once()
    http_client.aclose.assert_awaited_once()
    assert a2a_client._agent_card is None
    assert a2a_client._clients == {}


def test_extract_text_from_payload_can_handle_task_like_payload() -> None:
    fake_task_payload = SimpleNamespace(
        artifacts=[
            SimpleNamespace(
                parts=[TextPart(text="Task completed")],
            )
        ]
    )
    text = A2AClient._extract_text_from_payload(fake_task_payload)

    assert text == "Task completed"


def test_extract_text_from_payload_can_handle_history_message() -> None:
    user_message = Message(
        message_id="m1",
        role=Role("user"),
        parts=[TextPart(text="Previous prompt")],
    )
    agent_payload = SimpleNamespace(history=[user_message])

    text = A2AClient._extract_text_from_payload(agent_payload)

    assert text == "Previous prompt"


def test_extract_text_from_payload_can_handle_dict_shape_payload() -> None:
    payload = {
        "status": {
            "message": {
                "parts": [
                    {"text": "Mapping based response"},
                ]
            }
        }
    }

    text = A2AClient._extract_text_from_payload(payload)

    assert text == "Mapping based response"


@pytest.mark.asyncio
async def test_call_agent_falls_back_to_plain_string_without_json_wrapping() -> None:
    class LegacyResponse:
        def __str__(self) -> str:
            return "Task(artifacts=[...])"

    class FakeClient:
        async def send_message(self, *_args, **_kwargs):
            yield LegacyResponse()

    a2a_client = A2AClient("http://example-agent.internal:24020")
    a2a_client._get_client = AsyncMock(return_value=FakeClient())

    result = await a2a_client.call_agent("hello")

    assert result["success"] is True
    assert result["content"] == "Task(artifacts=[...])"


@pytest.mark.asyncio
async def test_cancel_task_returns_success_for_valid_request() -> None:
    class FakeClient:
        async def cancel_task(self, request):
            assert request.id == "task-1"
            return {"id": request.id}

    a2a_client = A2AClient("http://example-agent.internal:24020")
    a2a_client._get_client = AsyncMock(return_value=FakeClient())

    result = await a2a_client.cancel_task(" task-1 ")

    assert result["success"] is True
    assert result["task_id"] == "task-1"
    assert result["task"] == {"id": "task-1"}


@pytest.mark.asyncio
async def test_cancel_task_maps_http_status_error_codes() -> None:
    class FakeClient:
        async def cancel_task(self, _request):
            raise A2AClientHTTPError(404, "Task not found")

    a2a_client = A2AClient("http://example-agent.internal:24020")
    a2a_client._get_client = AsyncMock(return_value=FakeClient())

    result = await a2a_client.cancel_task("task-missing")

    assert result["success"] is False
    assert result["error_code"] == "task_not_found"


@pytest.mark.asyncio
async def test_cancel_task_rejects_blank_task_id() -> None:
    a2a_client = A2AClient("http://example-agent.internal:24020")

    result = await a2a_client.cancel_task("  ")

    assert result["success"] is False
    assert result["error_code"] == "invalid_task_id"
