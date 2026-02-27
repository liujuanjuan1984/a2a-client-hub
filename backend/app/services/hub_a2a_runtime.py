"""Runtime helpers for building A2A invocation context from hub agents."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.secret_vault import hub_a2a_secret_vault
from app.integrations.a2a_client.service import ResolvedAgent
from app.services.hub_a2a_agents import HubA2AAgentNotFoundError, hub_a2a_agent_service
from app.services.runtime_auth import build_resolved_runtime_agent
from app.services.runtime_common import BaseA2ARuntimeBuilder


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


class HubA2ARuntimeBuilder(BaseA2ARuntimeBuilder):
    """Builds resolved runtime configuration from stored hub agent records."""

    def __init__(self) -> None:
        super().__init__(
            vault=hub_a2a_secret_vault,
            validation_error_cls=HubA2ARuntimeValidationError,
        )

    async def build(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        agent_id: UUID,
    ) -> HubA2ARuntime:
        try:
            agent = await hub_a2a_agent_service.ensure_visible_for_user(
                db, user_id=user_id, agent_id=agent_id
            )
        except HubA2AAgentNotFoundError as exc:
            raise HubA2ARuntimeNotFoundError(str(exc)) from exc

        credential = None
        if agent.auth_type == "bearer":
            credential = await self._get_credential(db, agent_id=agent.id)
        resolved, _ = build_resolved_runtime_agent(
            name=agent.name,
            card_url=agent.card_url,
            extra_headers=agent.extra_headers,
            auth_type=agent.auth_type,
            auth_header=agent.auth_header,
            auth_scheme=agent.auth_scheme,
            credential=credential,
            vault=self._vault,
            validation_error_cls=self._validation_error_cls,
        )

        return HubA2ARuntime(
            agent_id=agent.id,
            agent_name=agent.name,
            agent_url=agent.card_url,
            resolved=resolved,
        )


hub_a2a_runtime_builder = HubA2ARuntimeBuilder()

__all__ = [
    "HubA2ARuntime",
    "HubA2ARuntimeError",
    "HubA2ARuntimeNotFoundError",
    "HubA2ARuntimeValidationError",
    "hub_a2a_runtime_builder",
]
