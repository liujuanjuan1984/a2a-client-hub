"""Tool for invoking external agents over the A2A protocol."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from app.agents.tools.base import AbstractTool, ToolMetadata
from app.agents.tools.responses import (
    ToolResult,
    create_tool_error,
    create_tool_response,
)
from app.core.config import settings
from app.core.logging import get_logger
from app.integrations.a2a_client import get_a2a_service
from app.integrations.a2a_client.controls import summarize_query
from app.integrations.a2a_client.errors import A2AAgentUnavailableError


class A2AAgentCallArguments(BaseModel):
    """Input payload accepted by ``A2AAgentTool``."""

    agent: Optional[str] = Field(
        default=None,
        description="Identifier of a pre-configured A2A agent",
    )
    agent_url: Optional[str] = Field(
        default=None,
        description="Direct URL of the downstream A2A agent",
    )
    query: str = Field(..., description="User query forwarded to the external agent")
    context_id: Optional[str] = Field(
        default=None,
        alias="contextId",
        description="Optional A2A context identifier",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Optional A2A metadata forwarded with the message",
    )
    model_config = {
        "populate_by_name": True,
    }


class A2AAgentTool(AbstractTool):
    """Expose downstream A2A agents as an agentic tool."""

    name = "a2a_agent"
    description = "Call external agents registered via the A2A protocol and return their response."
    args_schema = A2AAgentCallArguments
    metadata = ToolMetadata(
        read_only=True,
        requires_confirmation=False,
        default_timeout=settings.a2a_default_timeout,
        max_retries=0,
        retry_backoff=0.5,
        idempotent=True,
        labels=("a2a", "external"),
    )

    logger = get_logger(__name__)

    async def initialise(self) -> None:
        # Warm-up removed to avoid blocking when an unused agent is unavailable.
        return

    async def execute(self, **kwargs: Any) -> ToolResult:
        arguments = A2AAgentCallArguments(**kwargs)
        self.logger.info(
            "A2AAgentTool.execute invoked",
            extra={
                "agent": arguments.agent,
                "agent_url": arguments.agent_url,
                "query_meta": summarize_query(arguments.query),
            },
        )

        if not settings.a2a_enabled:
            self.logger.warning("A2A integration disabled; aborting tool execution")
            return create_tool_error(
                message="A2A integration is disabled",
                kind="a2a_disabled",
                detail="Set A2A_ENABLED=true and configure A2A_AGENTS to enable this tool",
            )

        service = get_a2a_service()

        try:
            resolved = service.resolve_agent(
                agent=arguments.agent,
                agent_url=arguments.agent_url,
            )
        except ValueError as exc:
            self.logger.warning(
                "Failed to resolve A2A agent",
                extra={
                    "agent": arguments.agent,
                    "agent_url": arguments.agent_url,
                    "error": str(exc),
                },
            )
            return create_tool_error(
                message="Invalid A2A agent reference",
                kind="invalid_agent",
                detail=str(exc),
            )

        if not arguments.query.strip():
            self.logger.warning(
                "Empty query passed to A2A agent",
                extra={
                    "agent": arguments.agent,
                    "agent_url": arguments.agent_url,
                },
            )
            return create_tool_error(
                message="Query must be a non-empty string",
                kind="validation_error",
            )

        try:
            result = await service.call_agent(
                resolved=resolved,
                query=arguments.query,
                context_id=arguments.context_id,
                metadata=arguments.metadata,
            )
        except A2AAgentUnavailableError as exc:  # pragma: no cover - defensive
            self.logger.error(
                "A2A agent unavailable during call",
                extra={
                    "agent": resolved.name,
                    "agent_url": resolved.url,
                    "error": str(exc),
                },
            )
            return create_tool_error(
                message=f"A2A agent '{resolved.name}' is unavailable",
                kind="a2a_unavailable",
                detail=str(exc),
                display=str(exc),
            )

        if not result.get("success", False):
            error_detail = result.get("error") or "Unknown A2A failure"
            error_kind = (
                "a2a_unavailable"
                if result.get("error_code") == "agent_unavailable"
                else "a2a_error"
            )
            self.logger.error(
                "A2A agent execution failed",
                extra={
                    "agent": resolved.name,
                    "agent_url": resolved.url,
                    "error": error_detail,
                },
            )
            return create_tool_error(
                message=f"A2A agent '{resolved.name}' execution failed",
                kind=error_kind,
                detail=error_detail,
                display=error_detail,
            )

        content = result.get("content") or ""
        data = {
            "agent_url": resolved.url,
            "agent_name": resolved.name,
        }
        if "raw" in result:
            data["raw"] = result["raw"]

        self.logger.info(
            "A2A agent execution succeeded",
            extra={
                "agent": resolved.name,
                "agent_url": resolved.url,
                "content_preview": content[:120],
            },
        )

        return create_tool_response(
            data=data,
            message="A2A agent call succeeded",
            display=content,
        )


__all__ = ["A2AAgentTool"]
