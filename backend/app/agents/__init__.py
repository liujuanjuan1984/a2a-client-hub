"""
Agents module

This module contains the Agentic layer for tool calling capabilities.
It provides a clean separation between API routes and business logic,
enabling easy extension and maintenance of AI agent tools.
"""

from app.agents.agent_registry import AgentRegistry, agent_registry
from app.agents.registry import ToolAccessRegistry

__all__ = ["ToolAccessRegistry", "AgentRegistry", "agent_registry"]
