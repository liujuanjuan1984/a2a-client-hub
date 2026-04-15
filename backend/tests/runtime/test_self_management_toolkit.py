from __future__ import annotations

import pytest

from app.features.personal_agents import service as personal_agent_service_module
from app.features.self_management_shared import (
    delegated_conversation_service as delegated_conversation_service_module,
)
from app.features.self_management_shared.actor_context import (
    SelfManagementActorType,
    build_self_management_actor_context,
)
from app.features.self_management_shared.capability_catalog import (
    SELF_AGENTS_CHECK_HEALTH,
    SELF_AGENTS_CHECK_HEALTH_ALL,
    SELF_AGENTS_START_SESSIONS,
    SELF_AGENTS_UPDATE_CONFIG,
    SELF_JOBS_GET,
    SELF_JOBS_LIST,
    SELF_JOBS_UPDATE_SCHEDULE,
    SELF_SESSIONS_LIST,
    SELF_SESSIONS_SEND_MESSAGE,
)
from app.features.self_management_shared.self_management_toolkit import (
    SelfManagementToolInputError,
    SelfManagementToolkit,
)
from app.features.self_management_shared.tool_gateway import (
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
        actor_type=SelfManagementActorType.HUMAN_API,
    )
    gateway = SelfManagementToolGateway(actor, surface=SelfManagementSurface.REST)
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
            "tags": ["self-management", "toolkit"],
        },
    )

    assert result.payload["agent"]["id"] == str(record.id)
    assert result.payload["agent"]["name"] == "Toolkit Updated Agent"
    assert result.payload["agent"]["enabled"] is False
    assert result.payload["agent"]["tags"] == ["self-management", "toolkit"]


async def test_self_management_toolkit_checks_agent_health(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await create_user(async_db_session)
    record = await create_a2a_agent(
        async_db_session,
        user_id=user.id,
        suffix="toolkit-health",
    )
    toolkit = _build_toolkit(async_db_session, user)

    async def _fake_check_agents_health(*, user_id, force=False, agent_id=None):
        assert user_id == user.id
        return (
            personal_agent_service_module.A2AAgentHealthCheckSummaryRecord(
                requested=1 if agent_id is not None else 2,
                checked=1,
                skipped_cooldown=0,
                healthy=1,
                degraded=0,
                unavailable=0,
                unknown=0,
            ),
            [
                personal_agent_service_module.A2AAgentHealthCheckItemRecord(
                    agent_id=record.id,
                    health_status="healthy",
                    checked_at=record.updated_at,
                    skipped_cooldown=not force,
                    error=None,
                    reason_code=None,
                )
            ],
        )

    monkeypatch.setattr(
        personal_agent_service_module.a2a_agent_service,
        "check_agents_health",
        _fake_check_agents_health,
    )

    single_result = await toolkit.execute(
        operation_id=SELF_AGENTS_CHECK_HEALTH.operation_id,
        arguments={"agent_id": str(record.id), "force": True},
    )
    all_result = await toolkit.execute(
        operation_id=SELF_AGENTS_CHECK_HEALTH_ALL.operation_id,
        arguments={"force": True},
    )

    assert single_result.payload["summary"]["requested"] == 1
    assert single_result.payload["items"][0]["agent_id"] == str(record.id)
    assert all_result.payload["summary"]["requested"] >= 1
    assert any(
        item["agent_id"] == str(record.id) for item in all_result.payload["items"]
    )


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


async def test_self_management_toolkit_sends_session_message(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await create_user(async_db_session)
    thread = await create_conversation_thread(
        async_db_session,
        user_id=user.id,
        title="Toolkit Delegated Session",
    )
    toolkit = _build_toolkit(async_db_session, user)

    async def _fake_send_messages_to_sessions(**kwargs):
        assert kwargs["db"] is async_db_session
        assert kwargs["current_user"].id == user.id
        assert kwargs["conversation_ids"] == [thread.id]
        assert kwargs["message"] == "ping"
        return {
            "summary": {"requested": 1, "completed": 1, "failed": 0},
            "items": [{"conversation_id": str(thread.id), "status": "completed"}],
        }

    monkeypatch.setattr(
        delegated_conversation_service_module.self_management_delegated_conversation_service,
        "send_messages_to_sessions",
        _fake_send_messages_to_sessions,
    )

    result = await toolkit.execute(
        operation_id=SELF_SESSIONS_SEND_MESSAGE.operation_id,
        arguments={
            "conversation_ids": [str(thread.id)],
            "message": "ping",
        },
    )

    assert result.payload["summary"] == {"requested": 1, "completed": 1, "failed": 0}
    assert result.payload["items"] == [
        {"conversation_id": str(thread.id), "status": "completed"}
    ]


async def test_self_management_toolkit_starts_agent_sessions(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await create_user(async_db_session)
    agent = await create_a2a_agent(
        async_db_session,
        user_id=user.id,
        suffix="toolkit-start-sessions",
    )
    toolkit = _build_toolkit(async_db_session, user)

    async def _fake_start_sessions_for_agents(**kwargs):
        assert kwargs["db"] is async_db_session
        assert kwargs["current_user"].id == user.id
        assert kwargs["agent_ids"] == [agent.id]
        assert kwargs["message"] == "hello"
        return {
            "summary": {"requested": 1, "completed": 1, "failed": 0},
            "items": [{"agent_id": str(agent.id), "status": "completed"}],
        }

    monkeypatch.setattr(
        delegated_conversation_service_module.self_management_delegated_conversation_service,
        "start_sessions_for_agents",
        _fake_start_sessions_for_agents,
    )

    result = await toolkit.execute(
        operation_id=SELF_AGENTS_START_SESSIONS.operation_id,
        arguments={
            "agent_ids": [str(agent.id)],
            "message": "hello",
        },
    )

    assert result.payload["summary"] == {"requested": 1, "completed": 1, "failed": 0}
    assert result.payload["items"] == [
        {"agent_id": str(agent.id), "status": "completed"}
    ]
