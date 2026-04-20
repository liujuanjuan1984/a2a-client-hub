from __future__ import annotations

from tests.hub_assistant import hub_assistant_support as support
from tests.hub_assistant.hub_assistant_support import (
    UUID,
    AgentMessage,
    Any,
    _approval_answer,
    _configure_swival_settings,
    _FakeSwivalSession,
    _install_fake_swival,
    _new_conversation_id,
    _reset_hub_assistant_runtime,
    cast,
    create_test_client,
    create_user,
    dispatch_due_hub_assistant_tasks,
    hub_assistant_agent_router,
    hub_assistant_service,
    pytest,
    select,
    session_hub_service,
    settings,
    uuid4,
)

pytestmark = support.pytestmark


async def test_hub_assistant_profile_route_requires_auth(async_session_maker) -> None:
    _reset_hub_assistant_runtime()
    async with create_test_client(
        hub_assistant_agent_router.router,
        async_session_maker=async_session_maker,
        base_prefix=settings.api_v1_prefix,
    ) as client:
        response = await client.get(f"{settings.api_v1_prefix}/me/hub-assistant")

    assert response.status_code == 401


async def test_hub_assistant_run_route_returns_swival_result(
    async_session_maker,
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_hub_assistant_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()

    async with create_test_client(
        hub_assistant_agent_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as client:
        profile_response = await client.get(
            f"{settings.api_v1_prefix}/me/hub-assistant"
        )
        run_response = await client.post(
            f"{settings.api_v1_prefix}/me/hub-assistant:run",
            json={"conversationId": conversation_id, "message": "Pause my job"},
        )

    assert profile_response.status_code == 200
    assert profile_response.json()["resources"] == [
        "agents",
        "followups",
        "jobs",
        "sessions",
    ]
    assert [item["operation_id"] for item in profile_response.json()["tools"]] == [
        "hub_assistant.agents.check_health",
        "hub_assistant.agents.check_health_all",
        "hub_assistant.agents.create",
        "hub_assistant.agents.delete",
        "hub_assistant.agents.get",
        "hub_assistant.agents.list",
        "hub_assistant.agents.start_sessions",
        "hub_assistant.agents.update_config",
        "hub_assistant.followups.get",
        "hub_assistant.followups.set_sessions",
        "hub_assistant.jobs.create",
        "hub_assistant.jobs.delete",
        "hub_assistant.jobs.get",
        "hub_assistant.jobs.list",
        "hub_assistant.jobs.pause",
        "hub_assistant.jobs.resume",
        "hub_assistant.jobs.update",
        "hub_assistant.jobs.update_prompt",
        "hub_assistant.jobs.update_schedule",
        "hub_assistant.sessions.archive",
        "hub_assistant.sessions.get",
        "hub_assistant.sessions.get_latest_messages",
        "hub_assistant.sessions.list",
        "hub_assistant.sessions.send_message",
        "hub_assistant.sessions.unarchive",
        "hub_assistant.sessions.update",
    ]
    assert run_response.status_code == 200
    assert run_response.json() == {
        "status": "completed",
        "answer": "Hub Assistant reply",
        "exhausted": False,
        "runtime": "swival",
        "resources": ["agents", "followups", "jobs", "sessions"],
        "tools": [
            "hub_assistant.agents.get",
            "hub_assistant.agents.list",
            "hub_assistant.followups.get",
            "hub_assistant.followups.set_sessions",
            "hub_assistant.jobs.get",
            "hub_assistant.jobs.list",
            "hub_assistant.sessions.get",
            "hub_assistant.sessions.get_latest_messages",
            "hub_assistant.sessions.list",
        ],
        "write_tools_enabled": False,
        "interrupt": None,
        "continuation": None,
    }


async def test_hub_assistant_run_route_logs_traceback_for_unavailable_error(
    async_session_maker,
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_hub_assistant_runtime()
    user = await create_user(async_db_session)
    logged: list[dict[str, Any]] = []

    async def _raise_unavailable(**_kwargs: Any) -> Any:
        raise hub_assistant_agent_router.HubAssistantUnavailableError("swival failed")

    def _capture(message: str, *args: Any, **kwargs: Any) -> None:
        logged.append({"message": message, **kwargs})

    monkeypatch.setattr(
        hub_assistant_agent_router.hub_assistant_service,
        "run",
        _raise_unavailable,
    )
    monkeypatch.setattr(hub_assistant_agent_router.logger, "exception", _capture)

    async with create_test_client(
        hub_assistant_agent_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as client:
        response = await client.post(
            f"{settings.api_v1_prefix}/me/hub-assistant:run",
            json={"conversationId": _new_conversation_id(), "message": "List my jobs"},
        )

    assert response.status_code == 502
    assert response.json()["detail"] == "swival failed"
    assert len(logged) == 1
    assert logged[0]["message"] == "Hub Assistant run failed"
    assert logged[0]["extra"]["user_id"] == str(user.id)
    assert isinstance(logged[0]["extra"]["conversation_id"], str)


async def test_hub_assistant_run_route_invalid_conversation_id_returns_400(
    async_session_maker,
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_hub_assistant_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)

    async with create_test_client(
        hub_assistant_agent_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as client:
        response = await client.post(
            f"{settings.api_v1_prefix}/me/hub-assistant:run",
            json={"conversationId": "test-1", "message": "List my jobs"},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid_conversation_id"


async def test_hub_assistant_run_persists_session_thread_and_messages(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_hub_assistant_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()

    result = await hub_assistant_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="List my jobs",
        allow_write_tools=False,
    )

    assert result.status == "completed"

    session_item, _db_mutated = await session_hub_service.get_session(
        async_db_session,
        user_id=cast(Any, user.id),
        conversation_id=conversation_id,
    )
    assert session_item["conversationId"] == conversation_id
    assert session_item["agent_id"] == "hub-assistant"
    assert session_item["agent_source"] == "hub_assistant"

    messages, _extra, _db_mutated = await session_hub_service.list_messages(
        async_db_session,
        user_id=cast(Any, user.id),
        conversation_id=conversation_id,
        before=None,
        limit=20,
    )
    assert [item["role"] for item in messages] == ["user", "agent"]
    assert messages[0]["content"] == "List my jobs"
    assert messages[1]["content"] == "Hub Assistant reply"


async def test_hub_assistant_run_persists_supplied_message_ids(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_hub_assistant_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()
    user_message_id = uuid4()
    agent_message_id = uuid4()

    result = await hub_assistant_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="List my jobs",
        user_message_id=user_message_id,
        agent_message_id=agent_message_id,
        allow_write_tools=False,
    )

    assert result.status == "completed"

    messages, _extra, _db_mutated = await session_hub_service.list_messages(
        async_db_session,
        user_id=cast(Any, user.id),
        conversation_id=conversation_id,
        before=None,
        limit=20,
    )
    assert messages[0]["id"] == str(user_message_id)
    assert messages[1]["id"] == str(agent_message_id)


async def test_hub_assistant_interrupt_and_resolution_are_persisted(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_hub_assistant_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()
    _FakeSwivalSession.next_answer = _approval_answer(
        "I can pause the requested job after you approve write access.",
        "hub_assistant.jobs.pause",
    )

    interrupt_result = await hub_assistant_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="Pause my job",
        allow_write_tools=False,
    )
    assert interrupt_result.interrupt is not None

    reject_outcome = await hub_assistant_service.reply_permission_interrupt(
        db=async_db_session,
        current_user=user,
        request_id=interrupt_result.interrupt.request_id,
        reply="reject",
    )
    assert reject_outcome.answer == "Write approval was rejected. No changes were made."

    messages, _extra, _db_mutated = await session_hub_service.list_messages(
        async_db_session,
        user_id=cast(Any, user.id),
        conversation_id=conversation_id,
        before=None,
        limit=20,
    )
    assert [item["role"] for item in messages] == ["user", "agent", "agent"]

    system_messages = list(
        (
            await async_db_session.scalars(
                select(AgentMessage)
                .where(
                    AgentMessage.user_id == cast(Any, user.id),
                    AgentMessage.conversation_id == UUID(conversation_id),
                    AgentMessage.sender == "system",
                )
                .order_by(AgentMessage.created_at.asc(), AgentMessage.id.asc())
            )
        ).all()
    )
    assert len(system_messages) == 2
    asked_interrupt = cast(dict[str, Any], system_messages[0].message_metadata)[
        "interrupt"
    ]
    resolved_interrupt = cast(dict[str, Any], system_messages[1].message_metadata)[
        "interrupt"
    ]
    assert asked_interrupt["phase"] == "asked"
    assert asked_interrupt["type"] == "permission"
    assert resolved_interrupt["phase"] == "resolved"
    assert resolved_interrupt["resolution"] == "rejected"


async def test_hub_assistant_permission_reply_persists_supplied_agent_message_id(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_hub_assistant_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()
    _FakeSwivalSession.next_answer = _approval_answer(
        "I can pause the requested job after you approve write access.",
        "hub_assistant.jobs.pause",
    )

    interrupt_result = await hub_assistant_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="Pause my job",
        allow_write_tools=False,
    )
    assert interrupt_result.interrupt is not None

    _FakeSwivalSession.next_answer = "Paused the requested job."
    follow_up_agent_message_id = uuid4()
    outcome = await hub_assistant_service.reply_permission_interrupt(
        db=async_db_session,
        current_user=user,
        request_id=interrupt_result.interrupt.request_id,
        reply="once",
        agent_message_id=follow_up_agent_message_id,
    )
    assert outcome.status == "accepted"
    await async_db_session.commit()
    await dispatch_due_hub_assistant_tasks()

    messages, _extra, _db_mutated = await session_hub_service.list_messages(
        async_db_session,
        user_id=cast(Any, user.id),
        conversation_id=conversation_id,
        before=None,
        limit=20,
    )
    assert [item["role"] for item in messages] == ["user", "agent", "agent"]
    matching_reply = next(
        item for item in messages if item["content"] == "Paused the requested job."
    )
    assert matching_reply["id"] == str(follow_up_agent_message_id)


async def test_hub_assistant_permission_reply_background_failure_persists_error(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_hub_assistant_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()
    _FakeSwivalSession.next_answer = _approval_answer(
        "I can pause the requested job after you approve write access.",
        "hub_assistant.jobs.pause",
    )

    interrupt_result = await hub_assistant_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="Pause my job",
        allow_write_tools=False,
    )
    assert interrupt_result.interrupt is not None

    _FakeSwivalSession.next_error = RuntimeError("write tool failed")
    follow_up_agent_message_id = uuid4()
    await hub_assistant_service.reply_permission_interrupt(
        db=async_db_session,
        current_user=user,
        request_id=interrupt_result.interrupt.request_id,
        reply="once",
        agent_message_id=follow_up_agent_message_id,
    )
    await async_db_session.commit()
    await dispatch_due_hub_assistant_tasks()

    messages, _extra, _db_mutated = await session_hub_service.list_messages(
        async_db_session,
        user_id=cast(Any, user.id),
        conversation_id=conversation_id,
        before=None,
        limit=20,
    )
    matching_reply = next(
        item for item in messages if item["id"] == str(follow_up_agent_message_id)
    )
    assert matching_reply["role"] == "agent"
    assert matching_reply["status"] == "error"
    assert "write tool failed" in matching_reply["content"]


async def test_hub_assistant_permission_reply_background_interrupt_persists_new_interrupt(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_hub_assistant_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()
    _FakeSwivalSession.next_answer = _approval_answer(
        "I can pause the requested job after you approve write access.",
        "hub_assistant.jobs.pause",
    )

    interrupt_result = await hub_assistant_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="Pause my job",
        allow_write_tools=False,
    )
    assert interrupt_result.interrupt is not None

    _FakeSwivalSession.next_answer = _approval_answer(
        "Deleting that agent requires additional approval.",
        "hub_assistant.agents.delete",
    )
    outcome = await hub_assistant_service.reply_permission_interrupt(
        db=async_db_session,
        current_user=user,
        request_id=interrupt_result.interrupt.request_id,
        reply="once",
    )
    await async_db_session.commit()
    await dispatch_due_hub_assistant_tasks()

    messages, _extra, _db_mutated = await session_hub_service.list_messages(
        async_db_session,
        user_id=cast(Any, user.id),
        conversation_id=conversation_id,
        before=None,
        limit=20,
    )
    interrupted_reply = next(
        item
        for item in messages
        if item["id"] == str(outcome.continuation.agent_message_id)
    )
    assert interrupted_reply["role"] == "agent"
    assert interrupted_reply["status"] == "interrupted"

    recovered = await hub_assistant_service.recover_pending_interrupts(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
    )
    assert len(recovered) == 1
    assert recovered[0].details["patterns"] == ["hub_assistant.agents.delete"]


async def test_hub_assistant_can_recover_unresolved_permission_interrupts(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_hub_assistant_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()
    _FakeSwivalSession.next_answer = _approval_answer(
        "I can pause the requested job after you approve write access.",
        "hub_assistant.jobs.pause",
    )

    interrupt_result = await hub_assistant_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="Pause my job",
        allow_write_tools=False,
    )

    recovered = await hub_assistant_service.recover_pending_interrupts(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
    )

    assert interrupt_result.interrupt is not None
    assert len(recovered) == 1
    assert recovered[0].request_id == interrupt_result.interrupt.request_id
    assert recovered[0].session_id == conversation_id
    assert recovered[0].type == "permission"
    assert recovered[0].details["permission"] == "hub-assistant-write"
    assert recovered[0].details["patterns"] == ["hub_assistant.jobs.pause"]


async def test_hub_assistant_recovery_ignores_resolved_interrupts(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_hub_assistant_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()
    _FakeSwivalSession.next_answer = _approval_answer(
        "I can pause the requested job after you approve write access.",
        "hub_assistant.jobs.pause",
    )

    interrupt_result = await hub_assistant_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="Pause my job",
        allow_write_tools=False,
    )
    assert interrupt_result.interrupt is not None

    await hub_assistant_service.reply_permission_interrupt(
        db=async_db_session,
        current_user=user,
        request_id=interrupt_result.interrupt.request_id,
        reply="reject",
    )

    recovered = await hub_assistant_service.recover_pending_interrupts(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
    )

    assert recovered == []
