from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from app.api.routers import me_sessions
from app.db.models.a2a_agent import A2AAgent
from app.db.models.a2a_schedule_execution import A2AScheduleExecution
from app.db.models.agent_message import AgentMessage
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
    async_db_session.add(
        AgentMessage(
            user_id=user.id,
            sender="automation",
            content="ping",
            conversation_id=session.id,
            message_metadata=metadata,
        )
    )
    async_db_session.add(
        AgentMessage(
            user_id=user.id,
            sender="agent",
            content="pong",
            conversation_id=session.id,
            message_metadata={**metadata, "success": True},
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
            json={"page": 1, "size": 50},
        )
        assert msgs_resp.status_code == 200
        msgs_payload = msgs_resp.json()
        assert msgs_payload["meta"]["conversationId"] == str(session.id)
        assert msgs_payload["meta"]["source"] == "scheduled"
        assert len(msgs_payload["items"]) == 2
        assert msgs_payload["items"][0]["role"] == "user"
        assert msgs_payload["items"][1]["role"] == "agent"
