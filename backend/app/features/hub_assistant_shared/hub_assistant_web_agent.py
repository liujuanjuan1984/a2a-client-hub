"""Runtime helpers for Hub Assistant web entry points."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User
from app.features.hub_assistant_shared.actor_context import (
    HubAssistantActorContext,
    HubAssistantActorType,
    build_hub_assistant_actor_context,
)
from app.features.hub_assistant_shared.hub_assistant_tool_contract import (
    HubAssistantToolDefinition,
    list_hub_assistant_tool_definitions,
)
from app.features.hub_assistant_shared.hub_assistant_toolkit import (
    HubAssistantToolkit,
)
from app.features.hub_assistant_shared.tool_gateway import (
    HubAssistantSurface,
    HubAssistantToolGateway,
)


@dataclass(frozen=True)
class HubAssistantWebAgentRuntime:
    """Resolved web-agent runtime for Hub Assistant entry points."""

    actor: HubAssistantActorContext
    gateway: HubAssistantToolGateway
    toolkit: HubAssistantToolkit
    tool_definitions: tuple[HubAssistantToolDefinition, ...]


def build_hub_assistant_web_agent_runtime(
    *,
    db: AsyncSession,
    current_user: User,
    web_agent_conversation_id: str | None = None,
) -> HubAssistantWebAgentRuntime:
    """Build the shared runtime used by the web Hub Assistant surface."""

    actor = build_hub_assistant_actor_context(
        user=current_user,
        actor_type=HubAssistantActorType.WEB_AGENT,
    )
    gateway = HubAssistantToolGateway(
        actor,
        surface=HubAssistantSurface.WEB_AGENT,
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
            surface=HubAssistantSurface.WEB_AGENT,
        ),
    )
