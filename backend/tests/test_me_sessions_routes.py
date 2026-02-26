from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from app.api.routers import me_sessions
from app.db.models.a2a_agent import A2AAgent
from app.db.models.a2a_schedule_execution import A2AScheduleExecution
from app.db.models.agent_message import AgentMessage
from app.db.models.agent_message_block import AgentMessageBlock
from app.db.models.conversation_thread import ConversationThread
from app.services.a2a_schedule_service import a2a_schedule_service
from app.utils.timezone_util import utc_now
from tests.api_utils import create_test_client
from tests.utils import create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _create_agent(async_db_session, *, user_id, suffix: str) -> A2AAgent:
    agent = A2AAgent(
        user_id=user_id,
        name=f"Agent {suffix}",
        card_url=f"https://example.com/{suffix}",
        auth_type="none",
        enabled=True,
    )
    async_db_session.add(agent)
    await async_db_session.commit()
    await async_db_session.refresh(agent)
    return agent


@pytest.mark.parametrize(
    ("detail", "expected_status"),
    [
        ("session_not_found", 404),
        ("session_forbidden", 403),
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
