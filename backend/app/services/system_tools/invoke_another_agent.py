"""System tool that invokes another Hub/Personal agent on behalf of the caller."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.core.logging import get_logger
from app.integrations.a2a_client import get_a2a_service
from app.integrations.a2a_client.errors import A2AAgentUnavailableError
from app.services import a2a_runtime, hub_a2a_runtime
from app.services.system_tools.types import (
    TOOL_INVOCATION_CHAIN_METADATA_KEY,
    TOOL_INVOCATION_DEPTH_METADATA_KEY,
    TOOL_INVOCATION_MAX_DEPTH_METADATA_KEY,
    SystemTool,
    ToolContext,
    ToolExecutionResult,
)

logger = get_logger(__name__)


class InvokeAnotherAgentTool(SystemTool):
    """Invoke another registered agent and return the latest assistant response."""

    @property
    def name(self) -> str:
        return "hub_invoke_agent"

    @property
    def description(self) -> str:
        return "Invoke another personal or shared agent with a prompt"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "prompt": {"type": "string"},
                "agent_source": {
                    "type": "string",
                    "enum": ["personal", "shared"],
                },
                "tool_choice": {},
                "tools": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["agent_id", "prompt"],
            "additionalProperties": False,
        }

    async def execute(
        self,
        params: dict[str, Any],
        context: ToolContext,
    ) -> ToolExecutionResult:
        if context.logger is not None:
            context.logger.debug(
                "Executing hub invoke tool",
                extra={"agent_id": context.user_id, "tool": self.name},
            )

        if not params:
            return ToolExecutionResult(
                success=False,
                error="tool parameters are required",
                error_code="invalid_parameters",
            )

        raw_agent_id = params.get("agent_id")
        raw_prompt = params.get("prompt")
        agent_source = params.get("agent_source")
        if agent_source is not None and str(agent_source) not in {"personal", "shared"}:
            return ToolExecutionResult(
                success=False,
                error="agent_source must be one of: personal, shared",
                error_code="invalid_agent_source",
            )
        if not isinstance(raw_agent_id, str) or not raw_agent_id.strip():
            return ToolExecutionResult(
                success=False,
                error="agent_id is required",
                error_code="invalid_parameters",
            )
        try:
            agent_uuid = UUID(raw_agent_id.strip())
        except ValueError:
            return ToolExecutionResult(
                success=False,
                error="agent_id must be a valid UUID",
                error_code="invalid_agent_id",
            )

        if not isinstance(raw_prompt, str) or not raw_prompt.strip():
            return ToolExecutionResult(
                success=False,
                error="prompt is required",
                error_code="invalid_parameters",
            )
        prompt = raw_prompt.strip()

        current_chain = tuple(context.tool_invocation_chain)
        if context.agent_id is not None:
            root_agent_id = str(context.agent_id)
            if root_agent_id and root_agent_id not in current_chain:
                current_chain = (root_agent_id, *current_chain)

        max_depth = context.tool_max_invocation_depth
        if max_depth <= 0:
            max_depth = max(1, int(settings.a2a_tool_call_max_depth))
        next_depth = context.tool_invocation_depth + 1
        if next_depth > max_depth:
            return ToolExecutionResult(
                success=False,
                error=f"Tool invocation depth exceeded (max {max_depth})",
                error_code="tool_invocation_depth_exceeded",
            )

        target_agent_id = str(agent_uuid)
        if target_agent_id in current_chain:
            return ToolExecutionResult(
                success=False,
                error=f"Tool invocation cycle detected for agent {target_agent_id}",
                error_code="tool_invocation_cycle_detected",
            )

        next_chain = (*current_chain, target_agent_id)
        next_depth_metadata = {
            TOOL_INVOCATION_CHAIN_METADATA_KEY: ",".join(next_chain),
            TOOL_INVOCATION_DEPTH_METADATA_KEY: str(next_depth),
            TOOL_INVOCATION_MAX_DEPTH_METADATA_KEY: str(max_depth),
        }
        tool_metadata = dict(context.metadata)
        tool_metadata.update(next_depth_metadata)

        resolved_source = (
            str(agent_source).strip()
            if isinstance(agent_source, str)
            else context.agent_source
        ) or "personal"
        if resolved_source not in {"personal", "shared"}:
            resolved_source = "personal"

        try:
            if resolved_source == "shared":
                runtime = await hub_a2a_runtime.hub_a2a_runtime_builder.build(
                    context.db,
                    user_id=context.user_id,
                    agent_id=agent_uuid,
                )
            else:
                runtime = await a2a_runtime.a2a_runtime_builder.build(
                    context.db,
                    user_id=context.user_id,
                    agent_id=agent_uuid,
                )
        except (RuntimeError, A2AAgentUnavailableError) as exc:
            logger.error(
                "Failed to resolve tool target runtime",
                extra={
                    "user_id": str(context.user_id),
                    "agent_id": str(agent_uuid),
                    "agent_source": resolved_source,
                },
            )
            return ToolExecutionResult(
                success=False,
                error=str(exc),
                error_code="agent_resolve_failed",
            )

        result = await get_a2a_service().call_agent(
            resolved=runtime.resolved,
            query=prompt,
            context_id=context.context_id,
            metadata=tool_metadata,
        )
        if not result.get("success"):
            return ToolExecutionResult(
                success=False,
                error=result.get("error"),
                error_code=result.get("error_code") or "invoke_failed",
                metadata={
                    "raw": result.get("raw"),
                    "agent_url": result.get("agent_url"),
                },
            )

        response_content = result.get("content")
        if response_content is None:
            raw = result.get("raw")
            if raw is not None:
                response_content = json.dumps(raw, ensure_ascii=False)

        return ToolExecutionResult(
            success=True,
            content=response_content,
            metadata={
                "agent_name": result.get("agent_name"),
                "agent_url": result.get("agent_url"),
                "upstream_error": result.get("error"),
            },
        )


__all__ = ["InvokeAnotherAgentTool"]
