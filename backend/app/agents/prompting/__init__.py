"""Prompting package exposing tool guides and agent configurations."""

# Import subpackages for registration side effects.
from app.agents.prompting import agent_configs as _agent_configs  # noqa: F401
from app.agents.prompting import tool_guides as _tool_guides  # noqa: F401
from app.agents.prompting.builder import (
    AgentPromptConfig,
    IntentTrigger,
    PromptBuilder,
    ToolArgumentGuide,
    ToolGuide,
)
from app.agents.prompting.registry import (
    AGENT_PROMPT_CONFIGS,
    TOOL_GUIDES,
    register_agent_config,
    register_tool,
)

__all__ = [
    "ToolArgumentGuide",
    "IntentTrigger",
    "ToolGuide",
    "AgentPromptConfig",
    "PromptBuilder",
    "TOOL_GUIDES",
    "AGENT_PROMPT_CONFIGS",
    "register_tool",
    "register_agent_config",
]
