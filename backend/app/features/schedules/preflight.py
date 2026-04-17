"""Preflight session helpers for scheduled A2A executions."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, AsyncIterator

from app.integrations.a2a_client.invoke_session import (
    A2AInvokeSession,
    AgentResolutionPolicy,
)

if TYPE_CHECKING:
    from app.integrations.a2a_client.gateway import A2AGateway


@asynccontextmanager
async def open_schedule_invoke_session(
    *,
    gateway: "A2AGateway",
    runtime: Any,
) -> AsyncIterator[A2AInvokeSession]:
    """Open a scheduled invoke session bound to a fresh contract snapshot."""

    async with gateway.open_invoke_session(
        resolved=runtime.resolved,
        policy=AgentResolutionPolicy.FRESH_SNAPSHOT,
        card_fetch_timeout=5.0,
    ) as session:
        yield session
