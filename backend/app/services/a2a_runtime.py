"""
Runtime helpers for building A2A invocation context from user-managed agents.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, cast
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.secret_vault import user_llm_secret_vault
from app.db.models.a2a_agent import A2AAgent
from app.db.models.a2a_agent_credential import A2AAgentCredential
from app.integrations.a2a_client.types import ResolvedAgent
from app.services.runtime_auth import build_resolved_runtime_agent


class A2ARuntimeError(RuntimeError):
    """Base error for A2A runtime building."""


class A2ARuntimeNotFoundError(A2ARuntimeError):
    """Raised when the agent cannot be located."""


class A2ARuntimeValidationError(A2ARuntimeError):
    """Raised when runtime data is invalid or incomplete."""


@dataclass(frozen=True)
class A2ARuntime:
    agent: A2AAgent
    resolved: ResolvedAgent
    token_last4: Optional[str]


class A2ARuntimeBuilder:
    """Builds resolved runtime configuration from stored agent records."""

    def __init__(self) -> None:
        self._vault = user_llm_secret_vault

    async def build(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        agent_id: UUID,
    ) -> A2ARuntime:
        agent = await self._get_agent(db, user_id=user_id, agent_id=agent_id)
        credential = None
        if agent.auth_type == "bearer":
            credential = await self._get_credential(db, agent_id=cast(UUID, agent.id))
        return self.build_from_agent(agent=agent, credential=credential)

    def build_from_agent(
        self,
        *,
        agent: A2AAgent,
        credential: Optional[A2AAgentCredential],
    ) -> A2ARuntime:
        resolved, token_last4 = self.resolve_prefetched(
            name=cast(str, agent.name),
            card_url=cast(str, agent.card_url),
            extra_headers=cast(dict[str, str] | None, agent.extra_headers),
            auth_type=cast(str, agent.auth_type),
            auth_header=cast(str | None, agent.auth_header),
            auth_scheme=cast(str | None, agent.auth_scheme),
            credential=credential,
        )

        return A2ARuntime(agent=agent, resolved=resolved, token_last4=token_last4)

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
            validation_error_cls=A2ARuntimeValidationError,
        )

    async def _get_agent(
        self, db: AsyncSession, *, user_id: UUID, agent_id: UUID
    ) -> A2AAgent:
        stmt = select(A2AAgent).where(
            and_(
                A2AAgent.id == agent_id,
                A2AAgent.user_id == user_id,
                A2AAgent.agent_scope == A2AAgent.SCOPE_PERSONAL,
                A2AAgent.deleted_at.is_(None),
            )
        )
        agent = cast(A2AAgent | None, await db.scalar(stmt))
        if agent is None:
            raise A2ARuntimeNotFoundError("A2A agent not found")
        return agent

    async def _get_credential(
        self, db: AsyncSession, *, agent_id: UUID
    ) -> Optional[A2AAgentCredential]:
        stmt = select(A2AAgentCredential).where(A2AAgentCredential.agent_id == agent_id)
        return cast(A2AAgentCredential | None, await db.scalar(stmt))


a2a_runtime_builder = A2ARuntimeBuilder()

__all__ = [
    "A2ARuntime",
    "A2ARuntimeError",
    "A2ARuntimeNotFoundError",
    "A2ARuntimeValidationError",
    "a2a_runtime_builder",
]
