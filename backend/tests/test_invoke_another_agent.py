"""Tests for system tool invocation safety checks."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.services.system_tools import ToolContext
from app.services.system_tools.invoke_another_agent import InvokeAnotherAgentTool


@pytest.mark.asyncio
async def test_invoke_another_agent_tool_rejects_depth_exceeded() -> None:
    context = ToolContext(
        db=None,
        user_id=uuid4(),
        agent_id=UUID("11111111-1111-1111-1111-111111111111"),
        agent_source="personal",
        query="trigger",
        context_id="context-1",
        conversation_id="conversation-1",
        logger=SimpleNamespace(debug=lambda *_args, **_kwargs: None),
        metadata={},
        tool_invocation_chain=(
            "11111111-1111-1111-1111-111111111111",
            "22222222-2222-2222-2222-222222222222",
        ),
        tool_invocation_depth=5,
        tool_max_invocation_depth=5,
    )

    tool = InvokeAnotherAgentTool()
    result = await tool.execute(
        {
            "agent_id": "33333333-3333-3333-3333-333333333333",
            "prompt": "continue",
        },
        context,
    )

    assert result.success is False
    assert result.error_code == "tool_invocation_depth_exceeded"


@pytest.mark.asyncio
async def test_invoke_another_agent_tool_rejects_cycle() -> None:
    agent_id = "44444444-4444-4444-4444-444444444444"
    context = ToolContext(
        db=None,
        user_id=uuid4(),
        agent_id=UUID(agent_id),
        agent_source="personal",
        query="trigger",
        context_id="context-1",
        conversation_id="conversation-1",
        logger=SimpleNamespace(debug=lambda *_args, **_kwargs: None),
        metadata={},
        tool_invocation_chain=(agent_id,),
        tool_invocation_depth=1,
        tool_max_invocation_depth=5,
    )

    tool = InvokeAnotherAgentTool()
    result = await tool.execute(
        {
            "agent_id": agent_id,
            "prompt": "continue",
        },
        context,
    )

    assert result.success is False
    assert result.error_code == "tool_invocation_cycle_detected"
