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


async def test_me_sessions_scheduled_list_detail_and_messages(
    async_db_session,
    async_session_maker,
    monkeypatch,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="sched")

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

    now = utc_now()
    session = AgentSession(
        id=uuid4(),
        user_id=user.id,
        name="[Scheduled] Nightly",
        module_key="a2a",
        session_type=AgentSession.TYPE_SCHEDULED,
        last_activity_at=now,
    )
    async_db_session.add(session)
    await async_db_session.flush()

    task.session_id = session.id
    execution = A2AScheduleExecution(
        user_id=user.id,
        task_id=task.id,
        session_id=session.id,
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
            session_id=session.id,
            sender="automation",
            content="ping",
            message_metadata=metadata,
        )
    )
    async_db_session.add(
        AgentMessage(
            user_id=user.id,
            session_id=session.id,
            sender="agent",
            content="pong",
            message_metadata={**metadata, "success": True},
        )
    )
    await async_db_session.commit()

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        manual_resp = await client.get("/me/sessions", params={"source": "manual"})
        assert manual_resp.status_code == 200
        assert manual_resp.json()["pagination"]["total"] == 0

        list_resp = await client.get("/me/sessions", params={"source": "scheduled"})
        assert list_resp.status_code == 200
        payload = list_resp.json()
        assert payload["pagination"]["total"] >= 1
        item = payload["items"][0]
        assert item["source"] == "scheduled"
        assert item["job_id"] == str(task.id)
        assert item["run_id"] == str(execution.id)
        assert item["agent_id"] == str(agent.id)

        detail_resp = await client.get(f"/me/sessions/{session.id}")
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert detail["id"] == str(session.id)
        assert detail["source"] == "scheduled"
        assert detail["job_id"] == str(task.id)
        assert detail["run_id"] == str(execution.id)

        msgs_resp = await client.get(
            f"/me/sessions/{session.id}/messages",
            params={"page": 1, "size": 50},
        )
        assert msgs_resp.status_code == 200
        msgs_payload = msgs_resp.json()
        assert msgs_payload["meta"]["session_id"] == str(session.id)
        assert len(msgs_payload["items"]) == 2
        assert msgs_payload["items"][0]["role"] == "user"
        assert msgs_payload["items"][1]["role"] == "agent"
