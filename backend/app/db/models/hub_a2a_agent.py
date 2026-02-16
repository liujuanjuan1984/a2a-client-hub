"""Compatibility export for shared-scope A2A agents."""

from app.db.models.a2a_agent import A2AAgent as HubA2AAgent

__all__ = ["HubA2AAgent"]
