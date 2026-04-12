from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from app.db.models.a2a_schedule_execution import A2AScheduleExecution
from app.db.models.agent_message import AgentMessage
from app.db.models.agent_message_block import AgentMessageBlock
from app.db.models.conversation_thread import ConversationThread
from app.features.schedules.service import a2a_schedule_service
from app.features.self_management_shared.constants import (
    SELF_MANAGEMENT_BUILT_IN_AGENT_INTERNAL_ID,
    SELF_MANAGEMENT_BUILT_IN_AGENT_PUBLIC_ID,
)
from app.features.sessions import router as me_sessions
from app.features.sessions.service import session_hub_service
from app.utils.timezone_util import utc_now
from tests.support.api_utils import create_test_client
from tests.support.utils import create_a2a_agent, create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_create_agent = create_a2a_agent


@pytest.mark.parametrize(
    ("detail", "expected_status"),
    [
        ("session_not_found", 404),
        ("session_forbidden", 403),
        ("upstream_unauthorized", 401),
        ("upstream_permission_denied", 403),
        ("upstream_resource_not_found", 404),
        ("upstream_quota_exceeded", 429),
        ("upstream_bad_request", 400),
        ("upstream_unreachable", 503),
        ("upstream_http_error", 502),
        ("invalid_conversation_id", 400),
    ],
)
async def test_status_code_for_session_error(detail: str, expected_status: int) -> None:
    assert (
        me_sessions._status_code_for_session_error(detail) == expected_status
    )  # noqa: SLF001


