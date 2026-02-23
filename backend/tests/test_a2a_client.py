"""Tests for A2A client lifecycle behaviors."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from a2a.types import Message, Role, TextPart

from app.integrations.a2a_client.client import A2AClient, ClientCacheEntry


@pytest.mark.asyncio
async def test_a2a_client_close_does_not_close_shared_transport_when_http_client_is_owned() -> None:
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
