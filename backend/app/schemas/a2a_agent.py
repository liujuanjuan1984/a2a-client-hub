"""Compatibility re-export for the legacy personal A2A agent schema path."""

from app.features.personal_agents.schemas import (
    A2AAgentCreate,
    A2AAgentListMeta,
    A2AAgentListResponse,
    A2AAgentPagination,
    A2AAgentResponse,
    A2AAgentUpdate,
    A2AAuthType,
)

__all__ = [
    "A2AAgentCreate",
    "A2AAgentListMeta",
    "A2AAgentListResponse",
    "A2AAgentPagination",
    "A2AAgentResponse",
    "A2AAgentUpdate",
    "A2AAuthType",
]
