from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.security import create_self_management_access_token
from app.db.models.agent_message import AgentMessage
from app.db.models.agent_message_block import AgentMessageBlock
from app.features.invoke import route_runner as invoke_route_runner
from app.features.invoke.service import StreamFinishReason, StreamOutcome
from app.features.personal_agents import service as personal_agent_service_module
from app.features.self_management_shared import (
    delegated_conversation_service as delegated_conversation_service_module,
)
from app.features.self_management_shared.self_management_mcp import (
    _MCP_ALLOWED_OPERATION_IDS_STATE_KEY,
    _MCP_USER_ID_STATE_KEY,
    _MCP_WEB_AGENT_CONVERSATION_ID_STATE_KEY,
    SELF_MANAGEMENT_MCP_READONLY_MOUNT_PATH,
    SELF_MANAGEMENT_MCP_READONLY_OPERATION_IDS,
    SelfManagementMcpAuthMiddleware,
    build_self_management_mcp_http_app,
    execute_self_management_mcp_operation,
    self_management_mcp_server,
    self_management_write_mcp_server,
)
from app.main import combine_lifespans
from tests.support.utils import (
    create_a2a_agent,
    create_conversation_thread,
    create_schedule_task,
    create_user,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@asynccontextmanager
async def _app_lifespan(_app: FastAPI):
    yield


async def test_self_management_mcp_server_lists_first_wave_tools() -> None:
    tools = await self_management_mcp_server.list_tools()
    tool_names = {tool.name for tool in tools}

    assert "self.agents.list" in tool_names
    assert "self.agents.get" in tool_names
    assert "self.jobs.list" in tool_names
    assert "self.jobs.get" in tool_names
    assert "self.sessions.list" in tool_names
    assert "self.sessions.get" in tool_names
    assert "self.sessions.get_latest_messages" in tool_names


async def test_self_management_write_mcp_server_lists_write_tools() -> None:
    tools = await self_management_write_mcp_server.list_tools()
    tool_names = {tool.name for tool in tools}

    assert "self.agents.check_health" in tool_names
    assert "self.agents.check_health_all" in tool_names
    assert "self.agents.create" in tool_names
    assert "self.agents.update_config" in tool_names
    assert "self.agents.delete" in tool_names
    assert "self.agents.start_sessions" in tool_names
    assert "self.jobs.create" in tool_names
    assert "self.jobs.pause" in tool_names
    assert "self.jobs.resume" in tool_names
    assert "self.jobs.update" in tool_names
    assert "self.jobs.delete" in tool_names
    assert "self.sessions.update" in tool_names
    assert "self.sessions.archive" in tool_names
    assert "self.sessions.send_message" in tool_names
    assert "self.sessions.unarchive" in tool_names


async def test_execute_self_management_mcp_operation_returns_swival_envelope(
    async_db_session,
) -> None:
    user = await create_user(async_db_session)
    agent = await create_a2a_agent(
        async_db_session,
        user_id=user.id,
        suffix="mcp-jobs",
    )
    task = await create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        prompt="mcp prompt",
    )

    list_result = await execute_self_management_mcp_operation(
        user_id=user.id,
        operation_id="self.jobs.list",
        arguments={"page": 1, "size": 20},
        db=async_db_session,
    )
    get_result = await execute_self_management_mcp_operation(
        user_id=user.id,
        operation_id="self.jobs.get",
        arguments={"task_id": str(task.id)},
        db=async_db_session,
    )

    assert list_result["ok"] is True
    assert any(item["id"] == str(task.id) for item in list_result["result"]["items"])
    assert get_result["ok"] is True
    assert get_result["result"]["job"]["prompt"] == "mcp prompt"


