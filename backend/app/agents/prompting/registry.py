"""In-memory registries for tool guides and agent prompt configurations."""

from __future__ import annotations

from typing import Dict

from app.agents.prompting.builder import AgentPromptConfig, ToolGuide

TOOL_GUIDES: Dict[str, ToolGuide] = {}
AGENT_PROMPT_CONFIGS: Dict[str, AgentPromptConfig] = {}


def register_tool(guide: ToolGuide) -> None:
    TOOL_GUIDES[guide.name] = guide


def register_agent_config(agent_name: str, config: AgentPromptConfig) -> None:
    AGENT_PROMPT_CONFIGS[agent_name] = config


__all__ = [
    "TOOL_GUIDES",
    "AGENT_PROMPT_CONFIGS",
    "register_tool",
    "register_agent_config",
]
