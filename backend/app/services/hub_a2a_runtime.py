"""Runtime helpers for building A2A invocation context from hub agents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.secret_vault import SecretVaultNotConfiguredError, hub_a2a_secret_vault
from app.db.models.hub_a2a_agent_credential import HubA2AAgentCredential
from app.integrations.a2a_client.service import ResolvedAgent
from app.services.hub_a2a_agents import HubA2AAgentNotFoundError, hub_a2a_agent_service
from app.utils.auth_headers import build_auth_header_pair


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
        try:
            agent = await hub_a2a_agent_service.ensure_visible_for_user(
                db, user_id=user_id, agent_id=agent_id
            )
        except HubA2AAgentNotFoundError as exc:
            raise HubA2ARuntimeNotFoundError(str(exc)) from exc

        headers = dict(agent.extra_headers or {})

        if agent.auth_type == "bearer":
            credential = await self._get_credential(db, agent_id=agent.id)
            if credential is None:
                raise HubA2ARuntimeValidationError("Bearer token is required")
            if not self._vault.is_configured:
                raise HubA2ARuntimeValidationError(
                    "Credential encryption key is missing"
                )
            try:
                decrypted = self._vault.decrypt(credential.encrypted_token)
            except SecretVaultNotConfiguredError as exc:
                raise HubA2ARuntimeValidationError(str(exc)) from exc

            header_name, header_value = build_auth_header_pair(
                auth_header=agent.auth_header,
                auth_scheme=agent.auth_scheme,
                token=decrypted.value,
            )
            headers[header_name] = header_value
        elif agent.auth_type == "none":
            pass
        else:
            raise HubA2ARuntimeValidationError("Unsupported auth_type")

        resolved = ResolvedAgent(
            name=agent.name,
            url=agent.card_url,
            description=None,
            metadata={},
            headers=headers,
        )

        return HubA2ARuntime(
            agent_id=agent.id,
            agent_name=agent.name,
            agent_url=agent.card_url,
            resolved=resolved,
        )

    async def _get_credential(
        self, db: AsyncSession, *, agent_id: UUID
    ) -> Optional[HubA2AAgentCredential]:
        stmt = select(HubA2AAgentCredential).where(
            HubA2AAgentCredential.agent_id == agent_id
        )
        return await db.scalar(stmt)


hub_a2a_runtime_builder = HubA2ARuntimeBuilder()

__all__ = [
    "HubA2ARuntime",
    "HubA2ARuntimeError",
    "HubA2ARuntimeNotFoundError",
    "HubA2ARuntimeValidationError",
    "hub_a2a_runtime_builder",
]