async def test_execute_self_management_mcp_operation_supports_sessions(
    async_db_session,
) -> None:
    user = await create_user(async_db_session)
    thread = await create_conversation_thread(
        async_db_session,
        user_id=user.id,
        title="MCP Session",
    )

    list_result = await execute_self_management_mcp_operation(
        user_id=user.id,
        operation_id="self.sessions.list",
        arguments={"page": 1, "size": 20},
        db=async_db_session,
    )
    get_result = await execute_self_management_mcp_operation(
        user_id=user.id,
        operation_id="self.sessions.get",
        arguments={"conversation_id": str(thread.id)},
        db=async_db_session,
    )

    assert list_result["ok"] is True
    assert any(
        item["conversation_id"] == str(thread.id)
        for item in list_result["result"]["items"]
    )
    assert get_result["ok"] is True
    assert get_result["result"]["session"]["conversation_id"] == str(thread.id)
    assert get_result["result"]["session"]["title"] == "MCP Session"
    assert get_result["result"]["session"]["status"] == "active"


async def test_execute_self_management_mcp_operation_supports_session_latest_messages(
    async_db_session,
) -> None:
    user = await create_user(async_db_session)
    thread = await create_conversation_thread(
        async_db_session,
        user_id=user.id,
        title="Latest Messages Session",
    )

    user_message = AgentMessage(
        user_id=user.id,
        conversation_id=thread.id,
        sender="automation",
        status="done",
        message_metadata={"message_kind": "delegated_agent_message"},
    )
    agent_message = AgentMessage(
        user_id=user.id,
        conversation_id=thread.id,
        sender="agent",
        status="done",
    )
    reasoning_only_message = AgentMessage(
        user_id=user.id,
        conversation_id=thread.id,
        sender="agent",
        status="done",
    )
    async_db_session.add_all([user_message, agent_message, reasoning_only_message])
    await async_db_session.flush()
    async_db_session.add_all(
        [
            AgentMessageBlock(
                user_id=user.id,
                message_id=user_message.id,
                block_seq=1,
                block_type="text",
                content="follow up on the target session",
                is_finished=True,
                source="automation_input",
            ),
            AgentMessageBlock(
                user_id=user.id,
                message_id=agent_message.id,
                block_seq=1,
                block_type="reasoning",
                content="hidden reasoning",
                is_finished=True,
                source="stream",
            ),
            AgentMessageBlock(
                user_id=user.id,
                message_id=agent_message.id,
                block_seq=2,
                block_type="text",
                content="target agent final reply",
                is_finished=True,
                source="final_snapshot",
            ),
            AgentMessageBlock(
                user_id=user.id,
                message_id=reasoning_only_message.id,
                block_seq=1,
                block_type="tool_call",
                content='{"name":"lookup"}',
                is_finished=True,
                source="stream",
            ),
        ]
    )
    await async_db_session.commit()

    result = await execute_self_management_mcp_operation(
        user_id=user.id,
        operation_id="self.sessions.get_latest_messages",
        arguments={
            "conversation_ids": [str(thread.id)],
            "limit_per_session": 2,
        },
        db=async_db_session,
    )

    assert result["ok"] is True
    assert result["result"]["summary"] == {"requested": 1, "available": 1, "failed": 0}
    item = result["result"]["items"][0]
    assert item["conversation_id"] == str(thread.id)
    assert item["status"] == "available"
    assert item["observation_status"] == "snapshot"
    assert item["latest_agent_message_id"] == str(agent_message.id)
    assert item["session"]["title"] == "Latest Messages Session"
    assert [message["content"] for message in item["messages"]] == [
        "follow up on the target session",
        "target agent final reply",
    ]
    assert all("toolCall" not in message for message in item["messages"])


