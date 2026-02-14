"""
Runtime helpers for building A2A invocation context from user-managed agents.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.secret_vault import user_llm_secret_vault
from app.db.models.a2a_agent import A2AAgent
from app.db.models.a2a_agent_credential import A2AAgentCredential
from app.integrations.a2a_client.service import ResolvedAgent
from app.services.runtime_auth import resolve_runtime_auth_headers


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
            credential = await self._get_credential(
                db, user_id=user_id, agent_id=agent.id
            )
        headers, token_last4 = resolve_runtime_auth_headers(
            headers=dict(agent.extra_headers or {}),
            auth_type=agent.auth_type,
            auth_header=agent.auth_header,
            auth_scheme=agent.auth_scheme,
            credential=credential,
            vault=self._vault,
            validation_error_cls=A2ARuntimeValidationError,
        )

        resolved = ResolvedAgent(
            name=agent.name,
            url=agent.card_url,
            description=None,
            metadata={},
            headers=headers,
        )

        return A2ARuntime(agent=agent, resolved=resolved, token_last4=token_last4)

    async def _get_agent(
        self, db: AsyncSession, *, user_id: UUID, agent_id: UUID
    ) -> A2AAgent:
        stmt = select(A2AAgent).where(
            and_(
                A2AAgent.id == agent_id,
                A2AAgent.user_id == user_id,
                A2AAgent.deleted_at.is_(None),
            )
        )
        agent = await db.scalar(stmt)
        if agent is None:
            raise A2ARuntimeNotFoundError("A2A agent not found")
        return agent

    async def _get_credential(
        self, db: AsyncSession, *, user_id: UUID, agent_id: UUID
    ) -> Optional[A2AAgentCredential]:
        stmt = select(A2AAgentCredential).where(
            and_(
                A2AAgentCredential.user_id == user_id,
                A2AAgentCredential.agent_id == agent_id,
                A2AAgentCredential.deleted_at.is_(None),
            )
        )
        return await db.scalar(stmt)


a2a_runtime_builder = A2ARuntimeBuilder()

__all__ = [
    "A2ARuntime",
    "A2ARuntimeError",
    "A2ARuntimeNotFoundError",
    "A2ARuntimeValidationError",
    "a2a_runtime_builder",
]
