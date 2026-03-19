"""Resolution helpers that build snapshots from A2A clients."""

from __future__ import annotations

from typing import Any

from app.integrations.a2a_client.invoke_session import (
    AgentSnapshotSource,
    ResolvedAgentSnapshot,
)
from app.utils.timezone_util import utc_now


class A2AResolutionService:
    """Resolve an invoke snapshot from one client and one policy source."""

    async def resolve_snapshot(
        self,
        *,
        client: Any,
        resolved: Any,
        source: AgentSnapshotSource,
        card_fetch_timeout: float | None,
    ) -> ResolvedAgentSnapshot:
        agent_card, peer_descriptor = await client.get_agent_resolution()
        return ResolvedAgentSnapshot(
            resolved=resolved,
            agent_card=agent_card,
            peer_descriptor=peer_descriptor,
            resolved_at=utc_now(),
            source=source,
            card_fetch_timeout=card_fetch_timeout,
        )


__all__ = ["A2AResolutionService"]
