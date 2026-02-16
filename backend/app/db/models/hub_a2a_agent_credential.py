"""Compatibility export for shared-scope A2A agent credentials."""

from app.db.models.a2a_agent_credential import (
    A2AAgentCredential as HubA2AAgentCredential,
)

__all__ = ["HubA2AAgentCredential"]
