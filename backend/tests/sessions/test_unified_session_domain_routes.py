from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import quote
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db.models.a2a_schedule_execution import A2AScheduleExecution
from app.db.models.agent_message import AgentMessage
from app.db.models.agent_message_block import AgentMessageBlock
from app.db.models.conversation_thread import ConversationThread
from app.db.models.conversation_upstream_task import ConversationUpstreamTask
from app.features.schedules.service import a2a_schedule_service
from app.features.sessions import router as me_sessions
from app.features.sessions.common import serialize_interrupt_event_block_content
from app.features.sessions.service import session_hub_service
from app.utils.timezone_util import utc_now
from tests.support.api_utils import create_test_client
from tests.support.utils import create_a2a_agent, create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_create_agent = create_a2a_agent


async def test_conversation_routes_use_conversation_id_only(
    async_db_session,
    async_session_maker,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="conv-only")

    now = utc_now()
    manual_session = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        agent_id=agent.id,
        agent_source="personal",
        title="Manual Thread",
        last_active_at=now,
        status=ConversationThread.STATUS_ACTIVE,
    )
    scheduled_session = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_SCHEDULED,
        agent_id=agent.id,
        agent_source="personal",
        title="Scheduled Thread",
        last_active_at=now - timedelta(minutes=10),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(manual_session)
    async_db_session.add(scheduled_session)
    await async_db_session.flush()

    task = await a2a_schedule_service.create_task(
        async_db_session,
        user_id=user.id,
        is_superuser=user.is_superuser,
        timezone_str=user.timezone or "UTC",
        name="Nightly",
        agent_id=agent.id,
        prompt="ping",
        cycle_type="daily",
        time_point={"time": "00:00"},
        enabled=False,
    )
    task.conversation_id = scheduled_session.id

    execution = A2AScheduleExecution(
        user_id=user.id,
        task_id=task.id,
        run_id=uuid4(),
        conversation_id=scheduled_session.id,
        scheduled_for=now - timedelta(minutes=1),
        started_at=now - timedelta(minutes=1),
        finished_at=now,
        status=A2AScheduleExecution.STATUS_SUCCESS,
        response_content="ok",
    )
    async_db_session.add(execution)

    user_message = AgentMessage(
        user_id=user.id,
        sender="user",
        conversation_id=manual_session.id,
        message_metadata={"contextId": "ctx-manual-1"},
    )
    agent_message = AgentMessage(
        user_id=user.id,
        sender="agent",
        conversation_id=manual_session.id,
        message_metadata={"contextId": "ctx-manual-1"},
    )
    async_db_session.add(user_message)
    async_db_session.add(agent_message)
    await async_db_session.flush()
    async_db_session.add(
        AgentMessageBlock(
            user_id=user.id,
            message_id=user_message.id,
            block_seq=1,
            block_type="text",
            content="hello",
            is_finished=True,
            source="user_input",
        )
    )
    agent_text_block = AgentMessageBlock(
        user_id=user.id,
        message_id=agent_message.id,
        block_seq=1,
        block_type="text",
        content="world",
        start_event_seq=1,
        end_event_seq=1,
        start_event_id="evt-route-1",
        end_event_id="evt-route-1",
        is_finished=True,
        source="stream",
    )
    agent_reasoning_block = AgentMessageBlock(
        user_id=user.id,
        message_id=agent_message.id,
        block_seq=2,
        block_type="reasoning",
        content="internal-thought",
        is_finished=True,
        source="stream",
    )
    async_db_session.add(agent_text_block)
    async_db_session.add(agent_reasoning_block)
    await async_db_session.commit()

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        list_resp = await client.post(
            "/me/conversations:query",
            json={"page": 1, "size": 50},
        )
        assert list_resp.status_code == 200
        list_payload = list_resp.json()

        conversation_ids = {item["conversationId"] for item in list_payload["items"]}
        assert str(manual_session.id) in conversation_ids
        assert str(scheduled_session.id) in conversation_ids
        assert all("id" not in item for item in list_payload["items"])

        messages_resp = await client.post(
            f"/me/conversations/{manual_session.id}/messages:query",
            json={"limit": 8},
        )
        assert messages_resp.status_code == 200
        messages_payload = messages_resp.json()
        assert len(messages_payload["items"]) == 2
        messages_user_item = next(
            item for item in messages_payload["items"] if item["role"] == "user"
        )
        messages_agent_item = next(
            item for item in messages_payload["items"] if item["role"] == "agent"
        )
        assert messages_user_item["id"] == str(user_message.id)
        assert messages_agent_item["id"] == str(agent_message.id)
        assert messages_user_item["content"] == "hello"
        assert messages_agent_item["content"] == "world"
        assert len(messages_user_item["blocks"]) == 1
        assert len(messages_agent_item["blocks"]) == 2
        assert messages_agent_item["blocks"][0]["content"] == "world"
        assert messages_agent_item["blocks"][1]["type"] == "reasoning"
        assert messages_agent_item["blocks"][1]["content"] == ""
        assert messages_payload["pageInfo"]["hasMoreBefore"] is False
        assert messages_payload["pageInfo"]["nextBefore"] is None

        block_detail_resp = await client.post(
            f"/me/conversations/{manual_session.id}/blocks:query",
            json={"blockIds": [str(agent_reasoning_block.id)]},
        )
        assert block_detail_resp.status_code == 200
        block_detail_payload = block_detail_resp.json()
        assert len(block_detail_payload["items"]) == 1
        assert block_detail_payload["items"][0]["id"] == str(agent_reasoning_block.id)
        assert block_detail_payload["items"][0]["messageId"] == str(agent_message.id)
        assert block_detail_payload["items"][0]["type"] == "reasoning"
        assert block_detail_payload["items"][0]["content"] == "internal-thought"
        assert block_detail_payload["items"][0]["isFinished"] is True

        continue_resp = await client.post(
            f"/me/conversations/{manual_session.id}:continue"
        )
        assert continue_resp.status_code == 200
        continue_payload = continue_resp.json()
        assert continue_payload["conversationId"] == str(manual_session.id)
        assert continue_payload["source"] == "manual"
        assert "session_id" not in continue_payload


