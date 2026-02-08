"""Validate tool isolation logic enforced by agent profiles."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.agents.agent_registry import (
    FOOD_AGENT_NAME,
    FOOD_TOOL_NAMES,
    HABIT_AGENT_NAME,
    HABIT_TOOL_NAMES,
    NOTE_AGENT_NAME,
    NOTE_TOOL_NAMES,
    PERSON_AGENT_NAME,
    PERSON_TOOL_NAMES,
    ROOT_AGENT_NAME,
    TAG_AGENT_NAME,
    TAG_TOOL_NAMES,
    TASK_AGENT_NAME,
    TASK_TOOL_NAMES,
    TIMELOG_AGENT_NAME,
    TIMELOG_TOOL_NAMES,
    USER_PREFERENCE_AGENT_NAME,
    USER_PREFERENCE_TOOL_NAMES,
    VISION_AGENT_NAME,
    VISION_TOOL_NAMES,
)
from app.agents.registry import ToolAccessRegistry


def _make_registry(session, agent_name: str) -> ToolAccessRegistry:
    return ToolAccessRegistry(db=session, user_id=uuid4(), agent_name=agent_name)


@pytest.mark.asyncio
async def test_root_agent_excludes_domain_tools(async_db_session):
    registry = _make_registry(async_db_session, ROOT_AGENT_NAME)
    allowed = set(registry._allowed_tools)
    domain_tools = (
        NOTE_TOOL_NAMES
        | TASK_TOOL_NAMES
        | HABIT_TOOL_NAMES
        | TIMELOG_TOOL_NAMES
        | PERSON_TOOL_NAMES
        | TAG_TOOL_NAMES
        | VISION_TOOL_NAMES
        | FOOD_TOOL_NAMES
        | USER_PREFERENCE_TOOL_NAMES
    )
    assert allowed.isdisjoint(domain_tools)


@pytest.mark.parametrize(
    "agent_name, expected_tools",
    [
        (NOTE_AGENT_NAME, NOTE_TOOL_NAMES),
        (TASK_AGENT_NAME, TASK_TOOL_NAMES),
        (HABIT_AGENT_NAME, HABIT_TOOL_NAMES),
        (TIMELOG_AGENT_NAME, TIMELOG_TOOL_NAMES),
        (PERSON_AGENT_NAME, PERSON_TOOL_NAMES),
        (TAG_AGENT_NAME, TAG_TOOL_NAMES),
        (VISION_AGENT_NAME, VISION_TOOL_NAMES),
        (FOOD_AGENT_NAME, FOOD_TOOL_NAMES),
        (USER_PREFERENCE_AGENT_NAME, USER_PREFERENCE_TOOL_NAMES),
    ],
)
@pytest.mark.asyncio
async def test_specialist_agents_include_expected_tools(
    async_db_session, agent_name, expected_tools
):
    registry = _make_registry(async_db_session, agent_name)
    allowed = set(registry._allowed_tools)
    assert set(expected_tools).issubset(allowed)


@pytest.mark.asyncio
async def test_root_agent_cannot_execute_note_tool(async_db_session):
    registry = _make_registry(async_db_session, ROOT_AGENT_NAME)
    with pytest.raises(ValueError):
        await registry.execute_tool("create_note", content="test")
