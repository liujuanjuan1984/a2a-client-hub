"""Compatibility re-export for the legacy personal A2A agent service path."""

from app.features.personal_agents.service import (
    A2AAgentError,
    A2AAgentNotFoundError,
    A2AAgentRecord,
    A2AAgentValidationError,
    a2a_agent_service,
)

__all__ = [
    "A2AAgentError",
    "A2AAgentNotFoundError",
    "A2AAgentRecord",
    "A2AAgentValidationError",
    "a2a_agent_service",
]
