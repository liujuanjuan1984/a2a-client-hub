"""Shared self-management agents service built on top of personal-agent services."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User
from app.features.agents_shared.capability_catalog import (
    SELF_AGENTS_GET,
    SELF_AGENTS_LIST,
    SELF_AGENTS_UPDATE_CONFIG,
)
from app.features.agents_shared.tool_gateway import SelfManagementToolGateway
from app.features.personal_agents.service import (
    A2AAgentListCounts,
    A2AAgentRecord,
    a2a_agent_service,
)


class SelfManagementAgentsService:
    """Shared agent operations for REST, CLI, and built-in agent entry points."""

    def _user_id(self, user: User) -> UUID:
        user_id = cast(UUID | None, user.id)
        if user_id is None:
            raise ValueError("Authenticated user id is required")
        return user_id

    async def list_agents(
        self,
        *,
        db: AsyncSession,
        gateway: SelfManagementToolGateway,
        current_user: User,
        page: int,
        size: int,
        health_bucket: str = "all",
    ) -> tuple[list[A2AAgentRecord], int, A2AAgentListCounts]:
        result = await gateway.execute(
            operation=SELF_AGENTS_LIST,
            handler=lambda: a2a_agent_service.list_agents(
                db,
                user_id=self._user_id(current_user),
                page=page,
                size=size,
                health_bucket=health_bucket,
            ),
        )
        return result.result

    async def get_agent(
        self,
        *,
        db: AsyncSession,
        gateway: SelfManagementToolGateway,
        current_user: User,
        agent_id: UUID,
    ) -> A2AAgentRecord:
        result = await gateway.execute(
            operation=SELF_AGENTS_GET,
            resource_id=str(agent_id),
            handler=lambda: a2a_agent_service.get_agent_record(
                db,
                user_id=self._user_id(current_user),
                agent_id=agent_id,
            ),
        )
        return result.result

    async def update_config(
        self,
        *,
        db: AsyncSession,
        gateway: SelfManagementToolGateway,
        current_user: User,
        agent_id: UUID,
        name: str | None = None,
        enabled: bool | None = None,
        tags: list[str] | None = None,
        extra_headers: dict[str, str] | None = None,
        invoke_metadata_defaults: dict[str, str] | None = None,
    ) -> A2AAgentRecord:
        result = await gateway.execute(
            operation=SELF_AGENTS_UPDATE_CONFIG,
            resource_id=str(agent_id),
            handler=lambda: a2a_agent_service.update_agent(
                db,
                user_id=self._user_id(current_user),
                agent_id=agent_id,
                name=name,
                enabled=enabled,
                tags=tags,
                extra_headers=extra_headers,
                invoke_metadata_defaults=invoke_metadata_defaults,
            ),
        )
        return result.result


self_management_agents_service = SelfManagementAgentsService()


__all__ = [
    "SelfManagementAgentsService",
    "self_management_agents_service",
]
