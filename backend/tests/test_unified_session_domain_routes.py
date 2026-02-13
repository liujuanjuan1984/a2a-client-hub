from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.api.routers import me_sessions
from app.db.models.a2a_agent import A2AAgent
from app.db.models.a2a_schedule_execution import A2AScheduleExecution
from app.db.models.agent_message import AgentMessage
from app.db.models.agent_session import AgentSession
from app.integrations.a2a_extensions.errors import A2AExtensionUpstreamError
from app.services.a2a_runtime import A2ARuntimeNotFoundError
from app.services.a2a_schedule_service import a2a_schedule_service
from app.services.conversation_identity import conversation_identity_service
from app.services.session_hub import (
    build_manual_session_key,
    build_opencode_session_key,
    build_scheduled_session_key,
    session_hub_service,
)
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


async def test_unified_opencode_continue_returns_400_for_invalid_session_key(
    async_db_session,
    async_session_maker,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post("/me/sessions/opencode:%2A%2A%2A:continue")
        assert resp.status_code == 400
        assert resp.json()["detail"] == "invalid opencode session key"


async def test_unified_opencode_continue_returns_404_when_runtime_missing(
    async_db_session,
    async_session_maker,
    monkeypatch,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    opencode_key = build_opencode_session_key(
        agent_id=uuid4(),
        agent_source="personal",
        upstream_session_id="upstream-session-1",
    )

    async def _raise_not_found(*args, **kwargs):
        raise A2ARuntimeNotFoundError("agent missing")

    monkeypatch.setattr(
        me_sessions.session_hub_service, "_build_runtime", _raise_not_found
    )

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(f"/me/sessions/{opencode_key}:continue")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "session_not_found"


async def test_unified_opencode_continue_returns_502_for_upstream_error(
    async_db_session,
    async_session_maker,
    monkeypatch,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    opencode_key = build_opencode_session_key(
        agent_id=uuid4(),
        agent_source="personal",
        upstream_session_id="upstream-session-1",
    )

    class _DummyRuntime:
        pass

    async def _build_runtime(*args, **kwargs):
        return _DummyRuntime()

    async def _raise_upstream(*args, **kwargs):
        raise A2AExtensionUpstreamError(
            message="network down",
            error_code="upstream_unreachable",
            upstream_error={"message": "network down"},
        )

    monkeypatch.setattr(
        me_sessions.session_hub_service, "_build_runtime", _build_runtime
    )
    monkeypatch.setattr(
        "app.services.session_hub.get_a2a_extensions_service",
        lambda: type("_Svc", (), {"opencode_continue_session": _raise_upstream})(),
    )

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(f"/me/sessions/{opencode_key}:continue")
        assert resp.status_code == 502
        assert resp.json()["detail"] == "upstream_unreachable"


async def test_unified_opencode_session_list_normalizes_directory_items(
    async_db_session,
    async_session_maker,
    monkeypatch,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent_id = uuid4()
    last_active_at = utc_now().isoformat()

    async def _list_all_opencode_sessions_stub(db, *, user_id, refresh):
        return (
            [
                {
                    "agent_id": agent_id,
                    "agent_source": "personal",
                    "session_id": "upstream-session-1",
                    "title": "Remote Session",
                    "last_active_at": last_active_at,
                }
            ],
            {
                "total_agents": 1,
                "refreshed_agents": 0,
                "cached_agents": 1,
                "partial_failures": 0,
            },
        )

    monkeypatch.setattr(
        me_sessions.session_hub_service,
        "_list_all_opencode_sessions",
        _list_all_opencode_sessions_stub,
    )

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(
            "/me/sessions:query",
            json={"page": 1, "size": 20, "source": "opencode", "refresh": False},
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["pagination"]["total"] == 1
        assert len(payload["items"]) == 1

        item = payload["items"][0]
        assert item["source"] == "opencode"
        assert item["source_session_id"] == "upstream-session-1"
        assert item["agent_id"] == str(agent_id)
        assert item["title"] == "Remote Session"
        assert item["id"].startswith("opencode:")


async def test_unified_session_list_dedups_manual_and_opencode_with_same_binding(
    async_db_session,
    async_session_maker,
    monkeypatch,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="dedup")
    now = utc_now()

    manual_session = AgentSession(
        id=uuid4(),
        user_id=user.id,
        name="Manual Bound Session",
        module_key=str(agent.id),
        session_type=AgentSession.TYPE_CHAT,
        last_activity_at=now,
    )
    async_db_session.add(manual_session)
    await async_db_session.flush()

    await session_hub_service.record_local_invoke_messages(
        async_db_session,
        session=manual_session,
        source="manual",
        user_id=user.id,
        agent_id=agent.id,
        agent_source="personal",
        query="hello",
        response_content="world",
        success=True,
        context_id="upstream-session-1",
        invoke_metadata={
            "provider": "opencode",
            "externalSessionId": "upstream-session-1",
        },
        extra_metadata={"transport": "http_json", "stream": False},
    )
    await async_db_session.commit()

    async def _list_all_opencode_sessions_stub(db, *, user_id, refresh):
        return (
            [
                {
                    "agent_id": agent.id,
                    "agent_source": "personal",
                    "session_id": "upstream-session-1",
                    "title": "Remote Session",
                    "last_active_at": now.isoformat(),
                }
            ],
            {
                "total_agents": 1,
                "refreshed_agents": 0,
                "cached_agents": 1,
                "partial_failures": 0,
            },
        )

    monkeypatch.setattr(
        me_sessions.session_hub_service,
        "_list_all_opencode_sessions",
        _list_all_opencode_sessions_stub,
    )

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(
            "/me/sessions:query",
            json={"page": 1, "size": 20, "refresh": False},
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["pagination"]["total"] == 1
        assert len(payload["items"]) == 1
        assert payload["items"][0]["source"] == "opencode"


async def test_unified_session_list_dedups_using_local_conversation_id_fallback(
    async_db_session,
    async_session_maker,
    monkeypatch,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session, user_id=user.id, suffix="conv-fallback"
    )
    now = utc_now()

    manual_session = AgentSession(
        id=uuid4(),
        user_id=user.id,
        name="Manual Conversation Fallback",
        module_key=str(agent.id),
        session_type=AgentSession.TYPE_CHAT,
        last_activity_at=now,
    )
    async_db_session.add(manual_session)
    await async_db_session.flush()

    conversation_id = await conversation_identity_service.bind_external_session(
        async_db_session,
        user_id=user.id,
        conversation_id=None,
        provider="opencode-a2a-serve",
        external_session_id="upstream-conv-fallback-1",
        agent_id=agent.id,
        agent_source="personal",
        context_id="ctx-conv-fallback-1",
        title="Conversation Fallback",
        binding_metadata={"provider": "opencode-a2a-serve"},
    )

    async_db_session.add(
        AgentMessage(
            user_id=user.id,
            session_id=manual_session.id,
            conversation_id=conversation_id,
            sender="user",
            content="manual-user",
            message_metadata={"context_id": "ctx-conv-fallback-1"},
        )
    )
    async_db_session.add(
        AgentMessage(
            user_id=user.id,
            session_id=manual_session.id,
            conversation_id=conversation_id,
            sender="agent",
            content="manual-agent",
            message_metadata={"context_id": "ctx-conv-fallback-1"},
        )
    )
    await async_db_session.commit()

    async def _list_all_opencode_sessions_stub(db, *, user_id, refresh):
        return (
            [
                {
                    "agent_id": agent.id,
                    "agent_source": "personal",
                    "session_id": "upstream-conv-fallback-1",
                    "title": "Remote Session",
                    "last_active_at": now.isoformat(),
                }
            ],
            {
                "total_agents": 1,
                "refreshed_agents": 0,
                "cached_agents": 1,
                "partial_failures": 0,
            },
        )

    monkeypatch.setattr(
        me_sessions.session_hub_service,
        "_list_all_opencode_sessions",
        _list_all_opencode_sessions_stub,
    )

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(
            "/me/sessions:query",
            json={"page": 1, "size": 20, "refresh": False},
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["pagination"]["total"] == 1
        assert len(payload["items"]) == 1
        assert payload["items"][0]["source"] == "opencode"


async def test_unified_session_list_dedups_when_provider_missing_but_external_present(
    async_db_session,
    async_session_maker,
    monkeypatch,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(async_db_session, user_id=user.id, suffix="weak-key")
    now = utc_now()

    manual_session = AgentSession(
        id=uuid4(),
        user_id=user.id,
        name="Manual External Only",
        module_key=str(agent.id),
        session_type=AgentSession.TYPE_CHAT,
        last_activity_at=now,
    )
    async_db_session.add(manual_session)
    await async_db_session.flush()

    async_db_session.add(
        AgentMessage(
            user_id=user.id,
            session_id=manual_session.id,
            sender="user",
            content="manual-user",
            message_metadata={"external_session_id": "upstream-weak-key-1"},
        )
    )
    async_db_session.add(
        AgentMessage(
            user_id=user.id,
            session_id=manual_session.id,
            sender="agent",
            content="manual-agent",
            message_metadata={"external_session_id": "upstream-weak-key-1"},
        )
    )
    await async_db_session.commit()

    async def _list_all_opencode_sessions_stub(db, *, user_id, refresh):
        return (
            [
                {
                    "agent_id": agent.id,
                    "agent_source": "personal",
                    "session_id": "upstream-weak-key-1",
                    "title": "Remote Session",
                    "last_active_at": now.isoformat(),
                }
            ],
            {
                "total_agents": 1,
                "refreshed_agents": 0,
                "cached_agents": 1,
                "partial_failures": 0,
            },
        )

    monkeypatch.setattr(
        me_sessions.session_hub_service,
        "_list_all_opencode_sessions",
        _list_all_opencode_sessions_stub,
    )

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(
            "/me/sessions:query",
            json={"page": 1, "size": 20, "refresh": False},
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["pagination"]["total"] == 1
        assert len(payload["items"]) == 1
        assert payload["items"][0]["source"] == "opencode"


async def test_unified_session_list_uses_local_session_binding_when_metadata_missing(
    async_db_session,
    async_session_maker,
    monkeypatch,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session, user_id=user.id, suffix="local-binding-map"
    )
    now = utc_now()

    manual_session = AgentSession(
        id=uuid4(),
        user_id=user.id,
        name="Manual Local Binding Session",
        module_key=str(agent.id),
        session_type=AgentSession.TYPE_CHAT,
        last_activity_at=now,
    )
    async_db_session.add(manual_session)
    await async_db_session.flush()

    conversation_id = await conversation_identity_service.bind_external_session(
        async_db_session,
        user_id=user.id,
        conversation_id=None,
        provider="opencode",
        external_session_id="upstream-local-binding-1",
        agent_id=agent.id,
        agent_source="personal",
        context_id="ctx-local-binding-1",
        title="Local Binding Session",
        binding_metadata={"provider": "opencode"},
        local_session_id=manual_session.id,
    )

    async_db_session.add(
        AgentMessage(
            user_id=user.id,
            session_id=manual_session.id,
            sender="user",
            content="manual-user",
            message_metadata={"context_id": "ctx-local-binding-1"},
        )
    )
    async_db_session.add(
        AgentMessage(
            user_id=user.id,
            session_id=manual_session.id,
            sender="agent",
            content="manual-agent",
            message_metadata={"context_id": "ctx-local-binding-1"},
        )
    )
    await async_db_session.commit()

    async def _list_all_opencode_sessions_stub(db, *, user_id, refresh):
        return (
            [
                {
                    "agent_id": agent.id,
                    "agent_source": "personal",
                    "session_id": "upstream-local-binding-1",
                    "title": "Remote Session",
                    "last_active_at": now.isoformat(),
                }
            ],
            {
                "total_agents": 1,
                "refreshed_agents": 0,
                "cached_agents": 1,
                "partial_failures": 0,
            },
        )

    monkeypatch.setattr(
        me_sessions.session_hub_service,
        "_list_all_opencode_sessions",
        _list_all_opencode_sessions_stub,
    )

    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(
            "/me/sessions:query",
            json={"page": 1, "size": 20, "refresh": False},
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["pagination"]["total"] == 1
        assert len(payload["items"]) == 1
        assert payload["items"][0]["source"] == "opencode"
        assert payload["items"][0]["conversationId"] == str(conversation_id)


async def test_unified_messages_query_keeps_prebinding_local_history(
    async_db_session,
    async_session_maker,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session, user_id=user.id, suffix="prebinding-history"
    )
    now = utc_now()

    manual_session = AgentSession(
        id=uuid4(),
        user_id=user.id,
        name="Manual Prebinding Session",
        module_key=str(agent.id),
        session_type=AgentSession.TYPE_CHAT,
        last_activity_at=now,
    )
    async_db_session.add(manual_session)
    await async_db_session.flush()

    async_db_session.add(
        AgentMessage(
            user_id=user.id,
            session_id=manual_session.id,
            sender="user",
            content="before-binding-user",
            message_metadata={"context_id": "ctx-before"},
        )
    )
    async_db_session.add(
        AgentMessage(
            user_id=user.id,
            session_id=manual_session.id,
            sender="agent",
            content="before-binding-agent",
            message_metadata={"context_id": "ctx-before"},
        )
    )
    await async_db_session.flush()

    await session_hub_service.record_local_invoke_messages(
        async_db_session,
        session=manual_session,
        source="manual",
        user_id=user.id,
        agent_id=agent.id,
        agent_source="personal",
        query="after-binding-user",
        response_content="after-binding-agent",
        success=True,
        context_id="upstream-session-2",
        invoke_metadata={
            "provider": "OpenCode",
            "externalSessionId": "upstream-session-2",
        },
        extra_metadata={"transport": "http_json", "stream": False},
    )
    await async_db_session.commit()
    rows = (
        await async_db_session.execute(
            select(AgentMessage).where(AgentMessage.session_id == manual_session.id)
        )
    ).scalars()
    conversation_ids = {
        str(message.conversation_id)
        for message in rows
        if getattr(message, "conversation_id", None) is not None
    }
    assert len(conversation_ids) == 1

    manual_key = build_manual_session_key(manual_session.id)
    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(
            f"/me/sessions/{manual_key}/messages:query",
            json={"page": 1, "size": 50},
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["pagination"]["total"] == 4
        contents = [item["content"] for item in payload["items"]]
        assert "before-binding-user" in contents
        assert "before-binding-agent" in contents
        assert "after-binding-user" in contents
        assert "after-binding-agent" in contents


async def test_unified_messages_query_backfills_legacy_rows_on_read(
    async_db_session,
    async_session_maker,
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    agent = await _create_agent(
        async_db_session, user_id=user.id, suffix="lazy-backfill"
    )
    now = utc_now()

    manual_session = AgentSession(
        id=uuid4(),
        user_id=user.id,
        name="Manual Legacy Session",
        module_key=str(agent.id),
        session_type=AgentSession.TYPE_CHAT,
        last_activity_at=now,
    )
    async_db_session.add(manual_session)
    await async_db_session.flush()

    async_db_session.add(
        AgentMessage(
            user_id=user.id,
            session_id=manual_session.id,
            sender="user",
            content="legacy-user",
            message_metadata={
                "provider": "OpenCode",
                "externalSessionId": "legacy-upstream-session",
                "context_id": "legacy-context",
            },
        )
    )
    async_db_session.add(
        AgentMessage(
            user_id=user.id,
            session_id=manual_session.id,
            sender="agent",
            content="legacy-agent",
            message_metadata={
                "provider": "OpenCode",
                "externalSessionId": "legacy-upstream-session",
                "context_id": "legacy-context",
            },
        )
    )

    conversation_id = await conversation_identity_service.bind_external_session(
        async_db_session,
        user_id=user.id,
        conversation_id=None,
        provider="opencode",
        external_session_id="legacy-upstream-session",
        agent_id=agent.id,
        agent_source="personal",
        context_id="legacy-context",
        title="Legacy Session",
        binding_metadata={
            "provider": "opencode",
            "externalSessionId": "legacy-upstream-session",
        },
    )
    await async_db_session.commit()

    legacy_rows_before = (
        await async_db_session.execute(
            select(AgentMessage).where(
                AgentMessage.session_id == manual_session.id,
                AgentMessage.conversation_id.is_(None),
            )
        )
    ).scalars()
    assert len(list(legacy_rows_before)) == 2

    manual_key = build_manual_session_key(manual_session.id)
    async with create_test_client(
        me_sessions.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.post(
            f"/me/sessions/{manual_key}/messages:query",
            json={"page": 1, "size": 50},
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["pagination"]["total"] == 2
        assert payload["meta"]["conversationId"] == str(conversation_id)

    legacy_rows_after = (
        await async_db_session.execute(
            select(AgentMessage).where(
                AgentMessage.session_id == manual_session.id,
                AgentMessage.conversation_id == conversation_id,
            )
        )
    ).scalars()
    assert len(list(legacy_rows_after)) == 2