async def test_me_sessions_scheduled_list_detail_and_messages(
    async_db_session,
    async_session_maker,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="sched")

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

    now = utc_now()
    session = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_SCHEDULED,
        agent_id=agent.id,
        agent_source="personal",
        title="[Scheduled] Nightly",
        last_active_at=now,
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(session)
    await async_db_session.flush()

    task.conversation_id = session.id
    execution = A2AScheduleExecution(
        user_id=user.id,
        task_id=task.id,
        run_id=uuid4(),
        conversation_id=session.id,
        scheduled_for=now - timedelta(minutes=1),
        started_at=now - timedelta(minutes=1),
        finished_at=now,
        status=A2AScheduleExecution.STATUS_SUCCESS,
        response_content="ok",
    )
    async_db_session.add(execution)
    await async_db_session.flush()

    metadata = {
        "source": "scheduled",
        "schedule_task_id": str(task.id),
        "schedule_execution_id": str(execution.id),
        "agent_id": str(agent.id),
    }
    user_message = AgentMessage(
        user_id=user.id,
        sender="automation",
        conversation_id=session.id,
        message_metadata=metadata,
    )
    agent_message = AgentMessage(
        user_id=user.id,
        sender="agent",
        conversation_id=session.id,
        message_metadata={**metadata, "success": True},
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
            content="ping",
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
            content="pong",
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
        assert manual_resp.json()["pagination"]["total"] == 0

        list_resp = await client.post(
            "/me/conversations:query",
            json={"page": 1, "size": 20, "source": "scheduled"},
        )
        assert list_resp.status_code == 200
        payload = list_resp.json()
        assert payload["pagination"]["total"] >= 1
        item = payload["items"][0]
        assert item["conversationId"] == str(session.id)
        assert item["source"] == "scheduled"
        assert item["external_provider"] is None
        assert item["external_session_id"] is None
        assert item["agent_id"] == str(agent.id)
        assert "id" not in item

        continue_resp = await client.post(f"/me/conversations/{session.id}:continue")
        assert continue_resp.status_code == 200
        continue_payload = continue_resp.json()
        assert continue_payload["conversationId"] == str(session.id)
        assert continue_payload["source"] == "scheduled"
        assert "session_id" not in continue_payload

        msgs_resp = await client.post(
            f"/me/conversations/{session.id}/messages:query",
            json={"limit": 8},
        )
        assert msgs_resp.status_code == 200
        msgs_payload = msgs_resp.json()
        assert len(msgs_payload["items"]) == 2
        assert msgs_payload["items"][0]["role"] == "user"
        assert msgs_payload["items"][1]["role"] == "agent"
        assert len(msgs_payload["items"][0]["blocks"]) == 1
        assert len(msgs_payload["items"][1]["blocks"]) == 1


async def test_me_sessions_query_supports_agent_id_filter(
    async_db_session,
    async_session_maker,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent_a = await _create_agent(async_db_session, user_id=user.id, suffix="a")
    agent_b = await _create_agent(async_db_session, user_id=user.id, suffix="b")
    now = utc_now()

    session_a = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        agent_id=agent_a.id,
        agent_source="personal",
        title="Session A",
        last_active_at=now,
        status=ConversationThread.STATUS_ACTIVE,
    )
    session_b = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        agent_id=agent_b.id,
        agent_source="personal",
        title="Session B",
        last_active_at=now - timedelta(minutes=1),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(session_a)
    async_db_session.add(session_b)
    await async_db_session.commit()

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(
            "/me/conversations:query",
            json={"page": 1, "size": 20, "agent_id": str(agent_a.id)},
        )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["pagination"]["total"] == 1
    assert len(payload["items"]) == 1
    assert payload["items"][0]["conversationId"] == str(session_a.id)
    assert payload["items"][0]["agent_id"] == str(agent_a.id)


async def test_me_sessions_query_supports_built_in_agent_public_id_filter(
    async_db_session,
    async_session_maker,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    now = utc_now()

    built_in_session = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        agent_id=SELF_MANAGEMENT_BUILT_IN_AGENT_INTERNAL_ID,
        agent_source="builtin",
        title="Built-in Session",
        last_active_at=now,
        status=ConversationThread.STATUS_ACTIVE,
    )
    other_session = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        agent_id=uuid4(),
        agent_source="personal",
        title="Other Session",
        last_active_at=now - timedelta(minutes=1),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(built_in_session)
    async_db_session.add(other_session)
    await async_db_session.commit()

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(
            "/me/conversations:query",
            json={
                "page": 1,
                "size": 20,
                "agent_id": SELF_MANAGEMENT_BUILT_IN_AGENT_PUBLIC_ID,
            },
        )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["pagination"]["total"] == 1
    assert len(payload["items"]) == 1
    assert payload["items"][0]["conversationId"] == str(built_in_session.id)
    assert payload["items"][0]["agent_id"] == SELF_MANAGEMENT_BUILT_IN_AGENT_PUBLIC_ID


async def test_me_sessions_cancel_returns_accepted_for_inflight_task(
    async_db_session,
    async_session_maker,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    session = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        title="Session",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(session)
    await async_db_session.flush()

    class _Gateway:
        async def cancel_task(
            self, *, resolved, task_id, metadata=None
        ):  # noqa: ANN001
            return {"success": True}

    token = await session_hub_service.register_inflight_invoke(
        user_id=user.id,
        conversation_id=session.id,
        gateway=_Gateway(),
        resolved=object(),
    )
    await session_hub_service.bind_inflight_task_id(
        user_id=user.id,
        conversation_id=session.id,
        token=token,
        task_id="task-123",
    )
    await async_db_session.commit()

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(f"/me/conversations/{session.id}/cancel")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["conversationId"] == str(session.id)
    assert payload["taskId"] == "task-123"
    assert payload["cancelled"] is True
    assert payload["status"] == "accepted"


async def test_me_sessions_cancel_accepts_pending_when_task_id_not_bound(
    async_db_session,
    async_session_maker,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    session = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        title="Session",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(session)
    await async_db_session.flush()

    class _Gateway:
        async def cancel_task(
            self, *, resolved, task_id, metadata=None
        ):  # noqa: ANN001, ARG002
            return {"success": True}

    await session_hub_service.register_inflight_invoke(
        user_id=user.id,
        conversation_id=session.id,
        gateway=_Gateway(),
        resolved=object(),
    )
    await async_db_session.commit()

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(f"/me/conversations/{session.id}/cancel")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["conversationId"] == str(session.id)
    assert payload["taskId"] is None
    assert payload["cancelled"] is True
    assert payload["status"] == "pending"


async def test_me_sessions_cancel_returns_no_inflight_when_session_not_found(
    async_db_session,
    async_session_maker,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    missing_conversation_id = uuid4()

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(f"/me/conversations/{missing_conversation_id}/cancel")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["conversationId"] == str(missing_conversation_id)
    assert payload["taskId"] is None
    assert payload["cancelled"] is False
    assert payload["status"] == "no_inflight"


async def test_me_sessions_cancel_maps_upstream_error_to_bad_gateway(
    async_db_session,
    async_session_maker,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    session = ConversationThread(
        id=uuid4(),
        user_id=user.id,
        source=ConversationThread.SOURCE_MANUAL,
        title="Session",
        last_active_at=utc_now(),
        status=ConversationThread.STATUS_ACTIVE,
    )
    async_db_session.add(session)
    await async_db_session.flush()

    class _Gateway:
        async def cancel_task(
            self, *, resolved, task_id, metadata=None
        ):  # noqa: ANN001
            return {"success": False, "error_code": "upstream_error"}

    token = await session_hub_service.register_inflight_invoke(
        user_id=user.id,
        conversation_id=session.id,
        gateway=_Gateway(),
        resolved=object(),
    )
    await session_hub_service.bind_inflight_task_id(
        user_id=user.id,
        conversation_id=session.id,
        token=token,
        task_id="task-failed",
    )
    await async_db_session.commit()

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(f"/me/conversations/{session.id}/cancel")

    assert resp.status_code == 502
    assert resp.json()["detail"] == "upstream_error"
