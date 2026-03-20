"""Runtime helpers for building A2A invocation context from hub agents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.secret_vault import hub_a2a_secret_vault
from app.db.models.a2a_agent import A2AAgent
from app.db.models.a2a_agent_credential import A2AAgentCredential
from app.integrations.a2a_client.types import ResolvedAgent
from app.services.runtime_auth import build_resolved_runtime_agent


class HubA2ARuntimeError(RuntimeError):
    """Base error for hub A2A runtime building."""


class HubA2ARuntimeNotFoundError(HubA2ARuntimeError):
    """Raised when the agent cannot be located or is not visible to the user."""


class HubA2ARuntimeValidationError(HubA2ARuntimeError):
    """Raised when runtime data is invalid or incomplete."""


@dataclass(frozen=True)
class HubA2ARuntime:
    agent_id: UUID
    agent_name: str
    agent_url: str
    resolved: ResolvedAgent


class HubA2ARuntimeBuilder:
    """Builds resolved runtime configuration from stored hub agent records."""

    def __init__(self) -> None:
        self._vault = hub_a2a_secret_vault

    async def build(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        agent_id: UUID,
    ) -> HubA2ARuntime:
        from app.features.hub_agents.service import (
            HubA2AAgentNotFoundError,
            hub_a2a_agent_service,
        )

        try:
            agent = await hub_a2a_agent_service.ensure_visible_for_user(
                db, user_id=user_id, agent_id=agent_id
            )
        except HubA2AAgentNotFoundError as exc:
            raise HubA2ARuntimeNotFoundError(str(exc)) from exc

        credential = None
        if agent.auth_type == "bearer":
            credential = await self._get_credential(db, agent_id=cast(UUID, agent.id))
        return self.build_from_agent(agent=agent, credential=credential)

    def build_from_agent(
        self,
        *,
        agent: A2AAgent,
        credential: Optional[A2AAgentCredential],
    ) -> HubA2ARuntime:
        resolved, _ = self.resolve_prefetched(
            name=cast(str, agent.name),
            card_url=cast(str, agent.card_url),
            extra_headers=cast(dict[str, str] | None, agent.extra_headers),
            auth_type=cast(str, agent.auth_type),
            auth_header=cast(str | None, agent.auth_header),
            auth_scheme=cast(str | None, agent.auth_scheme),
            credential=credential,
        )

        return HubA2ARuntime(
            agent_id=cast(UUID, agent.id),
            agent_name=cast(str, agent.name),
            agent_url=cast(str, agent.card_url),
            resolved=resolved,
        )

    def resolve_prefetched(
        self,
        *,
        name: str,
        card_url: str,
        extra_headers: dict[str, str] | None,
        auth_type: str,
        auth_header: str | None,
        auth_scheme: str | None,
        credential: Optional[A2AAgentCredential],
    ) -> tuple[ResolvedAgent, Optional[str]]:
        return build_resolved_runtime_agent(
            name=name,
            card_url=card_url,
            extra_headers=extra_headers,
            auth_type=auth_type,
            auth_header=auth_header,
            auth_scheme=auth_scheme,
            credential=credential,
            vault=self._vault,
            validation_error_cls=HubA2ARuntimeValidationError,
        )

    async def _get_credential(
        self, db: AsyncSession, *, agent_id: UUID
    ) -> Optional[A2AAgentCredential]:
        stmt = select(A2AAgentCredential).where(A2AAgentCredential.agent_id == agent_id)
        return cast(A2AAgentCredential | None, await db.scalar(stmt))


hub_a2a_runtime_builder = HubA2ARuntimeBuilder()

__all__ = [
    "HubA2ARuntime",
    "HubA2ARuntimeError",
    "HubA2ARuntimeNotFoundError",
    "HubA2ARuntimeValidationError",
    "hub_a2a_runtime_builder",
]
