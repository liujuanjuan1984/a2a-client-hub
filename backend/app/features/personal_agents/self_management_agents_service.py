"""Shared self-management agents service built on top of personal-agent services."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User
from app.features.personal_agents.service import (
    A2AAgentHealthCheckItemRecord,
    A2AAgentHealthCheckSummaryRecord,
    A2AAgentListCounts,
    A2AAgentRecord,
    a2a_agent_service,
)
from app.features.self_management_shared.capability_catalog import (
    SELF_AGENTS_CHECK_HEALTH,
    SELF_AGENTS_CHECK_HEALTH_ALL,
    SELF_AGENTS_CREATE,
    SELF_AGENTS_DELETE,
    SELF_AGENTS_GET,
    SELF_AGENTS_LIST,
    SELF_AGENTS_UPDATE_CONFIG,
)
from app.features.self_management_shared.tool_gateway import SelfManagementToolGateway


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

    async def check_agent_health(
        self,
        *,
        db: AsyncSession,
        gateway: SelfManagementToolGateway,
        current_user: User,
        agent_id: UUID,
        force: bool = True,
    ) -> tuple[A2AAgentHealthCheckSummaryRecord, list[A2AAgentHealthCheckItemRecord]]:
        del db
        result = await gateway.execute(
            operation=SELF_AGENTS_CHECK_HEALTH,
            resource_id=str(agent_id),
            handler=lambda: a2a_agent_service.check_agents_health(
                user_id=self._user_id(current_user),
                agent_id=agent_id,
                force=force,
            ),
        )
        return result.result

    async def check_all_agents_health(
        self,
        *,
        db: AsyncSession,
        gateway: SelfManagementToolGateway,
        current_user: User,
        force: bool = False,
    ) -> tuple[A2AAgentHealthCheckSummaryRecord, list[A2AAgentHealthCheckItemRecord]]:
        del db
        result = await gateway.execute(
            operation=SELF_AGENTS_CHECK_HEALTH_ALL,
            handler=lambda: a2a_agent_service.check_agents_health(
                user_id=self._user_id(current_user),
                force=force,
            ),
        )
        return result.result

    async def create_agent(
        self,
        *,
        db: AsyncSession,
        gateway: SelfManagementToolGateway,
        current_user: User,
        name: str,
        card_url: str,
        auth_type: str,
        auth_header: str | None = None,
        auth_scheme: str | None = None,
        enabled: bool = True,
        tags: list[str] | None = None,
        extra_headers: dict[str, str] | None = None,
        invoke_metadata_defaults: dict[str, str] | None = None,
        token: str | None = None,
        basic_username: str | None = None,
        basic_password: str | None = None,
    ) -> A2AAgentRecord:
        result = await gateway.execute(
            operation=SELF_AGENTS_CREATE,
            handler=lambda: a2a_agent_service.create_agent(
                db,
                user_id=self._user_id(current_user),
                name=name,
                card_url=card_url,
                auth_type=auth_type,
                auth_header=auth_header,
                auth_scheme=auth_scheme,
                enabled=enabled,
                tags=tags,
                extra_headers=extra_headers,
                invoke_metadata_defaults=invoke_metadata_defaults,
                token=token,
                basic_username=basic_username,
                basic_password=basic_password,
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
        card_url: str | None = None,
        auth_type: str | None = None,
        auth_header: str | None = None,
        auth_scheme: str | None = None,
        enabled: bool | None = None,
        tags: list[str] | None = None,
        extra_headers: dict[str, str] | None = None,
        invoke_metadata_defaults: dict[str, str] | None = None,
        token: str | None = None,
        basic_username: str | None = None,
        basic_password: str | None = None,
    ) -> A2AAgentRecord:
        result = await gateway.execute(
            operation=SELF_AGENTS_UPDATE_CONFIG,
            resource_id=str(agent_id),
            handler=lambda: a2a_agent_service.update_agent(
                db,
                user_id=self._user_id(current_user),
                agent_id=agent_id,
                name=name,
                card_url=card_url,
                auth_type=auth_type,
                auth_header=auth_header,
                auth_scheme=auth_scheme,
                enabled=enabled,
                tags=tags,
                extra_headers=extra_headers,
                invoke_metadata_defaults=invoke_metadata_defaults,
                token=token,
                basic_username=basic_username,
                basic_password=basic_password,
            ),
        )
        return result.result

    async def delete_agent(
        self,
        *,
        db: AsyncSession,
        gateway: SelfManagementToolGateway,
        current_user: User,
        agent_id: UUID,
    ) -> None:
        await gateway.execute(
            operation=SELF_AGENTS_DELETE,
            resource_id=str(agent_id),
            handler=lambda: a2a_agent_service.delete_agent(
                db,
                user_id=self._user_id(current_user),
                agent_id=agent_id,
            ),
        )


self_management_agents_service = SelfManagementAgentsService()


__all__ = [
    "SelfManagementAgentsService",
    "self_management_agents_service",
]
