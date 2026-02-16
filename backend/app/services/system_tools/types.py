"""Core abstractions for pluggable system tools."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class ToolContext:
    """Runtime context passed into system tool execution."""

    db: Any
    user_id: UUID
    agent_source: str | None
    query: str
    context_id: str | None
    conversation_id: str | None
    logger: Any
    metadata: dict[str, Any]


@dataclass(frozen=True)
class ToolExecutionResult:
    """Result object for system tool execution."""

    success: bool
    content: Any | None = None
    error: str | None = None
    error_code: str | None = None
    metadata: dict[str, Any] | None = None


class SystemTool(ABC):
    """Pluggable system tool contract."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Tool identifier used by downstream tool calls."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of tool intent."""

    @property
    @abstractmethod
    def input_schema(self) -> dict[str, Any]:
        """JSON schema describing tool input contract."""

    @abstractmethod
    async def execute(
        self,
        params: dict[str, Any],
        context: ToolContext,
    ) -> ToolExecutionResult:
        """Run the tool with validated params in the given execution context."""
