"""Runtime helpers for Hub Assistant web entry points."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User
from app.features.hub_access.actor_context import (
    HubActorContext,
    HubActorType,
    build_hub_actor_context,
)
from app.features.hub_access.operation_gateway import (
    HubOperationGateway,
    HubSurface,
)
from app.features.hub_assistant.shared.hub_assistant_tool_contract import (
    HubAssistantToolDefinition,
    list_hub_assistant_tool_definitions,
)
from app.features.hub_assistant.shared.hub_assistant_toolkit import (
    HubAssistantToolkit,
)


@dataclass(frozen=True)
class HubAssistantWebAgentRuntime:
    """Resolved web-agent runtime for Hub Assistant entry points."""

    actor: HubActorContext
    gateway: HubOperationGateway
    toolkit: HubAssistantToolkit
    tool_definitions: tuple[HubAssistantToolDefinition, ...]


def build_hub_assistant_web_agent_runtime(
    *,
    db: AsyncSession,
    current_user: User,
    web_agent_conversation_id: str | None = None,
) -> HubAssistantWebAgentRuntime:
    """Build the shared runtime used by the web Hub Assistant surface."""

    actor = build_hub_actor_context(
        user=current_user,
        actor_type=HubActorType.WEB_AGENT,
    )
    gateway = HubOperationGateway(
        actor,
        surface=HubSurface.WEB_AGENT,
        web_agent_conversation_id=web_agent_conversation_id,
    )
    toolkit = HubAssistantToolkit(
        db=db,
        current_user=current_user,
        gateway=gateway,
    )
    return HubAssistantWebAgentRuntime(
        actor=actor,
        gateway=gateway,
        toolkit=toolkit,
        tool_definitions=list_hub_assistant_tool_definitions(
            surface=HubSurface.WEB_AGENT,
        ),
    )
