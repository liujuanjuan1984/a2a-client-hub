"""Shared self-management sessions service built on top of session domain services."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User
from app.features.agents_shared.capability_catalog import (
    SELF_SESSIONS_GET,
    SELF_SESSIONS_LIST,
)
from app.features.agents_shared.tool_gateway import SelfManagementToolGateway
from app.features.sessions.common import SessionSource
from app.features.sessions.service import session_hub_service


class SelfManagementSessionsService:
    """Shared session operations for REST, CLI, and built-in agent entry points."""

    def _user_id(self, user: User) -> UUID:
        user_id = cast(UUID | None, user.id)
        if user_id is None:
            raise ValueError("Authenticated user id is required")
        return user_id

    async def list_sessions(
        self,
        *,
        db: AsyncSession,
        gateway: SelfManagementToolGateway,
        current_user: User,
        page: int,
        size: int,
        source: SessionSource | None = None,
        agent_id: UUID | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any], bool]:
        result = await gateway.execute(
            operation=SELF_SESSIONS_LIST,
            handler=lambda: session_hub_service.list_sessions(
                db,
                user_id=self._user_id(current_user),
                page=page,
                size=size,
                source=source,
                agent_id=agent_id,
            ),
        )
        return result.result

    async def get_session(
        self,
        *,
        db: AsyncSession,
        gateway: SelfManagementToolGateway,
        current_user: User,
        conversation_id: str,
    ) -> dict[str, Any]:
        result = await gateway.execute(
            operation=SELF_SESSIONS_GET,
            resource_id=conversation_id,
            handler=lambda: session_hub_service.get_session(
                db,
                user_id=self._user_id(current_user),
                conversation_id=conversation_id,
            ),
        )
        session_item, _db_mutated = result.result
        return session_item


self_management_sessions_service = SelfManagementSessionsService()


__all__ = [
    "SelfManagementSessionsService",
    "self_management_sessions_service",
]
