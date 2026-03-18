"""Preflight diagnostics for scheduled A2A executions."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, AsyncIterator

from app.utils.async_cleanup import await_cancel_safe

if TYPE_CHECKING:
    from app.integrations.a2a_client.client import A2AClient
    from app.integrations.a2a_client.gateway import A2AGateway


@dataclass
class ScheduleAgentCardPreflightSnapshot:
    client: "A2AClient"
    agent_card: Any


@asynccontextmanager
async def open_schedule_agent_card_preflight_snapshot(
    *,
    gateway: "A2AGateway",
    runtime: Any,
) -> AsyncIterator[ScheduleAgentCardPreflightSnapshot]:
    """Open a one-off preflight snapshot bound to the scheduled invoke.

    This is intentionally not a full upstream health check. It only confirms
    that the latest Agent Card is reachable within a short timeout and that the
    current client can still resolve a compatible transport from that card.

    The returned temporary client is warmed with the exact same Agent Card and
    peer descriptor that the scheduled invoke will use. This avoids mutating the
    shared client cache while keeping preflight and invoke on the same contract
    snapshot.
    """
    client = gateway.create_temporary_client(
        resolved=runtime.resolved,
        card_fetch_timeout=5.0,
    )
    try:
        agent_card = await gateway.fetch_agent_card_detail(
            resolved=runtime.resolved,
            client=client,
            raise_on_failure=True,
        )
        yield ScheduleAgentCardPreflightSnapshot(
            client=client,
            agent_card=agent_card,
        )
    finally:
        await await_cancel_safe(client.close())


__all__ = [
    "ScheduleAgentCardPreflightSnapshot",
    "open_schedule_agent_card_preflight_snapshot",
]
