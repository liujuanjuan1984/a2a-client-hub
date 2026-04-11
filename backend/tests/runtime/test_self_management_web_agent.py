from __future__ import annotations

from uuid import uuid4

import pytest

from app.api.deps import get_current_self_management_web_agent_runtime
from app.db.models.user import User
from app.features.self_management_shared.self_management_web_agent import (
    build_self_management_web_agent_runtime,
)
from app.features.self_management_shared.tool_gateway import SelfManagementSurface
from tests.support.utils import create_a2a_agent, create_schedule_task, create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _build_user(*, is_superuser: bool = False) -> User:
    return User(
        id=uuid4(),
        email=f"user-{uuid4().hex[:8]}@example.com",
        name="Web Agent User",
        password_hash="test-password-hash",  # pragma: allowlist secret
        is_superuser=is_superuser,
        timezone="UTC",
    )


async def test_build_self_management_web_agent_runtime_exposes_toolkit_and_tools(
    async_db_session,
) -> None:
    user = await create_user(async_db_session)
    agent = await create_a2a_agent(
        async_db_session,
        user_id=user.id,
        suffix="web-agent-runtime",
    )
    task = await create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
    )

    runtime = build_self_management_web_agent_runtime(
        db=async_db_session,
        current_user=user,
    )
    result = await runtime.toolkit.execute(
        operation_id="self.jobs.get",
        arguments={"task_id": str(task.id)},
    )

    assert runtime.actor.actor_type.value == "web_agent"
    assert runtime.gateway.surface == SelfManagementSurface.WEB_AGENT
    assert any(item.tool_name == "self.jobs.list" for item in runtime.tool_definitions)
    assert result.payload["job"]["id"] == str(task.id)


async def test_web_agent_dependency_returns_web_agent_runtime(
    async_db_session,
) -> None:
    user = _build_user()

    runtime = get_current_self_management_web_agent_runtime(
        db=async_db_session,
        current_user=user,
    )

    assert runtime.actor.actor_type.value == "web_agent"
    assert runtime.gateway.surface == SelfManagementSurface.WEB_AGENT