async def test_execute_self_management_mcp_operation_supports_agents(
    async_db_session,
) -> None:
    user = await create_user(async_db_session)
    agent = await create_a2a_agent(
        async_db_session,
        user_id=user.id,
        suffix="mcp-agent",
        tags=["before"],
    )

    list_result = await execute_self_management_mcp_operation(
        user_id=user.id,
        operation_id="self.agents.list",
        arguments={"page": 1, "size": 20, "health_bucket": "all"},
        db=async_db_session,
    )
    get_result = await execute_self_management_mcp_operation(
        user_id=user.id,
        operation_id="self.agents.get",
        arguments={"agent_id": str(agent.id)},
        db=async_db_session,
    )
    update_result = await execute_self_management_mcp_operation(
        user_id=user.id,
        operation_id="self.agents.update_config",
        arguments={
            "agent_id": str(agent.id),
            "name": "MCP Updated Agent",
            "enabled": False,
            "tags": ["after"],
            "extra_headers": {"X-Test": "1"},
            "invoke_metadata_defaults": {"mode": "safe"},
        },
        db=async_db_session,
    )

    assert list_result["ok"] is True
    assert any(item["id"] == str(agent.id) for item in list_result["result"]["items"])
    assert get_result["ok"] is True
    assert get_result["result"]["agent"]["id"] == str(agent.id)
    assert update_result["ok"] is True
    assert update_result["result"]["agent"]["id"] == str(agent.id)
    assert update_result["result"]["agent"]["name"] == "MCP Updated Agent"
    assert update_result["result"]["agent"]["enabled"] is False
    assert update_result["result"]["agent"]["tags"] == ["after"]


