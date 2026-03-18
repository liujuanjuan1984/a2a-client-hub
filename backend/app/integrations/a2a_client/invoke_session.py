"""Resolution policy and invoke-session models for A2A downstream calls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from a2a.types import AgentCard

    from app.integrations.a2a_client.client import A2AClient
    from app.integrations.a2a_client.service import ResolvedAgent


class AgentResolutionPolicy(str, Enum):
    """How a call should resolve Agent Card metadata before invoke."""

    CACHED_SHARED = "cached_shared"
    FRESH_PROBE = "fresh_probe"
    FRESH_SNAPSHOT = "fresh_snapshot"


class AgentSnapshotSource(str, Enum):
    """How the current snapshot was obtained."""

    SHARED_CACHE = "shared_cache"
    FRESH_FETCH = "fresh_fetch"


class InvokeSessionOwnership(str, Enum):
    """Lifecycle ownership for the invoke session client."""

    SHARED = "shared"
    EPHEMERAL = "ephemeral"


@dataclass(frozen=True, slots=True)
class ResolvedAgentSnapshot:
    """The resolved Agent Card contract for a specific execution window."""

    resolved: "ResolvedAgent"
    agent_card: "AgentCard"
    peer_descriptor: Any
    resolved_at: datetime
    source: AgentSnapshotSource
    card_fetch_timeout: float | None


@dataclass(slots=True)
class A2AInvokeSession:
    """A resolved invoke session bound to one client and one snapshot."""

    client: "A2AClient"
    snapshot: ResolvedAgentSnapshot
    policy: AgentResolutionPolicy
    ownership: InvokeSessionOwnership

    @property
    def is_shared(self) -> bool:
        return self.ownership == InvokeSessionOwnership.SHARED


__all__ = [
    "A2AInvokeSession",
    "AgentResolutionPolicy",
    "AgentSnapshotSource",
    "InvokeSessionOwnership",
    "ResolvedAgentSnapshot",
]
