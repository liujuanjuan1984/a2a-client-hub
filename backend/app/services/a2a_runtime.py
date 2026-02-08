"""
Runtime helpers for building A2A invocation context from user-managed agents.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.secret_vault import SecretVaultNotConfiguredError, user_llm_secret_vault
from app.db.models.a2a_agent import A2AAgent
from app.db.models.a2a_agent_credential import A2AAgentCredential
from app.integrations.a2a_client.service import ResolvedAgent


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
        headers = dict(agent.extra_headers or {})
        token_last4: Optional[str] = None

        if agent.auth_type == "bearer":
            credential = await self._get_credential(
                db, user_id=user_id, agent_id=agent.id
            )
            if credential is None:
                raise A2ARuntimeValidationError("Bearer token is required")
            if not self._vault.is_configured:
                raise A2ARuntimeValidationError("Credential encryption key is missing")
            try:
                decrypted = self._vault.decrypt(credential.encrypted_token)
            except SecretVaultNotConfiguredError as exc:
                raise A2ARuntimeValidationError(str(exc)) from exc

            header_name = (
                agent.auth_header or "Authorization"
            ).strip() or "Authorization"
            scheme = (agent.auth_scheme or "Bearer").strip()
            if scheme:
                headers[header_name] = f"{scheme} {decrypted.value}"
            else:
                headers[header_name] = decrypted.value
            token_last4 = decrypted.last4 or credential.token_last4
        elif agent.auth_type == "none":
            pass
        else:
            raise A2ARuntimeValidationError("Unsupported auth_type")

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
