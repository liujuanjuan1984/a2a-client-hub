from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from app.api.routers import me_sessions
from app.db.models.a2a_agent import A2AAgent
from app.db.models.a2a_schedule_execution import A2AScheduleExecution
from app.db.models.agent_message import AgentMessage
from app.db.models.agent_session import AgentSession
from app.services.a2a_schedule_service import a2a_schedule_service
from app.services.session_hub import build_manual_session_key, build_scheduled_session_key
from app.utils.timezone_util import utc_now
from backend.tests.api_utils import create_test_client
from backend.tests.utils import create_user

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


async def test_unified_session_list_messages_and_continue(
    async_db_session,
    async_session_maker,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="unified")

    now = utc_now()
    manual_session = AgentSession(
        id=uuid4(),
        user_id=user.id,
        name="Manual Thread",
        module_key=str(agent.id),
        session_type=AgentSession.TYPE_CHAT,
        last_activity_at=now,
    )
    scheduled_session = AgentSession(
        id=uuid4(),
        user_id=user.id,
        name="Scheduled Thread",
        module_key="a2a",
        session_type=AgentSession.TYPE_SCHEDULED,
        last_activity_at=now - timedelta(minutes=10),
    )
    async_db_session.add(manual_session)
    async_db_session.add(scheduled_session)
    await async_db_session.flush()

    task = await a2a_schedule_service.create_task(
        async_db_session,
        user_id=user.id,
        name="Nightly",
        agent_id=agent.id,
        prompt="ping",
        cycle_type="daily",
        time_point={"time": "00:00"},
        enabled=False,
    )
    task.session_id = scheduled_session.id

    execution = A2AScheduleExecution(
        user_id=user.id,
        task_id=task.id,
        session_id=scheduled_session.id,
        scheduled_for=now - timedelta(minutes=1),
        started_at=now - timedelta(minutes=1),
        finished_at=now,
        status=A2AScheduleExecution.STATUS_SUCCESS,
        response_content="ok",
    )
    async_db_session.add(execution)

    async_db_session.add(
        AgentMessage(
            user_id=user.id,
            session_id=manual_session.id,
            sender="user",
            content="hello",
            message_metadata={"context_id": "ctx-manual-1"},
        )
    )
    async_db_session.add(
        AgentMessage(
            user_id=user.id,
            session_id=manual_session.id,
            sender="agent",
            content="world",
            message_metadata={"context_id": "ctx-manual-1"},
        )
    )
    await async_db_session.commit()

    manual_key = build_manual_session_key(manual_session.id)
    scheduled_key = build_scheduled_session_key(scheduled_session.id)

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        list_resp = await client.post(
            "/me/sessions:query",
            json={"page": 1, "size": 50, "refresh": False},
        )
        assert list_resp.status_code == 200
        list_payload = list_resp.json()

        keys = {item["id"] for item in list_payload["items"]}
        assert manual_key in keys
        assert scheduled_key in keys

        manual_msgs_resp = await client.post(
            f"/me/sessions/{manual_key}/messages:query",
            json={"page": 1, "size": 50},
        )
        assert manual_msgs_resp.status_code == 200
        msgs_payload = manual_msgs_resp.json()
        assert msgs_payload["meta"]["source"] == "manual"
        assert len(msgs_payload["items"]) == 2

        continue_resp = await client.post(f"/me/sessions/{manual_key}:continue")
        assert continue_resp.status_code == 200
        continue_payload = continue_resp.json()
        assert continue_payload["source"] == "manual"
        assert continue_payload["contextId"] == "ctx-manual-1"


async def test_unified_manual_messages_query_returns_empty_for_new_session(
    async_db_session,
    async_session_maker,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    missing_manual_key = f"manual:{uuid4()}"

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(
            f"/me/sessions/{missing_manual_key}/messages:query",
            json={"page": 1, "size": 20},
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["pagination"]["total"] == 0
        assert payload["items"] == []
