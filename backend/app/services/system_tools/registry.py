"""System tool registry for pluggable Hub tool execution."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional

from app.core.logging import get_logger

from .types import SystemTool

logger = get_logger(__name__)


class SystemToolRegistry:
    """Runtime registry for Hub system tools."""

    def __init__(self) -> None:
        self._tools: dict[str, SystemTool] = {}

    def register(self, tool: SystemTool) -> None:
        """Register (or replace) a system tool by name."""
        self._tools[tool.name] = tool
        logger.debug("System tool registered", extra={"tool_name": tool.name})

    def get_tool(self, name: str) -> Optional[SystemTool]:
        """Get a registered system tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> Mapping[str, SystemTool]:
        """Return all registered tools."""
        return dict(self._tools)

    def build_upstream_tool_schema(self) -> list[dict[str, Any]]:
        """Convert registered tools into upstream tool schema list."""
        schemas: list[dict[str, Any]] = []
        for name in sorted(self._tools.keys()):
            tool = self._tools[name]
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.input_schema,
                    },
                }
            )
        return schemas


system_tool_registry = SystemToolRegistry()

__all__ = ["SystemToolRegistry", "system_tool_registry"]