async def test_execute_self_management_mcp_operation_supports_agent_health_checks(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await create_user(async_db_session)
    agent = await create_a2a_agent(
        async_db_session,
        user_id=user.id,
        suffix="mcp-agent-health",
    )

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
                    agent_id=agent.id,
                    health_status="healthy",
                    checked_at=agent.updated_at,
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

    single_result = await execute_self_management_mcp_operation(
        user_id=user.id,
        operation_id="self.agents.check_health",
        arguments={"agent_id": str(agent.id), "force": True},
        db=async_db_session,
    )
    all_result = await execute_self_management_mcp_operation(
        user_id=user.id,
        operation_id="self.agents.check_health_all",
        arguments={"force": True},
        db=async_db_session,
    )

    assert single_result["ok"] is True
    assert single_result["result"]["summary"]["requested"] == 1
    assert single_result["result"]["items"][0]["agent_id"] == str(agent.id)
    assert all_result["ok"] is True
    assert all_result["result"]["summary"]["requested"] >= 1
    assert any(
        item["agent_id"] == str(agent.id) for item in all_result["result"]["items"]
    )


async def test_execute_self_management_mcp_operation_supports_agent_create_delete(
    async_db_session,
) -> None:
    user = await create_user(async_db_session)

    create_result = await execute_self_management_mcp_operation(
        user_id=user.id,
        operation_id="self.agents.create",
        arguments={
            "name": "Created via MCP",
            "card_url": "https://example.com/mcp-created/.well-known/agent-card.json",
            "auth_type": "bearer",
            "token": "secret-token",
        },
        db=async_db_session,
    )

    assert create_result["ok"] is True
    created_agent_id = create_result["result"]["agent"]["id"]

    delete_result = await execute_self_management_mcp_operation(
        user_id=user.id,
        operation_id="self.agents.delete",
        arguments={"agent_id": created_agent_id},
        db=async_db_session,
    )

    assert delete_result == {
        "ok": True,
        "result": {"agent_id": created_agent_id, "deleted": True},
    }


async def test_execute_self_management_mcp_operation_supports_job_create_update_delete(
    async_db_session,
) -> None:
    user = await create_user(async_db_session)
    agent = await create_a2a_agent(
        async_db_session,
        user_id=user.id,
        suffix="mcp-job-create",
    )

    create_result = await execute_self_management_mcp_operation(
        user_id=user.id,
        operation_id="self.jobs.create",
        arguments={
            "name": "Created job",
            "agent_id": str(agent.id),
            "prompt": "run it",
            "cycle_type": "daily",
            "time_point": {"time": "10:15"},
            "enabled": True,
        },
        db=async_db_session,
    )

    assert create_result["ok"] is True
    task_id = create_result["result"]["job"]["id"]

    update_result = await execute_self_management_mcp_operation(
        user_id=user.id,
        operation_id="self.jobs.update",
        arguments={
            "task_id": task_id,
            "name": "Updated job",
            "enabled": False,
            "conversation_policy": "reuse_single",
        },
        db=async_db_session,
    )
    delete_result = await execute_self_management_mcp_operation(
        user_id=user.id,
        operation_id="self.jobs.delete",
        arguments={"task_id": task_id},
        db=async_db_session,
    )

    assert update_result["ok"] is True
    assert update_result["result"]["job"]["name"] == "Updated job"
    assert update_result["result"]["job"]["enabled"] is False
    assert update_result["result"]["job"]["conversation_policy"] == "reuse_single"
    assert delete_result == {
        "ok": True,
        "result": {"task_id": task_id, "deleted": True},
    }


async def test_execute_self_management_mcp_operation_rejects_noncanonical_job_conversation_policy(
    async_db_session,
) -> None:
    user = await create_user(async_db_session)
    agent = await create_a2a_agent(
        async_db_session,
        user_id=user.id,
        suffix="mcp-job-policy-invalid",
    )

    create_result = await execute_self_management_mcp_operation(
        user_id=user.id,
        operation_id="self.jobs.create",
        arguments={
            "name": "Aliased policy job",
            "agent_id": str(agent.id),
            "prompt": "run it",
            "cycle_type": "daily",
            "time_point": {"time": "10:15"},
            "conversation_policy": "reuse",
        },
        db=async_db_session,
    )

    assert create_result == {
        "ok": False,
        "error": "conversation_policy must be one of new_each_run, reuse_single",
    }


async def test_execute_self_management_mcp_operation_supports_session_writes(
    async_db_session,
) -> None:
    user = await create_user(async_db_session)
    thread = await create_conversation_thread(
        async_db_session,
        user_id=user.id,
        title="Before",
    )

    update_result = await execute_self_management_mcp_operation(
        user_id=user.id,
        operation_id="self.sessions.update",
        arguments={
            "conversation_id": str(thread.id),
            "title": "After",
        },
        db=async_db_session,
    )
    archive_result = await execute_self_management_mcp_operation(
        user_id=user.id,
        operation_id="self.sessions.archive",
        arguments={"conversation_id": str(thread.id)},
        db=async_db_session,
    )
    unarchive_result = await execute_self_management_mcp_operation(
        user_id=user.id,
        operation_id="self.sessions.unarchive",
        arguments={"conversation_id": str(thread.id)},
        db=async_db_session,
    )

    assert update_result["ok"] is True
    assert update_result["result"]["session"]["title"] == "After"
    assert archive_result["ok"] is True
    assert archive_result["result"]["session"]["status"] == "archived"
    assert unarchive_result["ok"] is True
    assert unarchive_result["result"]["session"]["status"] == "active"


async def test_execute_self_management_mcp_operation_supports_session_send_message(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await create_user(async_db_session)
    thread = await create_conversation_thread(
        async_db_session,
        user_id=user.id,
        title="Delegated Session",
    )

    async def _fake_send_messages_to_sessions(**kwargs):
        assert kwargs["db"] is async_db_session
        assert kwargs["current_user"].id == user.id
        assert kwargs["conversation_ids"] == [thread.id]
        assert kwargs["message"] == "ping"
        return {
            "summary": {"requested": 1, "accepted": 1, "failed": 0},
            "items": [
                {
                    "target_type": "session",
                    "conversation_id": str(thread.id),
                    "status": "accepted",
                }
            ],
        }

    monkeypatch.setattr(
        delegated_conversation_service_module.self_management_delegated_conversation_service,
        "send_messages_to_sessions",
        _fake_send_messages_to_sessions,
    )

    result = await execute_self_management_mcp_operation(
        user_id=user.id,
        operation_id="self.sessions.send_message",
        arguments={
            "conversation_ids": [str(thread.id)],
            "message": "ping",
        },
        db=async_db_session,
    )

    assert result == {
        "ok": True,
        "result": {
            "summary": {"requested": 1, "accepted": 1, "failed": 0},
            "items": [
                {
                    "target_type": "session",
                    "conversation_id": str(thread.id),
                    "status": "accepted",
                }
            ],
        },
    }


async def test_execute_self_management_mcp_operation_supports_agent_start_sessions(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await create_user(async_db_session)
    agent = await create_a2a_agent(
        async_db_session,
        user_id=user.id,
        suffix="mcp-start-sessions",
    )

    async def _fake_start_sessions_for_agents(**kwargs):
        assert kwargs["db"] is async_db_session
        assert kwargs["current_user"].id == user.id
        assert kwargs["agent_ids"] == [agent.id]
        assert kwargs["message"] == "hello"
        return {
            "summary": {"requested": 1, "accepted": 1, "failed": 0},
            "items": [
                {
                    "target_type": "agent",
                    "agent_id": str(agent.id),
                    "status": "accepted",
                }
            ],
        }

    monkeypatch.setattr(
        delegated_conversation_service_module.self_management_delegated_conversation_service,
        "start_sessions_for_agents",
        _fake_start_sessions_for_agents,
    )

    result = await execute_self_management_mcp_operation(
        user_id=user.id,
        operation_id="self.agents.start_sessions",
        arguments={
            "agent_ids": [str(agent.id)],
            "message": "hello",
        },
        db=async_db_session,
    )

    assert result == {
        "ok": True,
        "result": {
            "summary": {"requested": 1, "accepted": 1, "failed": 0},
            "items": [
                {
                    "target_type": "agent",
                    "agent_id": str(agent.id),
                    "status": "accepted",
                }
            ],
        },
    }


async def test_execute_self_management_mcp_operation_persists_delegated_session_send(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await create_user(async_db_session)
    agent = await create_a2a_agent(
        async_db_session,
        user_id=user.id,
        suffix="mcp-delegated-session-e2e",
        name="Delegated Session Agent",
    )
    built_in_thread = await create_conversation_thread(
        async_db_session,
        user_id=user.id,
        title="Built-in Session",
    )
    thread = await create_conversation_thread(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        agent_source="personal",
        title="Delegated Session Thread",
    )
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(
            name="Delegated Session Agent",
            url="https://example.com/a2a",
        )
    )

    async def _fake_load_for_external_call(_db, _loader):
        return runtime

    async def _fake_finalize_outbound_invoke_payload(**kwargs):
        return kwargs["payload"]

    async def _fake_noop(**_kwargs):
        return None

    async def _fake_consume_stream(**kwargs):
        await kwargs["on_event"](
            {
                "kind": "artifact-update",
                "artifact": {
                    "parts": [{"kind": "text", "text": "delegated draft"}],
                    "metadata": {
                        "shared": {
                            "stream": {
                                "block_type": "text",
                                "event_id": "evt-delegated-1",
                                "sequence": 1,
                            }
                        }
                    },
                },
            }
        )
        outcome = StreamOutcome(
            success=True,
            finish_reason=StreamFinishReason.SUCCESS,
            final_text="delegated final",
            error_message=None,
            error_code=None,
            elapsed_seconds=1.0,
            idle_seconds=0.1,
            terminal_event_seen=True,
        )
        await kwargs["on_finalized"](outcome)
        return outcome

    monkeypatch.setattr(
        delegated_conversation_service_module,
        "load_for_external_call",
        _fake_load_for_external_call,
    )
    monkeypatch.setattr(
        delegated_conversation_service_module,
        "get_a2a_service",
        lambda: SimpleNamespace(gateway=object()),
    )
    monkeypatch.setattr(
        invoke_route_runner,
        "_finalize_outbound_invoke_payload",
        _fake_finalize_outbound_invoke_payload,
    )
    monkeypatch.setattr(
        invoke_route_runner,
        "_preempt_previous_invoke_if_requested",
        _fake_noop,
    )
    monkeypatch.setattr(invoke_route_runner, "_register_inflight_invoke", _fake_noop)
    monkeypatch.setattr(invoke_route_runner, "_unregister_inflight_invoke", _fake_noop)
    monkeypatch.setattr(
        invoke_route_runner.a2a_invoke_service,
        "consume_stream",
        _fake_consume_stream,
    )

    result = await execute_self_management_mcp_operation(
        user_id=user.id,
        operation_id="self.sessions.send_message",
        arguments={
            "conversation_ids": [str(thread.id)],
            "message": "ping",
        },
        web_agent_conversation_id=str(built_in_thread.id),
        db=async_db_session,
    )

    assert result["ok"] is True
    assert result["result"]["summary"] == {"requested": 1, "accepted": 1, "failed": 0}
    assert result["result"]["items"][0]["status"] == "accepted"
    await delegated_conversation_service_module.self_management_delegated_conversation_service.drain_pending_tasks()

    automation_message = await async_db_session.scalar(
        select(AgentMessage).where(
            AgentMessage.conversation_id == thread.id,
            AgentMessage.sender == "automation",
        )
    )
    agent_message = await async_db_session.scalar(
        select(AgentMessage).where(
            AgentMessage.conversation_id == thread.id,
            AgentMessage.sender == "agent",
        )
    )
    assert automation_message is not None
    assert agent_message is not None
    assert automation_message.message_metadata["delegated_by"] == (
        "self_management_built_in_agent"
    )
    assert automation_message.message_metadata["delegated_target_kind"] == "session"
    assert automation_message.message_metadata["delegated_target_id"] == str(thread.id)
    assert automation_message.message_metadata["message_kind"] == (
        "delegated_session_message"
    )
    assert agent_message.message_metadata["message_kind"] == "delegated_session_message"

    built_in_messages = list(
        (
            await async_db_session.scalars(
                select(AgentMessage).where(
                    AgentMessage.conversation_id == built_in_thread.id,
                    AgentMessage.sender == "agent",
                )
            )
        ).all()
    )
    handoff_message = next(
        (
            message
            for message in built_in_messages
            if isinstance(message.message_metadata, dict)
            and message.message_metadata.get("message_kind") == "delegation_handoff"
        ),
        None,
    )
    assert handoff_message is not None
    assert handoff_message.message_metadata["delegation"]["status"] == "accepted"
    assert handoff_message.message_metadata["delegation"]["target_type"] == "session"
    assert handoff_message.message_metadata["delegation"][
        "target_conversation_id"
    ] == str(thread.id)
    assert handoff_message.message_metadata["delegation"]["target_agent_id"] == str(
        agent.id
    )
    handoff_block = await async_db_session.scalar(
        select(AgentMessageBlock).where(
            AgentMessageBlock.message_id == handoff_message.id,
        )
    )
    assert handoff_block is not None
    assert str(thread.id) in handoff_block.content
    assert "ping" in handoff_block.content

    persisted_user_block = await async_db_session.scalar(
        select(AgentMessageBlock).where(
            AgentMessageBlock.message_id == automation_message.id,
        )
    )
    assert persisted_user_block is not None
    assert persisted_user_block.content == "ping"
    assert persisted_user_block.source == "automation_input"


async def test_execute_self_management_mcp_operation_persists_delegated_agent_start(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await create_user(async_db_session)
    built_in_thread = await create_conversation_thread(
        async_db_session,
        user_id=user.id,
        title="Built-in Session",
    )
    agent = await create_a2a_agent(
        async_db_session,
        user_id=user.id,
        suffix="mcp-delegated-agent-e2e",
        name="Delegated Agent",
    )
    runtime = SimpleNamespace(
        resolved=SimpleNamespace(
            name="Delegated Agent",
            url="https://example.com/a2a",
        )
    )

    async def _fake_load_for_external_call(_db, _loader):
        return runtime

    async def _fake_finalize_outbound_invoke_payload(**kwargs):
        return kwargs["payload"]

    async def _fake_noop(**_kwargs):
        return None

    async def _fake_consume_stream(**kwargs):
        await kwargs["on_event"](
            {
                "kind": "artifact-update",
                "artifact": {
                    "parts": [{"kind": "text", "text": "agent delegated draft"}],
                    "metadata": {
                        "shared": {
                            "stream": {
                                "block_type": "text",
                                "event_id": "evt-agent-start-1",
                                "sequence": 1,
                            }
                        }
                    },
                },
            }
        )
        outcome = StreamOutcome(
            success=True,
            finish_reason=StreamFinishReason.SUCCESS,
            final_text="agent delegated final",
            error_message=None,
            error_code=None,
            elapsed_seconds=1.0,
            idle_seconds=0.1,
            terminal_event_seen=True,
        )
        await kwargs["on_finalized"](outcome)
        return outcome

    monkeypatch.setattr(
        delegated_conversation_service_module,
        "load_for_external_call",
        _fake_load_for_external_call,
    )
    monkeypatch.setattr(
        delegated_conversation_service_module,
        "get_a2a_service",
        lambda: SimpleNamespace(gateway=object()),
    )
    monkeypatch.setattr(
        invoke_route_runner,
        "_finalize_outbound_invoke_payload",
        _fake_finalize_outbound_invoke_payload,
    )
    monkeypatch.setattr(
        invoke_route_runner,
        "_preempt_previous_invoke_if_requested",
        _fake_noop,
    )
    monkeypatch.setattr(invoke_route_runner, "_register_inflight_invoke", _fake_noop)
    monkeypatch.setattr(invoke_route_runner, "_unregister_inflight_invoke", _fake_noop)
    monkeypatch.setattr(
        invoke_route_runner.a2a_invoke_service,
        "consume_stream",
        _fake_consume_stream,
    )

    result = await execute_self_management_mcp_operation(
        user_id=user.id,
        operation_id="self.agents.start_sessions",
        arguments={
            "agent_ids": [str(agent.id)],
            "message": "hello",
        },
        web_agent_conversation_id=str(built_in_thread.id),
        db=async_db_session,
    )

    assert result["ok"] is True
    assert result["result"]["summary"] == {"requested": 1, "accepted": 1, "failed": 0}
    assert result["result"]["items"][0]["status"] == "accepted"
    await delegated_conversation_service_module.self_management_delegated_conversation_service.drain_pending_tasks()

    automation_message = await async_db_session.scalar(
        select(AgentMessage).where(
            AgentMessage.user_id == user.id,
            AgentMessage.sender == "automation",
        )
    )
    assert automation_message is not None
    assert automation_message.message_metadata["delegated_target_kind"] == "agent"
    assert automation_message.message_metadata["delegated_target_id"] == str(agent.id)
    assert automation_message.message_metadata["message_kind"] == (
        "delegated_agent_message"
    )

    built_in_messages = list(
        (
            await async_db_session.scalars(
                select(AgentMessage).where(
                    AgentMessage.conversation_id == built_in_thread.id,
                    AgentMessage.sender == "agent",
                )
            )
        ).all()
    )
    handoff_message = next(
        (
            message
            for message in built_in_messages
            if isinstance(message.message_metadata, dict)
            and message.message_metadata.get("message_kind") == "delegation_handoff"
        ),
        None,
    )
    assert handoff_message is not None
    assert handoff_message.message_metadata["delegation"]["status"] == "accepted"
    assert handoff_message.message_metadata["delegation"]["target_type"] == "agent"
    assert handoff_message.message_metadata["delegation"]["target_agent_id"] == str(
        agent.id
    )
    assert (
        handoff_message.message_metadata["delegation"]["target_conversation_id"]
        == result["result"]["items"][0]["conversation_id"]
    )
    handoff_block = await async_db_session.scalar(
        select(AgentMessageBlock).where(
            AgentMessageBlock.message_id == handoff_message.id,
        )
    )
    assert handoff_block is not None
    assert result["result"]["items"][0]["conversation_id"] in handoff_block.content
    assert "hello" in handoff_block.content


async def test_self_management_mcp_http_app_requires_bearer_auth(
    async_db_session,
) -> None:
    await create_user(async_db_session)
    mcp_app = build_self_management_mcp_http_app(
        operation_ids=SELF_MANAGEMENT_MCP_READONLY_OPERATION_IDS
    )
    app = FastAPI(lifespan=combine_lifespans(_app_lifespan, mcp_app.lifespan))
    app.mount(SELF_MANAGEMENT_MCP_READONLY_MOUNT_PATH, mcp_app)

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        missing = await client.get(f"{SELF_MANAGEMENT_MCP_READONLY_MOUNT_PATH}/")
        invalid = await client.get(
            f"{SELF_MANAGEMENT_MCP_READONLY_MOUNT_PATH}/",
            headers={"Authorization": "Bearer invalid-token"},
        )

    assert missing.status_code == 401
    assert missing.json()["detail"] == "Missing or invalid Authorization header"
    assert invalid.status_code == 401
    assert invalid.json()["detail"] == "Invalid or expired token"


async def test_self_management_mcp_auth_middleware_accepts_valid_bearer_auth(
    async_db_session,
) -> None:
    user = await create_user(async_db_session)
    token = create_self_management_access_token(
        user.id,
        allowed_operations=sorted(SELF_MANAGEMENT_MCP_READONLY_OPERATION_IDS),
        delegated_by="test",
        conversation_id="builtin-conv-1",
    )
    app = FastAPI()
    app.add_middleware(
        SelfManagementMcpAuthMiddleware,
        default_allowed_operation_ids=SELF_MANAGEMENT_MCP_READONLY_OPERATION_IDS,
        require_delegated_claims=True,
    )

    @app.get("/")
    async def read_root(request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "user_id": str(
                    getattr(request.state, _MCP_USER_ID_STATE_KEY, ""),
                ),
                "allowed_operation_ids": sorted(
                    getattr(
                        request.state, _MCP_ALLOWED_OPERATION_IDS_STATE_KEY, frozenset()
                    )
                ),
                "conversation_id": getattr(
                    request.state, _MCP_WEB_AGENT_CONVERSATION_ID_STATE_KEY, None
                ),
            }
        )

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            "/",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert response.json()["user_id"] == str(user.id)
    assert response.json()["conversation_id"] == "builtin-conv-1"
    assert response.json()["allowed_operation_ids"] == sorted(
        SELF_MANAGEMENT_MCP_READONLY_OPERATION_IDS
    )


async def test_execute_self_management_mcp_operation_rejects_unapproved_operation(
    async_db_session,
) -> None:
    user = await create_user(async_db_session)
    agent = await create_a2a_agent(
        async_db_session,
        user_id=user.id,
        suffix="mcp-agent-denied",
    )

    result = await execute_self_management_mcp_operation(
        user_id=user.id,
        operation_id="self.agents.update_config",
        arguments={"agent_id": str(agent.id), "name": "Denied"},
        allowed_operation_ids=SELF_MANAGEMENT_MCP_READONLY_OPERATION_IDS,
        db=async_db_session,
    )

    assert result == {
        "ok": False,
        "error": (
            "Operation `self.agents.update_config` is not authorized for this MCP session."
        ),
    }
