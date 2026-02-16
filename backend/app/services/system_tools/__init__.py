"""Pluggable system tools for Hub invocation."""

from __future__ import annotations

from .invoke_another_agent import InvokeAnotherAgentTool
from .registry import SystemToolRegistry, system_tool_registry
from .types import SystemTool, ToolContext, ToolExecutionResult

_DEFAULT_TOOL_NAME = "hub_invoke_agent"


def register_default_tools() -> None:
    """Register built-in system tools with safe idempotent behavior."""
    if system_tool_registry.get_tool(_DEFAULT_TOOL_NAME) is None:
        system_tool_registry.register(InvokeAnotherAgentTool())


register_default_tools()


__all__ = [
    "SystemTool",
    "ToolContext",
    "ToolExecutionResult",
    "SystemToolRegistry",
    "system_tool_registry",
    "register_default_tools",
]
