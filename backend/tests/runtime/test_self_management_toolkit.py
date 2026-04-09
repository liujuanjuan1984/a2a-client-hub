from __future__ import annotations

import pytest

from app.features.agents_shared.actor_context import (
    SelfManagementActorType,
    build_self_management_actor_context,
)
from app.features.agents_shared.capability_catalog import (
    SELF_AGENTS_UPDATE_CONFIG,
    SELF_JOBS_GET,
    SELF_JOBS_LIST,
    SELF_JOBS_UPDATE_SCHEDULE,
    SELF_SESSIONS_LIST,
)
from app.features.agents_shared.self_management_toolkit import (
    SelfManagementToolInputError,
    SelfManagementToolkit,
)
from app.features.agents_shared.tool_gateway import (
    SelfManagementSurface,
    SelfManagementToolGateway,
)
from tests.support.utils import (
    create_a2a_agent,
    create_conversation_thread,
    create_schedule_task,
    create_user,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _build_toolkit(async_db_session, user):
    actor = build_self_management_actor_context(
        user=user,
        actor_type=SelfManagementActorType.HUMAN_CLI,
    )
    gateway = SelfManagementToolGateway(actor, surface=SelfManagementSurface.CLI)
    return SelfManagementToolkit(
        db=async_db_session,
        current_user=user,
        gateway=gateway,
    )


async def test_self_management_toolkit_executes_first_wave_operations(
    async_db_session,
) -> None:
    user = await create_user(async_db_session)
    agent = await create_a2a_agent(
        async_db_session,
        user_id=user.id,
        suffix="toolkit-jobs",
    )
    task = await create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        prompt="toolkit prompt",
    )
    await create_conversation_thread(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        title="Toolkit Session",
    )
    toolkit = _build_toolkit(async_db_session, user)

    list_result = await toolkit.execute(
        operation_id=SELF_JOBS_LIST.operation_id,
        arguments={"page": 1, "size": 20},
    )
    get_result = await toolkit.execute(
        operation_id=SELF_JOBS_GET.operation_id,
        arguments={"task_id": str(task.id)},
    )
    sessions_result = await toolkit.execute(
        operation_id=SELF_SESSIONS_LIST.operation_id,
        arguments={"page": 1, "size": 20},
    )

    assert list_result.payload["total"] >= 1
    assert any(item["id"] == str(task.id) for item in list_result.payload["items"])
    assert get_result.payload["job"]["id"] == str(task.id)
    assert get_result.payload["job"]["prompt"] == "toolkit prompt"
    assert sessions_result.payload["pagination"]["total"] >= 1
    assert sessions_result.payload["items"][0]["title"] == "Toolkit Session"


async def test_self_management_toolkit_updates_agent_config(
    async_db_session,
) -> None:
    user = await create_user(async_db_session)
    record = await create_a2a_agent(
        async_db_session,
        user_id=user.id,
        suffix="toolkit-agent",
    )
    toolkit = _build_toolkit(async_db_session, user)

    result = await toolkit.execute(
        operation_id=SELF_AGENTS_UPDATE_CONFIG.operation_id,
        arguments={
            "agent_id": str(record.id),
            "name": "Toolkit Updated Agent",
            "enabled": False,
            "tags": ["cli", "toolkit"],
        },
    )

    assert result.payload["agent"]["id"] == str(record.id)
    assert result.payload["agent"]["name"] == "Toolkit Updated Agent"
    assert result.payload["agent"]["enabled"] is False
    assert result.payload["agent"]["tags"] == ["cli", "toolkit"]


async def test_self_management_toolkit_rejects_invalid_schedule_inputs(
    async_db_session,
) -> None:
    user = await create_user(async_db_session)
    agent = await create_a2a_agent(
        async_db_session,
        user_id=user.id,
        suffix="toolkit-invalid",
    )
    task = await create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
    )
    toolkit = _build_toolkit(async_db_session, user)

    with pytest.raises(SelfManagementToolInputError) as exc_info:
        await toolkit.execute(
            operation_id=SELF_JOBS_UPDATE_SCHEDULE.operation_id,
            arguments={
                "task_id": str(task.id),
                "time_point": "not-an-object",
            },
        )

    assert str(exc_info.value) == "`time_point` must be an object."
