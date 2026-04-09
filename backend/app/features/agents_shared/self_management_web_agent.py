"""Runtime helpers for self-management web built-in agent entry points."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User
from app.features.agents_shared.actor_context import (
    SelfManagementActorContext,
    SelfManagementActorType,
    build_self_management_actor_context,
)
from app.features.agents_shared.self_management_tool_contract import (
    SelfManagementToolDefinition,
    list_self_management_tool_definitions,
)
from app.features.agents_shared.self_management_toolkit import SelfManagementToolkit
from app.features.agents_shared.tool_gateway import (
    SelfManagementSurface,
    SelfManagementToolGateway,
)


@dataclass(frozen=True)
class SelfManagementWebAgentRuntime:
    """Resolved web-agent runtime for self-management entry points."""

    actor: SelfManagementActorContext
    gateway: SelfManagementToolGateway
    toolkit: SelfManagementToolkit
    tool_definitions: tuple[SelfManagementToolDefinition, ...]


def build_self_management_web_agent_runtime(
    *,
    db: AsyncSession,
    current_user: User,
) -> SelfManagementWebAgentRuntime:
    """Build the shared runtime used by the web built-in agent surface."""

    actor = build_self_management_actor_context(
        user=current_user,
        actor_type=SelfManagementActorType.WEB_AGENT,
    )
    gateway = SelfManagementToolGateway(
        actor,
        surface=SelfManagementSurface.WEB_AGENT,
    )
    toolkit = SelfManagementToolkit(
        db=db,
        current_user=current_user,
        gateway=gateway,
    )
    return SelfManagementWebAgentRuntime(
        actor=actor,
        gateway=gateway,
        toolkit=toolkit,
        tool_definitions=list_self_management_tool_definitions(
            surface=SelfManagementSurface.WEB_AGENT,
        ),
    )


__all__ = [
    "SelfManagementWebAgentRuntime",
    "build_self_management_web_agent_runtime",
]
