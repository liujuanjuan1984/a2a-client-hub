"""Compatibility re-export for the legacy hub A2A agent service path."""

from app.features.hub_agents.service import (
    HubA2AAgentError,
    HubA2AAgentNotFoundError,
    HubA2AAgentRecord,
    HubA2AAgentService,
    HubA2AAgentValidationError,
    HubA2AAllowlistConflictError,
    HubA2AAllowlistRecord,
    HubA2AUserNotFoundError,
    hub_a2a_agent_service,
)

__all__ = [
    "HubA2AAgentError",
    "HubA2AAgentNotFoundError",
    "HubA2AAgentRecord",
    "HubA2AAgentService",
    "HubA2AAgentValidationError",
    "HubA2AAllowlistConflictError",
    "HubA2AAllowlistRecord",
    "HubA2AUserNotFoundError",
    "hub_a2a_agent_service",
]