async def test_continue_includes_opencode_session_metadata(
    async_db_session,
    async_session_maker,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="binding")

    session = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        agent_id=agent.id,
        agent_source="personal",
        external_provider="opencode",
        external_session_id="ses_upstream_1",
        context_id="ctx-bound-1",
        title="Manual Thread",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(session)
    await async_db_session.flush()

    bound_message = AgentMessage(
        user_id=user.id,
        sender="agent",
        conversation_id=session.id,
        message_metadata={
            "contextId": "ctx-bound-1",
            "shared": {
                "session": {
                    "id": "ses_upstream_1",
                    "provider": "opencode",
                }
            },
        },
    )
    async_db_session.add(bound_message)
    await async_db_session.flush()
    async_db_session.add(
        AgentMessageBlock(
            user_id=user.id,
            message_id=bound_message.id,
            block_seq=1,
            block_type="text",
            content="bound",
            is_finished=True,
            source="finalize_snapshot",
        )
    )
    await async_db_session.commit()

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(f"/me/conversations/{session.id}:continue")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["conversationId"] == str(session.id)
        assert payload["source"] == "manual"
        assert payload.get("metadata", {}).get("contextId") == "ctx-bound-1"
        assert payload.get("metadata", {}).get("shared", {}).get("session") == {
            "id": "ses_upstream_1",
            "provider": "opencode",
        }


