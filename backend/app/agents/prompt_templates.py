"""Compatibility layer re-exporting the new prompting package."""

from app.agents.prompting import (
    AGENT_PROMPT_CONFIGS,
    TOOL_GUIDES,
    AgentPromptConfig,
    IntentTrigger,
    PromptBuilder,
    ToolArgumentGuide,
    ToolGuide,
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
