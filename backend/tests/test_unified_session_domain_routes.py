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
        message_metadata={"context_id": "ctx-manual-1"},
    )
    agent_message = AgentMessage(
        user_id=user.id,
        sender="agent",
        conversation_id=manual_session.id,
        message_metadata={"context_id": "ctx-manual-1"},
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
            start_event_seq=1,
            end_event_seq=1,
            start_event_id="evt-route-1",
            end_event_id="evt-route-1",
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
        assert messages_payload["meta"]["conversationId"] == str(manual_session.id)
        messages_user_item = next(
            item for item in messages_payload["items"] if item["role"] == "user"
        )
        messages_agent_item = next(
            item for item in messages_payload["items"] if item["role"] == "agent"
        )
        assert messages_user_item["id"] == str(user_message.id)
        assert messages_agent_item["id"] == str(agent_message.id)
        assert len(messages_user_item["blocks"]) == 1
        assert len(messages_agent_item["blocks"]) == 1
        assert messages_agent_item["blocks"][0]["content"] == "world"
        assert messages_payload["pageInfo"]["hasMoreBefore"] is False
        assert messages_payload["pageInfo"]["nextBefore"] is None

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
            "provider": "opencode",
            "external_session_id": "ses_upstream_1",
            "context_id": "ctx-bound-1",
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
        assert payload.get("metadata", {}).get("provider") == "opencode"
        assert payload.get("metadata", {}).get("externalSessionId") == "ses_upstream_1"
        assert payload.get("metadata", {}).get("contextId") == "ctx-bound-1"


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
            "provider": "opencode",
            "external_session_id": "ses_filter_1",
            "context_id": "ctx-filter-1",
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
        "provider": "opencode",
        "external_session_id": "ses_local_hist_1",
        "context_id": "ctx-local-hist-1",
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
        assert payload["meta"]["conversationId"] == str(session.id)
        assert payload["meta"]["source"] == "manual"
        assert payload["meta"]["upstream_session_id"] == "ses_local_hist_1"
        assert len(payload["items"]) == 2
        assert payload["items"][0]["role"] == "user"
        assert payload["items"][1]["role"] == "agent"
        assert payload["items"][0]["blocks"][0]["content"] == "hello"
        assert payload["items"][1]["blocks"][0]["content"] == "world"


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
            "provider": "opencode",
            "context_id": "ses_context_only_1",
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
        assert payload.get("metadata", {}).get("provider") == "opencode"
        assert payload.get("metadata", {}).get("externalSessionId") is None
        assert payload.get("metadata", {}).get("contextId") == "ses_context_only_1"
