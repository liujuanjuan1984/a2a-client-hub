"""Tests for A2A client lifecycle behaviors."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

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