async def test_invalid_conversation_id_returns_400(
    async_db_session,
    async_session_maker,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(
            "/me/conversations/not-a-uuid/messages:query",
            json={"limit": 8},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "invalid_conversation_id"


async def test_invalid_messages_cursor_returns_400(
    async_db_session,
    async_session_maker,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    conversation_id = uuid4()

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(
            f"/me/conversations/{conversation_id}/messages:query",
            json={"before": "not-valid-cursor", "limit": 8},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "invalid_before_cursor"


async def test_append_route_persists_canonical_user_message(
    async_db_session,
    async_session_maker,
    monkeypatch: pytest.MonkeyPatch,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="append")
    session = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        agent_id=agent.id,
        agent_source="personal",
        external_provider="opencode",
        external_session_id="ses-append-1",
        title="Append Session",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(session)
    await async_db_session.commit()
    operation_id = str(uuid4())
    user_message_id = str(uuid4())
    extension_calls: list[dict[str, object]] = []

    class _FakeExtensions:
        async def append_session_control(self, **kwargs):
            extension_calls.append(kwargs)
            assert kwargs["session_id"] == "ses-append-1"
            assert kwargs["request_payload"]["parts"][0]["text"] == "append this"
            return SimpleNamespace(
                success=True,
                result={"ok": True, "session_id": "ses-append-1"},
                error_code=None,
            )

    async def _fake_load_runtime_for_thread(**kwargs):
        assert kwargs["thread"].id == session.id
        return SimpleNamespace(resolved=SimpleNamespace(url="https://example.com"))

    monkeypatch.setattr(
        me_sessions, "_load_runtime_for_thread", _fake_load_runtime_for_thread
    )
    monkeypatch.setattr(
        me_sessions,
        "get_a2a_extensions_service",
        lambda: _FakeExtensions(),
    )

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        append_resp = await client.post(
            f"/me/conversations/{session.id}/messages:append",
            json={
                "content": "append this",
                "userMessageId": user_message_id,
                "operationId": operation_id,
            },
        )
        assert append_resp.status_code == 200
        append_payload = append_resp.json()
        assert append_payload["conversationId"] == str(session.id)
        assert append_payload["userMessage"]["role"] == "user"
        assert append_payload["userMessage"]["kind"] == "session_append_user"
        assert append_payload["userMessage"]["content"] == "append this"
        assert append_payload["userMessage"]["operationId"] == operation_id
        assert append_payload["sessionControl"] == {
            "intent": "append",
            "status": "accepted",
            "sessionId": "ses-append-1",
        }
        replay_resp = await client.post(
            f"/me/conversations/{session.id}/messages:append",
            json={
                "content": "append this",
                "userMessageId": user_message_id,
                "operationId": operation_id,
            },
        )
        assert replay_resp.status_code == 200
        replay_payload = replay_resp.json()
        assert (
            replay_payload["userMessage"]["id"] == append_payload["userMessage"]["id"]
        )
        assert len(extension_calls) == 1

        messages_resp = await client.post(
            f"/me/conversations/{session.id}/messages:query",
            json={"limit": 8},
        )
        assert messages_resp.status_code == 200
        items = messages_resp.json()["items"]
        assert len(items) == 1
        assert items[0]["id"] == append_payload["userMessage"]["id"]
        assert items[0]["kind"] == "session_append_user"
        assert items[0]["content"] == "append this"
        assert items[0]["operationId"] == operation_id

    session.external_session_id = None
    await async_db_session.commit()

    async def _replay_runtime_should_not_run(**kwargs):
        raise AssertionError("replay should not load runtime")

    monkeypatch.setattr(
        me_sessions, "_load_runtime_for_thread", _replay_runtime_should_not_run
    )

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        replay_without_binding_resp = await client.post(
            f"/me/conversations/{session.id}/messages:append",
            json={
                "content": "append this",
                "userMessageId": user_message_id,
                "operationId": operation_id,
            },
        )
        assert replay_without_binding_resp.status_code == 200
        assert (
            replay_without_binding_resp.json()["userMessage"]["id"]
            == append_payload["userMessage"]["id"]
        )


async def test_command_route_persists_canonical_command_messages(
    async_db_session,
    async_session_maker,
    monkeypatch: pytest.MonkeyPatch,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="command")
    session = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        agent_id=agent.id,
        agent_source="personal",
        external_provider="opencode",
        external_session_id="ses-command-1",
        title="Command Session",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(session)
    await async_db_session.commit()
    operation_id = str(uuid4())
    user_message_id = str(uuid4())
    agent_message_id = str(uuid4())
    extension_calls: list[dict[str, object]] = []

    class _FakeExtensions:
        async def command_session(self, **kwargs):
            extension_calls.append(kwargs)
            assert kwargs["session_id"] == "ses-command-1"
            assert kwargs["request_payload"]["command"] == "/review"
            assert kwargs["request_payload"]["arguments"] == "--quick"
            return SimpleNamespace(
                success=True,
                result={
                    "item": {
                        "messageId": "upstream-msg-1",
                        "role": "agent",
                        "parts": [
                            {"type": "text", "text": "Review complete."},
                            {
                                "type": "data",
                                "data": {
                                    "summary": "done",
                                    "files": ["backend/app.py"],
                                },
                            },
                        ],
                    }
                },
                error_code=None,
            )

    async def _fake_load_runtime_for_thread(**kwargs):
        assert kwargs["thread"].id == session.id
        return SimpleNamespace(resolved=SimpleNamespace(url="https://example.com"))

    monkeypatch.setattr(
        me_sessions, "_load_runtime_for_thread", _fake_load_runtime_for_thread
    )
    monkeypatch.setattr(
        me_sessions,
        "get_a2a_extensions_service",
        lambda: _FakeExtensions(),
    )

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        command_resp = await client.post(
            f"/me/conversations/{session.id}/commands:run",
            json={
                "command": "/review",
                "arguments": "--quick",
                "prompt": "Focus on tests",
                "userMessageId": user_message_id,
                "agentMessageId": agent_message_id,
                "operationId": operation_id,
            },
        )
        assert command_resp.status_code == 200
        command_payload = command_resp.json()
        assert command_payload["conversationId"] == str(session.id)
        assert (
            command_payload["userMessage"]["content"]
            == "/review --quick\nFocus on tests"
        )
        assert command_payload["userMessage"]["kind"] == "session_command_input"
        assert command_payload["userMessage"]["operationId"] == operation_id
        assert command_payload["agentMessage"]["content"] == "Review complete."
        assert command_payload["agentMessage"]["kind"] == "session_command_output"
        assert command_payload["agentMessage"]["operationId"] == operation_id
        assert [
            block["type"] for block in command_payload["agentMessage"]["blocks"]
        ] == [
            "text",
            "data",
        ]
        replay_resp = await client.post(
            f"/me/conversations/{session.id}/commands:run",
            json={
                "command": "/review",
                "arguments": "--quick",
                "prompt": "Focus on tests",
                "userMessageId": user_message_id,
                "agentMessageId": agent_message_id,
                "operationId": operation_id,
            },
        )
        assert replay_resp.status_code == 200
        replay_payload = replay_resp.json()
        assert (
            replay_payload["userMessage"]["id"] == command_payload["userMessage"]["id"]
        )
        assert (
            replay_payload["agentMessage"]["id"]
            == command_payload["agentMessage"]["id"]
        )
        assert len(extension_calls) == 1

        messages_resp = await client.post(
            f"/me/conversations/{session.id}/messages:query",
            json={"limit": 8},
        )
        assert messages_resp.status_code == 200
        items = messages_resp.json()["items"]
        assert [item["id"] for item in items] == [
            command_payload["userMessage"]["id"],
            command_payload["agentMessage"]["id"],
        ]
        assert [item["kind"] for item in items] == [
            "session_command_input",
            "session_command_output",
        ]
        assert items[0]["content"] == "/review --quick\nFocus on tests"
        assert items[1]["content"] == "Review complete."
        assert items[1]["operationId"] == operation_id
        assert [block["type"] for block in items[1]["blocks"]] == ["text", "data"]

    session.external_session_id = None
    await async_db_session.commit()

    async def _replay_runtime_should_not_run(**kwargs):
        raise AssertionError("replay should not load runtime")

    monkeypatch.setattr(
        me_sessions, "_load_runtime_for_thread", _replay_runtime_should_not_run
    )

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        replay_without_binding_resp = await client.post(
            f"/me/conversations/{session.id}/commands:run",
            json={
                "command": "/review",
                "arguments": "--quick",
                "prompt": "Focus on tests",
                "userMessageId": user_message_id,
                "agentMessageId": agent_message_id,
                "operationId": operation_id,
            },
        )
        assert replay_without_binding_resp.status_code == 200
        assert (
            replay_without_binding_resp.json()["agentMessage"]["id"]
            == command_payload["agentMessage"]["id"]
        )


async def test_upstream_task_route_fetches_task_for_bound_conversation(
    async_db_session,
    async_session_maker,
    monkeypatch: pytest.MonkeyPatch,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="task-query")
    session = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        agent_id=agent.id,
        agent_source="personal",
        external_provider="opencode",
        external_session_id="ses-task-1",
        title="Task Query Session",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(session)
    await async_db_session.flush()
    await session_hub_service.record_upstream_task_binding(
        async_db_session,
        user_id=user.id,
        conversation_id=session.id,
        task_id="task-1",
        agent_id=agent.id,
        agent_source="personal",
        source="stream_identity",
    )
    await async_db_session.commit()

    resolved = SimpleNamespace(
        name="TaskAgent",
        url="https://example.com/a2a",
        headers={},
        metadata={},
    )
    calls: list[dict[str, object]] = []

    async def _fake_load_runtime_for_thread(**kwargs):
        assert kwargs["thread"].id == session.id
        return SimpleNamespace(resolved=resolved)

    class _FakeA2AService:
        async def get_task(self, **kwargs):
            calls.append(kwargs)
            return {
                "success": True,
                "task_id": "task-1",
                "task": {
                    "id": "task-1",
                    "status": {"state": "working"},
                },
            }

    monkeypatch.setattr(
        me_sessions, "_load_runtime_for_thread", _fake_load_runtime_for_thread
    )
    monkeypatch.setattr(me_sessions, "get_a2a_service", lambda: _FakeA2AService())

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.get(
            f"/me/conversations/{session.id}/upstream-tasks/task-1",
            params={"historyLength": 3},
        )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload == {
        "conversationId": str(session.id),
        "taskId": "task-1",
        "task": {
            "id": "task-1",
            "status": {"state": "working"},
        },
    }
    assert calls == [
        {
            "resolved": resolved,
            "task_id": "task-1",
            "history_length": 3,
            "metadata": {
                "shared": {
                    "session": {
                        "id": "ses-task-1",
                        "provider": "opencode",
                    }
                },
            },
        }
    ]


async def test_upstream_task_route_accepts_opaque_task_ids_with_slashes(
    async_db_session,
    async_session_maker,
    monkeypatch: pytest.MonkeyPatch,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session,
        user_id=user.id,
        suffix="task-query-slash",
    )
    session = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        agent_id=agent.id,
        agent_source="personal",
        external_provider="opencode",
        external_session_id="ses-task-slash",
        title="Task Query Slash Session",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(session)
    await async_db_session.flush()
    task_id = "run/task-1/step-2"
    await session_hub_service.record_upstream_task_binding(
        async_db_session,
        user_id=user.id,
        conversation_id=session.id,
        task_id=task_id,
        agent_id=agent.id,
        agent_source="personal",
        source="stream_identity",
    )
    await async_db_session.commit()

    resolved = SimpleNamespace(
        name="TaskAgent",
        url="https://example.com/a2a",
        headers={},
        metadata={},
    )
    calls: list[dict[str, object]] = []

    async def _fake_load_runtime_for_thread(**kwargs):
        assert kwargs["thread"].id == session.id
        return SimpleNamespace(resolved=resolved)

    class _FakeA2AService:
        async def get_task(self, **kwargs):
            calls.append(kwargs)
            return {
                "success": True,
                "task_id": task_id,
                "task": {
                    "id": task_id,
                    "status": {"state": "working"},
                },
            }

    monkeypatch.setattr(
        me_sessions, "_load_runtime_for_thread", _fake_load_runtime_for_thread
    )
    monkeypatch.setattr(me_sessions, "get_a2a_service", lambda: _FakeA2AService())

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.get(
            f"/me/conversations/{session.id}/upstream-tasks/{quote(task_id, safe='')}"
        )

    assert resp.status_code == 200
    assert resp.json()["taskId"] == task_id
    assert calls[0]["task_id"] == task_id


@pytest.mark.parametrize(
    ("error_code", "expected_status"),
    [
        ("invalid_task_id", 400),
        ("task_not_found", 404),
        ("unsupported_operation", 501),
        ("timeout", 504),
    ],
)
async def test_upstream_task_route_maps_a2a_service_errors(
    async_db_session,
    async_session_maker,
    monkeypatch: pytest.MonkeyPatch,
    error_code: str,
    expected_status: int,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session,
        user_id=user.id,
        suffix=f"task-{error_code}",
    )
    session = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        agent_id=agent.id,
        agent_source="personal",
        title="Task Error Session",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(session)
    await async_db_session.flush()
    await session_hub_service.record_upstream_task_binding(
        async_db_session,
        user_id=user.id,
        conversation_id=session.id,
        task_id="task-1",
        agent_id=agent.id,
        agent_source="personal",
        source="stream_identity",
    )
    await async_db_session.commit()

    async def _fake_load_runtime_for_thread(**_kwargs):
        return SimpleNamespace(
            resolved=SimpleNamespace(
                name="TaskAgent",
                url="https://example.com/a2a",
                headers={},
                metadata={},
            )
        )

    class _FakeA2AService:
        async def get_task(self, **_kwargs):
            return {
                "success": False,
                "task_id": "task-1",
                "error": error_code,
                "error_code": error_code,
            }

    monkeypatch.setattr(
        me_sessions, "_load_runtime_for_thread", _fake_load_runtime_for_thread
    )
    monkeypatch.setattr(me_sessions, "get_a2a_service", lambda: _FakeA2AService())

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.get(f"/me/conversations/{session.id}/upstream-tasks/task-1")

    assert resp.status_code == expected_status
    assert resp.json()["detail"] == error_code


async def test_upstream_task_route_rejects_unbound_task_without_upstream_call(
    async_db_session,
    async_session_maker,
    monkeypatch: pytest.MonkeyPatch,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session, user_id=user.id, suffix="task-unbound"
    )
    session = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        agent_id=agent.id,
        agent_source="personal",
        title="Task Unbound Session",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(session)
    await async_db_session.commit()

    async def _runtime_should_not_load(**_kwargs):
        raise AssertionError("unbound tasks should not load runtime")

    monkeypatch.setattr(
        me_sessions, "_load_runtime_for_thread", _runtime_should_not_load
    )

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.get(
            f"/me/conversations/{session.id}/upstream-tasks/task-unbound"
        )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "task_not_found"


async def test_upstream_task_route_rejects_task_bound_to_another_conversation(
    async_db_session,
    async_session_maker,
    monkeypatch: pytest.MonkeyPatch,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="task-cross")
    now = utc_now()
    first_session = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        agent_id=agent.id,
        agent_source="personal",
        title="Task Owner Session",
        last_active_at=now,
        status=ConversationThread.STATUS_ACTIVE,
    )
    second_session = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        agent_id=agent.id,
        agent_source="personal",
        title="Task Other Session",
        last_active_at=now,
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(first_session)
    async_db_session.add(second_session)
    await async_db_session.flush()
    await session_hub_service.record_upstream_task_binding(
        async_db_session,
        user_id=user.id,
        conversation_id=first_session.id,
        task_id="task-owned",
        agent_id=agent.id,
        agent_source="personal",
        source="stream_identity",
    )
    await async_db_session.commit()

    async def _runtime_should_not_load(**_kwargs):
        raise AssertionError("cross-conversation tasks should not load runtime")

    monkeypatch.setattr(
        me_sessions, "_load_runtime_for_thread", _runtime_should_not_load
    )

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.get(
            f"/me/conversations/{second_session.id}/upstream-tasks/task-owned"
        )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "task_not_found"


async def test_upstream_task_binding_upsert_preserves_first_seen_and_updates_latest(
    async_db_session,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="task-upsert")
    session = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        agent_id=agent.id,
        agent_source="personal",
        title="Task Upsert Session",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(session)
    await async_db_session.flush()
    first_message = AgentMessage(
        id=uuid4(),
        user_id=user.id,
        sender="agent",
        conversation_id=session.id,
        status="streaming",
    )
    latest_message = AgentMessage(
        id=uuid4(),
        user_id=user.id,
        sender="agent",
        conversation_id=session.id,
        status="done",
    )
    async_db_session.add(first_message)
    async_db_session.add(latest_message)
    await async_db_session.flush()

    first_binding = await session_hub_service.record_upstream_task_binding(
        async_db_session,
        user_id=user.id,
        conversation_id=session.id,
        task_id="task-upsert-1",
        agent_id=agent.id,
        agent_source="personal",
        message_id=first_message.id,
        source="stream_identity",
        status_hint="streaming",
    )
    second_binding = await session_hub_service.record_upstream_task_binding(
        async_db_session,
        user_id=user.id,
        conversation_id=session.id,
        task_id="task-upsert-1",
        agent_id=agent.id,
        agent_source="personal",
        message_id=latest_message.id,
        source="final_metadata",
        status_hint="done",
    )
    await async_db_session.flush()

    assert first_binding is True
    assert second_binding is True
    bindings = list(
        (
            await async_db_session.scalars(
                select(ConversationUpstreamTask).where(
                    ConversationUpstreamTask.conversation_id == session.id,
                    ConversationUpstreamTask.upstream_task_id == "task-upsert-1",
                )
            )
        ).all()
    )
    assert len(bindings) == 1
    binding = bindings[0]
    assert binding.first_seen_message_id == first_message.id
    assert binding.latest_message_id == latest_message.id
    assert binding.source == "final_metadata"
    assert binding.status_hint == "done"


async def test_blocks_query_returns_404_when_block_not_found(
    async_db_session,
    async_session_maker,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    conversation_id = uuid4()

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(
            f"/me/conversations/{conversation_id}/blocks:query",
            json={"blockIds": [str(uuid4())]},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "block_not_found"


async def test_blocks_query_rejects_cross_conversation_block(
    async_db_session,
    async_session_maker,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="cross-block")
    now = utc_now()

    source_session = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        agent_id=agent.id,
        agent_source="personal",
        title="Source Thread",
        last_active_at=now,
        status=ConversationThread.STATUS_ACTIVE,
    )
    target_session = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        agent_id=agent.id,
        agent_source="personal",
        title="Target Thread",
        last_active_at=now - timedelta(minutes=1),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(source_session)
    async_db_session.add(target_session)
    await async_db_session.flush()

    source_message = AgentMessage(
        user_id=user.id,
        sender="agent",
        conversation_id=source_session.id,
    )
    async_db_session.add(source_message)
    await async_db_session.flush()

    source_block = AgentMessageBlock(
        user_id=user.id,
        message_id=source_message.id,
        block_seq=1,
        block_type="tool_call",
        content='{"tool":"search"}',
        is_finished=True,
        source="stream",
    )
    async_db_session.add(source_block)
    await async_db_session.commit()

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(
            f"/me/conversations/{target_session.id}/blocks:query",
            json={"blockIds": [str(source_block.id)]},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "block_not_found"


async def test_tool_call_blocks_expose_normalized_tool_call_view(
    async_db_session,
    async_session_maker,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="tool-call")
    now = utc_now()

    session = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        agent_id=agent.id,
        agent_source="personal",
        title="Tool Call Thread",
        last_active_at=now,
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(session)
    await async_db_session.flush()

    agent_message = AgentMessage(
        user_id=user.id,
        sender="agent",
        conversation_id=session.id,
        status="done",
    )
    async_db_session.add(agent_message)
    await async_db_session.flush()

    tool_block = AgentMessageBlock(
        user_id=user.id,
        message_id=agent_message.id,
        block_seq=1,
        block_type="tool_call",
        content=(
            '{"call_id":"call-1","tool":"bash","status":"pending","input":{}}'
            '{"call_id":"call-1","tool":"bash","status":"running",'
            '"input":{"command":"pwd","description":"Inspect repository state."}}'
            '{"call_id":"call-1","tool":"bash","status":"completed",'
            '"title":"Inspect repository state.","output":"main\\nclean"}'
        ),
        is_finished=True,
        source="stream",
    )
    async_db_session.add(tool_block)
    await async_db_session.commit()

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        messages_resp = await client.post(
            f"/me/conversations/{session.id}/messages:query",
            json={"limit": 8},
        )
        assert messages_resp.status_code == 200
        message_blocks = messages_resp.json()["items"][0]["blocks"]
        assert message_blocks[0]["type"] == "tool_call"
        assert message_blocks[0]["content"] == ""
        assert message_blocks[0]["toolCall"] == {
            "name": "bash",
            "status": "success",
            "callId": "call-1",
            "arguments": {
                "command": "pwd",
                "description": "Inspect repository state.",
            },
            "result": "main\nclean",
            "error": None,
        }

        detail_resp = await client.post(
            f"/me/conversations/{session.id}/blocks:query",
            json={"blockIds": [str(tool_block.id)]},
        )
        assert detail_resp.status_code == 200
        detail_item = detail_resp.json()["items"][0]
        assert detail_item["id"] == str(tool_block.id)
        assert detail_item["messageId"] == str(agent_message.id)
        assert detail_item["content"] == (
            '{"call_id":"call-1","tool":"bash","status":"pending","input":{}}'
            '{"call_id":"call-1","tool":"bash","status":"running",'
            '"input":{"command":"pwd","description":"Inspect repository state."}}'
            '{"call_id":"call-1","tool":"bash","status":"completed",'
            '"title":"Inspect repository state.","output":"main\\nclean"}'
        )
        assert detail_item["toolCall"] == {
            "name": "bash",
            "status": "success",
            "callId": "call-1",
            "arguments": {
                "command": "pwd",
                "description": "Inspect repository state.",
            },
            "result": "main\nclean",
            "error": None,
        }
        assert detail_item["toolCallDetail"] == {
            "name": "bash",
            "status": "success",
            "callId": "call-1",
            "title": "Inspect repository state.",
            "arguments": {
                "command": "pwd",
                "description": "Inspect repository state.",
            },
            "result": "main\nclean",
            "error": None,
            "timeline": [
                {
                    "status": "pending",
                    "title": None,
                    "input": {},
                    "output": None,
                    "error": None,
                },
                {
                    "status": "running",
                    "title": "Inspect repository state.",
                    "input": {
                        "command": "pwd",
                        "description": "Inspect repository state.",
                    },
                    "output": None,
                    "error": None,
                },
                {
                    "status": "completed",
                    "title": "Inspect repository state.",
                    "input": None,
                    "output": "main\nclean",
                    "error": None,
                },
            ],
            "raw": (
                '{"call_id":"call-1","tool":"bash","status":"pending","input":{}}'
                '{"call_id":"call-1","tool":"bash","status":"running",'
                '"input":{"command":"pwd","description":"Inspect repository state."}}'
                '{"call_id":"call-1","tool":"bash","status":"completed",'
                '"title":"Inspect repository state.","output":"main\\nclean"}'
            ),
        }


async def test_legacy_timeline_and_blocks_routes_are_removed(
    async_db_session,
    async_session_maker,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    conversation_id = uuid4()

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(
            f"/me/conversations/{conversation_id}/messages/timeline:query",
            json={"limit": 8},
        )
        assert resp.status_code == 404

        resp = await client.post(
            f"/me/conversations/{conversation_id}/messages/blocks:query",
            json={"messageIds": [str(uuid4())], "mode": "full"},
        )
        assert resp.status_code == 404

        resp = await client.post(
            f"/me/conversations/{conversation_id}/messages/{uuid4()}/blocks/1:query",
        )
        assert resp.status_code == 404


async def test_list_sessions_filters_use_conversation_source_only(
    async_db_session,
    async_session_maker,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="op-filter")

    session = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        agent_id=agent.id,
        agent_source="personal",
        external_provider="opencode",
        external_session_id="ses_filter_1",
        context_id="ctx-filter-1",
        title="Bound Session",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(session)
    await async_db_session.flush()
    bound_message = AgentMessage(
        user_id=user.id,
        sender="agent",
        conversation_id=session.id,
        message_metadata={
            "contextId": "ctx-filter-1",
            "shared": {
                "session": {
                    "id": "ses_filter_1",
                    "provider": "opencode",
                }
            },
        },
    )
    async_db_session.add(bound_message)
    await async_db_session.flush()
    async_db_session.add(
        AgentMessageBlock(
            user_id=user.id,
            message_id=bound_message.id,
            block_seq=1,
            block_type="text",
            content="bound",
            is_finished=True,
            source="finalize_snapshot",
        )
    )
    await async_db_session.commit()

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        manual_resp = await client.post(
            "/me/conversations:query",
            json={"page": 1, "size": 20, "source": "manual"},
        )
        assert manual_resp.status_code == 200
        manual_payload = manual_resp.json()
        assert manual_payload["pagination"]["total"] == 1
        assert manual_payload["items"][0]["conversationId"] == str(session.id)
        assert manual_payload["items"][0]["source"] == "manual"
        assert manual_payload["items"][0]["external_provider"] == "opencode"
        assert manual_payload["items"][0]["external_session_id"] == "ses_filter_1"

        scheduled_resp = await client.post(
            "/me/conversations:query",
            json={"page": 1, "size": 20, "source": "scheduled"},
        )
        assert scheduled_resp.status_code == 200
        assert scheduled_resp.json()["pagination"]["total"] == 0


async def test_messages_query_reads_local_history_for_opencode_bound_conversation(
    async_db_session,
    async_session_maker,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="op-msg")

    session = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        agent_id=agent.id,
        agent_source="personal",
        external_provider="opencode",
        external_session_id="ses_local_hist_1",
        context_id="ctx-local-hist-1",
        title="Opencode Local History",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(session)
    await async_db_session.flush()
    metadata = {
        "contextId": "ctx-local-hist-1",
        "shared": {
            "session": {
                "id": "ses_local_hist_1",
                "provider": "opencode",
            }
        },
    }
    user_message = AgentMessage(
        user_id=user.id,
        sender="user",
        conversation_id=session.id,
        message_metadata=metadata,
    )
    agent_message = AgentMessage(
        user_id=user.id,
        sender="agent",
        conversation_id=session.id,
        message_metadata=metadata,
    )
    async_db_session.add(user_message)
    async_db_session.add(agent_message)
    await async_db_session.flush()
    async_db_session.add(
        AgentMessageBlock(
            user_id=user.id,
            message_id=user_message.id,
            block_seq=1,
            start_event_seq=1,
            end_event_seq=1,
            start_event_id="evt-local-hist-user-1",
            end_event_id="evt-local-hist-user-1",
            block_type="text",
            content="hello",
            is_finished=True,
            source="user_input",
        )
    )
    async_db_session.add(
        AgentMessageBlock(
            user_id=user.id,
            message_id=agent_message.id,
            block_seq=1,
            start_event_seq=1,
            end_event_seq=1,
            start_event_id="evt-local-hist-1",
            end_event_id="evt-local-hist-1",
            block_type="text",
            content="world",
            is_finished=True,
            source="stream",
        )
    )
    await async_db_session.commit()

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(
            f"/me/conversations/{session.id}/messages:query",
            json={"limit": 8},
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert len(payload["items"]) == 2
        assert payload["items"][0]["role"] == "user"
        assert payload["items"][1]["role"] == "agent"
        assert payload["items"][0]["blocks"][0]["content"] == "hello"
        assert payload["items"][1]["blocks"][0]["content"] == "world"


async def test_messages_query_hides_interrupt_lifecycle_history_from_timeline(
    async_db_session,
    async_session_maker,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="interrupts")

    session = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        agent_id=agent.id,
        agent_source="personal",
        title="Interrupt History",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(session)
    await async_db_session.flush()

    await session_hub_service.record_interrupt_lifecycle_event_by_local_session_id(
        async_db_session,
        local_session_id=session.id,
        user_id=user.id,
        event={
            "request_id": "perm-1",
            "type": "permission",
            "phase": "asked",
            "details": {
                "permission": "read",
                "patterns": ["/repo/.env"],
            },
        },
    )
    await session_hub_service.record_interrupt_lifecycle_event_by_local_session_id(
        async_db_session,
        local_session_id=session.id,
        user_id=user.id,
        event={
            "request_id": "perm-1",
            "type": "permission",
            "phase": "resolved",
            "resolution": "replied",
        },
    )
    await async_db_session.commit()

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(
            f"/me/conversations/{session.id}/messages:query",
            json={"limit": 8},
        )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["items"] == []


async def test_messages_query_fills_visible_page_when_interrupt_lifecycle_exists(
    async_db_session,
    async_session_maker,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session, user_id=user.id, suffix="interrupt-mix"
    )

    session = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        agent_id=agent.id,
        agent_source="personal",
        title="Interrupt Mixed History",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(session)
    await async_db_session.flush()

    user_message = AgentMessage(
        user_id=user.id,
        sender="user",
        conversation_id=session.id,
    )
    agent_message = AgentMessage(
        user_id=user.id,
        sender="agent",
        conversation_id=session.id,
    )
    async_db_session.add(user_message)
    async_db_session.add(agent_message)
    await async_db_session.flush()
    async_db_session.add(
        AgentMessageBlock(
            user_id=user.id,
            message_id=user_message.id,
            block_seq=1,
            block_type="text",
            content="hello",
            is_finished=True,
            source="user_input",
        )
    )
    async_db_session.add(
        AgentMessageBlock(
            user_id=user.id,
            message_id=agent_message.id,
            block_seq=1,
            block_type="text",
            content="world",
            is_finished=True,
            source="stream",
        )
    )

    await session_hub_service.record_interrupt_lifecycle_event_by_local_session_id(
        async_db_session,
        local_session_id=session.id,
        user_id=user.id,
        event={
            "request_id": "perm-2",
            "type": "permission",
            "phase": "asked",
            "details": {
                "permission": "read",
                "patterns": ["/repo/.env"],
            },
        },
    )
    await session_hub_service.record_interrupt_lifecycle_event_by_local_session_id(
        async_db_session,
        local_session_id=session.id,
        user_id=user.id,
        event={
            "request_id": "perm-2",
            "type": "permission",
            "phase": "resolved",
            "resolution": "replied",
        },
    )
    await async_db_session.commit()

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(
            f"/me/conversations/{session.id}/messages:query",
            json={"limit": 2},
        )

    assert resp.status_code == 200
    payload = resp.json()
    assert len(payload["items"]) == 2
    assert [item["role"] for item in payload["items"]] == ["user", "agent"]
    assert payload["items"][0]["blocks"][0]["content"] == "hello"
    assert payload["items"][1]["blocks"][0]["content"] == "world"


async def test_messages_query_keeps_preempt_history_visible(
    async_db_session,
    async_session_maker,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="preempts")

    session = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        agent_id=agent.id,
        agent_source="personal",
        title="Preempt History",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(session)
    await async_db_session.flush()

    await session_hub_service.record_preempt_event_by_local_session_id(
        async_db_session,
        local_session_id=session.id,
        user_id=user.id,
        event={
            "reason": "invoke_interrupt",
            "status": "completed",
            "source": "user",
            "target_message_id": str(uuid4()),
            "replacement_user_message_id": str(uuid4()),
            "replacement_agent_message_id": str(uuid4()),
            "target_task_ids": ["task-preempt-1"],
            "failed_error_codes": [],
        },
    )
    await async_db_session.commit()

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(
            f"/me/conversations/{session.id}/messages:query",
            json={"limit": 8},
        )

    assert resp.status_code == 200
    payload = resp.json()
    assert len(payload["items"]) == 1
    assert payload["items"][0]["role"] == "system"
    assert payload["items"][0]["blocks"][0]["content"].startswith(
        "Interrupted the previous response before continuing with your new message."
    )


async def test_messages_query_keeps_interrupt_event_blocks_inline_on_agent_message(
    async_db_session,
    async_session_maker,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session, user_id=user.id, suffix="interrupt-inline-blocks"
    )

    session = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        agent_id=agent.id,
        agent_source="personal",
        title="Interrupt Inline Blocks",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(session)
    await async_db_session.flush()

    agent_message = AgentMessage(
        user_id=user.id,
        sender="agent",
        conversation_id=session.id,
        status="done",
    )
    async_db_session.add(agent_message)
    await async_db_session.flush()

    async_db_session.add_all(
        [
            AgentMessageBlock(
                user_id=user.id,
                message_id=agent_message.id,
                block_seq=1,
                block_type="text",
                content="Checking access",
                is_finished=True,
                source="stream",
            ),
            AgentMessageBlock(
                user_id=user.id,
                message_id=agent_message.id,
                block_seq=2,
                block_type="interrupt_event",
                content=serialize_interrupt_event_block_content(
                    {
                        "request_id": "perm-inline-1",
                        "type": "permission",
                        "phase": "asked",
                        "details": {
                            "permission": "read",
                            "patterns": ["/repo/.env"],
                        },
                    }
                ),
                is_finished=True,
                source="interrupt_lifecycle",
            ),
            AgentMessageBlock(
                user_id=user.id,
                message_id=agent_message.id,
                block_seq=3,
                block_type="text",
                content="Resuming execution",
                is_finished=True,
                source="stream",
            ),
        ]
    )
    await async_db_session.commit()

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(
            f"/me/conversations/{session.id}/messages:query",
            json={"limit": 8},
        )

    assert resp.status_code == 200
    payload = resp.json()
    assert len(payload["items"]) == 1
    returned_message = payload["items"][0]
    assert returned_message["role"] == "agent"
    assert [block["type"] for block in returned_message["blocks"]] == [
        "text",
        "interrupt_event",
        "text",
    ]
    assert returned_message["blocks"][1]["content"].startswith(
        "Agent requested permission: read."
    )
    interrupt = returned_message["blocks"][1]["interrupt"]
    assert interrupt["requestId"] == "perm-inline-1"
    assert interrupt["type"] == "permission"
    assert interrupt["phase"] == "asked"
    assert interrupt["resolution"] is None
    assert interrupt["details"]["permission"] == "read"
    assert interrupt["details"]["patterns"] == ["/repo/.env"]
    assert interrupt["details"]["displayMessage"] is None
    assert interrupt["details"]["questions"] == []
    assert interrupt["details"]["permissions"] is None
    assert interrupt["details"]["serverName"] is None
    assert interrupt["details"]["mode"] is None
    assert interrupt["details"]["requestedSchema"] is None
    assert interrupt["details"]["url"] is None
    assert interrupt["details"]["elicitationId"] is None
    assert interrupt["details"]["meta"] is None


async def test_messages_query_keeps_non_interrupt_system_messages(
    async_db_session,
    async_session_maker,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="system-msg")

    session = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        agent_id=agent.id,
        agent_source="personal",
        title="System Message History",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(session)
    await async_db_session.flush()

    system_message = AgentMessage(
        user_id=user.id,
        sender="system",
        conversation_id=session.id,
        status="done",
        message_metadata={"category": "notice"},
    )
    async_db_session.add(system_message)
    await async_db_session.flush()
    async_db_session.add(
        AgentMessageBlock(
            user_id=user.id,
            message_id=system_message.id,
            block_seq=1,
            block_type="text",
            content="System notice",
            is_finished=True,
            source="system_notice",
        )
    )
    await async_db_session.commit()

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(
            f"/me/conversations/{session.id}/messages:query",
            json={"limit": 8},
        )

    assert resp.status_code == 200
    payload = resp.json()
    assert len(payload["items"]) == 1
    assert payload["items"][0]["role"] == "system"
    assert payload["items"][0]["blocks"][0]["content"] == "System notice"


async def test_continue_keeps_external_session_id_empty_when_missing(
    async_db_session,
    async_session_maker,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session, user_id=user.id, suffix="ctx-fallback"
    )

    session = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        agent_id=agent.id,
        agent_source="personal",
        external_provider="opencode",
        context_id="ses_context_only_1",
        title="Context Binding",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(session)
    await async_db_session.flush()
    bound_message = AgentMessage(
        user_id=user.id,
        sender="agent",
        conversation_id=session.id,
        message_metadata={
            "contextId": "ses_context_only_1",
            "shared": {
                "session": {
                    "provider": "opencode",
                }
            },
        },
    )
    async_db_session.add(bound_message)
    await async_db_session.flush()
    async_db_session.add(
        AgentMessageBlock(
            user_id=user.id,
            message_id=bound_message.id,
            block_seq=1,
            block_type="text",
            content="bound-by-context",
            is_finished=True,
            source="finalize_snapshot",
        )
    )
    await async_db_session.commit()

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(f"/me/conversations/{session.id}:continue")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["conversationId"] == str(session.id)
        assert payload["source"] == "manual"
        assert payload.get("metadata", {}).get("externalSessionId") is None
        assert payload.get("metadata", {}).get("contextId") == "ses_context_only_1"
