"""Tests for A2A client lifecycle behaviors."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.integrations.a2a_client.client import A2AClient, ClientCacheEntry


@pytest.mark.asyncio
async def test_a2a_client_close_clears_cached_clients_without_closing_transports() -> None:
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
