from __future__ import annotations

from tests.hub_assistant import hub_assistant_support as support
from tests.hub_assistant.hub_assistant_support import (
    UUID,
    AgentMessage,
    Any,
    ConversationThread,
    ModuleType,
    SimpleNamespace,
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
    get_hub_assistant_interrupt_message,
    get_hub_assistant_interrupt_tool_names,
    get_hub_assistant_operation_ids,
    hub_assistant_agent_router,
    hub_assistant_agent_service_module,
    hub_assistant_service,
    pytest,
    select,
    settings,
    sys,
    uuid4,
    verify_jwt_token_claims,
)

pytestmark = support.pytestmark


async def test_hub_assistant_run_route_allows_write_tools_only_when_explicitly_enabled(
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
        run_response = await client.post(
            f"{settings.api_v1_prefix}/me/hub-assistant:run",
            json={
                "conversationId": conversation_id,
                "message": "Pause my job",
                "allow_write_tools": True,
            },
        )

    assert run_response.status_code == 200
    assert run_response.json()["status"] == "completed"
    assert run_response.json()["write_tools_enabled"] is True
    assert "hub_assistant.jobs.pause" in run_response.json()["tools"]


async def test_hub_assistant_read_only_run_can_raise_permission_interrupt(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_hub_assistant_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    _FakeSwivalSession.next_answer = _approval_answer(
        "I can pause the requested job after you approve write access.",
        "hub_assistant.jobs.pause",
    )
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()

    result = await hub_assistant_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="Pause my job",
        allow_write_tools=False,
    )

    assert result.status == "interrupted"
    assert (
        result.answer == "I can pause the requested job after you approve write access."
    )
    assert result.write_tools_enabled is False
    assert result.interrupt is not None
    assert result.interrupt.permission == "hub-assistant-write"
    assert result.interrupt.patterns == ("hub_assistant.jobs.pause",)
    claims = verify_jwt_token_claims(
        result.interrupt.request_id,
        expected_type="hub_assistant_interrupt",
    )
    assert claims is not None
    assert claims.subject == str(user.id)
    assert get_hub_assistant_interrupt_message(claims) == "Pause my job"
    assert get_hub_assistant_interrupt_tool_names(claims) == (
        "hub_assistant.jobs.pause",
    )
    assert get_hub_assistant_operation_ids(claims) == frozenset(
        {"hub_assistant.jobs.pause"}
    )


async def test_hub_assistant_permission_reply_once_resumes_with_write_tools(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_hub_assistant_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()
    interrupt = hub_assistant_service._runtime.build_permission_interrupt(
        current_user=user,
        conversation_id=conversation_id,
        message="Pause my job",
        answer="Need approval",
        requested_write_operation_ids=("hub_assistant.jobs.pause",),
    )

    outcome = await hub_assistant_service.reply_permission_interrupt(
        db=async_db_session,
        current_user=user,
        request_id=interrupt.request_id,
        reply="once",
    )
    assert outcome.status == "accepted"
    assert outcome.write_tools_enabled is True
    assert "hub_assistant.jobs.pause" in outcome.tool_names
    assert "hub_assistant.sessions.update" not in outcome.tool_names
    assert _FakeSwivalSession.ask_call_count == 0
    await async_db_session.commit()
    await dispatch_due_hub_assistant_tasks()
    assert _FakeSwivalSession.ask_call_count == 1
    assert _FakeSwivalSession.last_message == "Pause my job"
    assert _FakeSwivalSession.last_init_kwargs is not None
    assert _FakeSwivalSession.last_init_kwargs["mcp_servers"]["a2a-client-hub"][
        "url"
    ] == ("http://internal-mcp/mcp-write/")
    assert _FakeSwivalSession.instance_count == 1


async def test_hub_assistant_session_refresh_preserves_new_system_prompt(
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

    outcome = await hub_assistant_service.reply_permission_interrupt(
        db=async_db_session,
        current_user=user,
        request_id=interrupt_result.interrupt.request_id,
        reply="once",
    )
    assert outcome.status == "accepted"
    await async_db_session.commit()
    await dispatch_due_hub_assistant_tasks()
    assert _FakeSwivalSession.instance_count == 2
    assert _FakeSwivalSession.instances[1]._conv_state is not None
    next_messages = cast(
        list[dict[str, str]], _FakeSwivalSession.instances[1]._conv_state["messages"]
    )
    assert next_messages[0]["role"] == "system"
    assert (
        "This run includes explicitly approved write tools."
        in next_messages[0]["content"]
    )
    assert "The currently approved write operations are: hub_assistant.jobs.pause." in (
        next_messages[0]["content"]
    )
    assert next_messages[1:3] == [
        {"role": "user", "content": "Pause my job"},
        {
            "role": "assistant",
            "content": "I can pause the requested job after you approve write access.\n"
            "[[HUB_ASSISTANT_WRITE_APPROVAL_REQUIRED]]\n"
            "[[HUB_ASSISTANT_WRITE_OPERATIONS:hub_assistant.jobs.pause]]",
        },
    ]


async def test_hub_assistant_permission_reply_reject_returns_no_change_result(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_hub_assistant_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()
    interrupt = hub_assistant_service._runtime.build_permission_interrupt(
        current_user=user,
        conversation_id=conversation_id,
        message="Pause my job",
        answer="Need approval",
        requested_write_operation_ids=("hub_assistant.jobs.pause",),
    )

    outcome = await hub_assistant_service.reply_permission_interrupt(
        db=async_db_session,
        current_user=user,
        request_id=interrupt.request_id,
        reply="reject",
    )
    assert outcome.status == "completed"
    assert outcome.answer == "Write approval was rejected. No changes were made."
    assert outcome.write_tools_enabled is False
    assert outcome.exhausted is False
    assert _FakeSwivalSession.ask_call_count == 0


async def test_hub_assistant_permission_reply_route_resumes_or_rejects(
    async_session_maker,
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

    async with create_test_client(
        hub_assistant_agent_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as client:
        interrupt_response = await client.post(
            f"{settings.api_v1_prefix}/me/hub-assistant:run",
            json={"conversationId": conversation_id, "message": "Pause my job"},
        )
        assert interrupt_response.status_code == 200
        interrupt_payload = interrupt_response.json()
        assert interrupt_payload["status"] == "interrupted"
        request_id = interrupt_payload["interrupt"]["requestId"]

        _FakeSwivalSession.next_answer = "Paused the requested job."
        approve_response = await client.post(
            f"{settings.api_v1_prefix}/me/hub-assistant/interrupts/permission:reply",
            json={"requestId": request_id, "reply": "once"},
        )

    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "accepted"
    assert approve_response.json()["write_tools_enabled"] is True
    assert approve_response.json()["interrupt"] is None
    assert approve_response.json()["continuation"]["phase"] == "running"
    await dispatch_due_hub_assistant_tasks()


async def test_hub_assistant_interrupt_recovery_route_returns_unresolved_interrupts(
    async_session_maker,
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

    await hub_assistant_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="Pause my job",
        allow_write_tools=False,
    )
    await async_db_session.commit()

    async with create_test_client(
        hub_assistant_agent_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as client:
        response = await client.post(
            f"{settings.api_v1_prefix}/me/hub-assistant/interrupts:recover",
            json={"conversationId": conversation_id},
        )

    assert response.status_code == 200
    assert response.json()["items"] == [
        {
            "requestId": response.json()["items"][0]["requestId"],
            "sessionId": conversation_id,
            "type": "permission",
            "phase": "asked",
            "details": {
                "permission": "hub-assistant-write",
                "patterns": ["hub_assistant.jobs.pause"],
                "displayMessage": "I can pause the requested job after you approve write access.",
            },
        }
    ]


async def test_hub_assistant_interrupt_recovery_route_persists_expired_interrupts(
    async_session_maker,
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_hub_assistant_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    persisted_user_id = cast(Any, user.id)
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
    await async_db_session.commit()

    original_verify = hub_assistant_agent_service_module.verify_jwt_token_claims
    invalid_request_id = interrupt_result.interrupt.request_id
    monkeypatch.setattr(
        hub_assistant_agent_service_module,
        "verify_jwt_token_claims",
        lambda token, *, expected_type: (
            None
            if token == invalid_request_id
            else original_verify(token, expected_type=expected_type)
        ),
    )

    async with create_test_client(
        hub_assistant_agent_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as client:
        response = await client.post(
            f"{settings.api_v1_prefix}/me/hub-assistant/interrupts:recover",
            json={"conversationId": conversation_id},
        )

    assert response.status_code == 200
    assert response.json()["items"] == []

    await async_db_session.rollback()
    system_messages = list(
        (
            await async_db_session.scalars(
                select(AgentMessage)
                .where(
                    AgentMessage.user_id == persisted_user_id,
                    AgentMessage.conversation_id == UUID(conversation_id),
                    AgentMessage.sender == "system",
                )
                .order_by(AgentMessage.created_at.asc(), AgentMessage.id.asc())
            )
        ).all()
    )
    assert len(system_messages) == 2


async def test_hub_assistant_interrupt_recovery_route_returns_unresolved_interrupts_for_archived_conversation(
    async_session_maker,
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

    await hub_assistant_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="Pause my job",
        allow_write_tools=False,
    )
    thread = await async_db_session.get(ConversationThread, UUID(conversation_id))
    assert thread is not None
    thread.status = ConversationThread.STATUS_ARCHIVED
    await async_db_session.commit()

    async with create_test_client(
        hub_assistant_agent_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as client:
        response = await client.post(
            f"{settings.api_v1_prefix}/me/hub-assistant/interrupts:recover",
            json={"conversationId": conversation_id},
        )

    assert response.status_code == 200
    assert response.json()["items"] == [
        {
            "requestId": response.json()["items"][0]["requestId"],
            "sessionId": conversation_id,
            "type": "permission",
            "phase": "asked",
            "details": {
                "permission": "hub-assistant-write",
                "patterns": ["hub_assistant.jobs.pause"],
                "displayMessage": "I can pause the requested job after you approve write access.",
            },
        }
    ]


async def test_hub_assistant_recovery_skips_invalid_interrupt_requests(
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

    original_verify = hub_assistant_agent_service_module.verify_jwt_token_claims
    invalid_request_id = interrupt_result.interrupt.request_id
    monkeypatch.setattr(
        hub_assistant_agent_service_module,
        "verify_jwt_token_claims",
        lambda token, *, expected_type: (
            None
            if token == invalid_request_id
            else original_verify(token, expected_type=expected_type)
        ),
    )

    recovered = await hub_assistant_service.recover_pending_permission_interrupts(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
    )

    assert recovered == []

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
    resolved_interrupt = cast(dict[str, Any], system_messages[1].message_metadata)[
        "interrupt"
    ]
    assert resolved_interrupt["phase"] == "resolved"
    assert resolved_interrupt["resolution"] == "expired"


async def test_hub_assistant_recovery_skips_interrupts_for_other_conversations(
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

    monkeypatch.setattr(
        hub_assistant_agent_service_module,
        "get_hub_assistant_interrupt_conversation_id",
        lambda _claims: str(uuid4()),
    )

    recovered = await hub_assistant_service.recover_pending_permission_interrupts(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
    )

    assert recovered == []


async def test_hub_assistant_permission_reply_route_returns_terminal_error_code_for_expired_request(
    async_session_maker,
    async_db_session,
) -> None:
    _reset_hub_assistant_runtime()
    user = await create_user(async_db_session)

    async with create_test_client(
        hub_assistant_agent_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as client:
        response = await client.post(
            f"{settings.api_v1_prefix}/me/hub-assistant/interrupts/permission:reply",
            json={"requestId": "expired-request", "reply": "always"},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "message": "The write approval request is invalid or expired.",
        "error_code": "interrupt_request_expired",
    }


async def test_hub_assistant_permission_reply_route_logs_traceback_for_unavailable_error(
    async_session_maker,
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_hub_assistant_runtime()
    user = await create_user(async_db_session)
    logged: list[dict[str, Any]] = []

    async def _raise_unavailable(**_kwargs: Any) -> Any:
        raise hub_assistant_agent_router.HubAssistantUnavailableError(
            "invalid approval request"
        )

    def _capture(message: str, *args: Any, **kwargs: Any) -> None:
        logged.append({"message": message, **kwargs})

    monkeypatch.setattr(
        hub_assistant_agent_router.hub_assistant_service,
        "reply_permission_interrupt",
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
            f"{settings.api_v1_prefix}/me/hub-assistant/interrupts/permission:reply",
            json={"requestId": "req-1", "reply": "once"},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid approval request"
    assert logged == [
        {
            "message": "Hub Assistant permission reply failed",
            "extra": {
                "user_id": str(user.id),
                "request_id": "req-1",
                "reply": "once",
            },
        }
    ]


async def test_hub_assistant_permission_reply_route_rejects_other_user_interrupt(
    async_session_maker,
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_hub_assistant_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    owner = await create_user(async_db_session)
    other_user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()
    interrupt = hub_assistant_service._runtime.build_permission_interrupt(
        current_user=owner,
        conversation_id=conversation_id,
        message="Pause my job",
        answer="Need approval",
        requested_write_operation_ids=("hub_assistant.jobs.pause",),
    )

    async with create_test_client(
        hub_assistant_agent_router.router,
        async_session_maker=async_session_maker,
        current_user=other_user,
        base_prefix=settings.api_v1_prefix,
    ) as client:
        response = await client.post(
            f"{settings.api_v1_prefix}/me/hub-assistant/interrupts/permission:reply",
            json={"requestId": interrupt.request_id, "reply": "once"},
        )

    assert response.status_code == 400
    assert "does not belong to the current user" in response.json()["detail"]


async def test_hub_assistant_reuses_conversation_session_for_follow_up_turns(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_hub_assistant_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()

    await hub_assistant_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="List my jobs",
        allow_write_tools=False,
    )
    await hub_assistant_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="Now list my agents",
        allow_write_tools=False,
    )

    assert _FakeSwivalSession.instance_count == 1
    assert _FakeSwivalSession.ask_call_count == 2
    assert _FakeSwivalSession.instances[0]._conv_state is not None
    assert len(_FakeSwivalSession.instances[0]._conv_state["messages"]) == 5


async def test_hub_assistant_rehydrates_runtime_from_durable_history_after_registry_loss(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_hub_assistant_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()

    await hub_assistant_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="List my jobs",
        allow_write_tools=False,
    )
    _reset_hub_assistant_runtime()

    await hub_assistant_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="Now list my agents",
        allow_write_tools=False,
    )

    assert _FakeSwivalSession.instance_count == 2
    assert _FakeSwivalSession.ask_call_count == 2
    assert _FakeSwivalSession.instances[1]._conv_state is not None
    assert len(_FakeSwivalSession.instances[1]._conv_state["messages"]) == 5
    assert _FakeSwivalSession.instances[1]._conv_state["messages"][0] == {
        "role": "system",
        "content": cast(str, _FakeSwivalSession.instances[1]._system_prompt),
    }
    assert _FakeSwivalSession.instances[1]._conv_state["messages"][1] == {
        "role": "user",
        "content": "List my jobs",
    }
    assert _FakeSwivalSession.instances[1]._conv_state["messages"][2] == {
        "role": "assistant",
        "content": "Hub Assistant reply",
    }


async def test_hub_assistant_permission_reply_always_enables_session_scoped_write_tools(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_hub_assistant_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()
    interrupt = hub_assistant_service._runtime.build_permission_interrupt(
        current_user=user,
        conversation_id=conversation_id,
        message="Pause my job",
        answer="Need approval",
        requested_write_operation_ids=("hub_assistant.jobs.pause",),
    )

    always_outcome = await hub_assistant_service.reply_permission_interrupt(
        db=async_db_session,
        current_user=user,
        request_id=interrupt.request_id,
        reply="always",
    )
    assert always_outcome.status == "accepted"
    await async_db_session.commit()
    await dispatch_due_hub_assistant_tasks()
    follow_up_result = await hub_assistant_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="Pause it now",
        allow_write_tools=False,
    )

    assert always_outcome.write_tools_enabled is True
    assert follow_up_result.write_tools_enabled is True
    assert "hub_assistant.jobs.pause" in follow_up_result.tool_names
    assert "hub_assistant.sessions.update" not in follow_up_result.tool_names
    assert _FakeSwivalSession.instance_count == 1
    assert _FakeSwivalSession.ask_call_count == 2
    assert _FakeSwivalSession.last_init_kwargs is not None
    assert _FakeSwivalSession.last_init_kwargs["mcp_servers"]["a2a-client-hub"][
        "url"
    ] == ("http://internal-mcp/mcp-write/")


async def test_hub_assistant_requests_additional_approval_for_new_write_operations(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_hub_assistant_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()
    interrupt = hub_assistant_service._runtime.build_permission_interrupt(
        current_user=user,
        conversation_id=conversation_id,
        message="Pause my job",
        answer="Need approval",
        requested_write_operation_ids=("hub_assistant.jobs.pause",),
    )

    await hub_assistant_service.reply_permission_interrupt(
        db=async_db_session,
        current_user=user,
        request_id=interrupt.request_id,
        reply="always",
    )
    await async_db_session.commit()
    await dispatch_due_hub_assistant_tasks()

    _FakeSwivalSession.next_answer = _approval_answer(
        "Deleting that agent requires additional approval.",
        "hub_assistant.agents.delete",
    )
    follow_up_result = await hub_assistant_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="Delete my agent",
        allow_write_tools=False,
    )

    assert follow_up_result.status == "interrupted"
    assert follow_up_result.write_tools_enabled is True
    assert follow_up_result.interrupt is not None
    assert follow_up_result.interrupt.patterns == ("hub_assistant.agents.delete",)

    _FakeSwivalSession.next_answer = "Deleted the requested agent."
    resumed_outcome = await hub_assistant_service.reply_permission_interrupt(
        db=async_db_session,
        current_user=user,
        request_id=follow_up_result.interrupt.request_id,
        reply="once",
    )
    assert resumed_outcome.status == "accepted"
    await async_db_session.commit()
    await dispatch_due_hub_assistant_tasks()
    assert resumed_outcome.write_tools_enabled is True
    assert resumed_outcome.tool_names == ("hub_assistant.agents.delete",)
    assert "hub_assistant.sessions.update" not in resumed_outcome.tool_names


async def test_hub_assistant_runtime_patches_private_swival_mcp_tool_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_hub_assistant_runtime()
    _configure_swival_settings(monkeypatch)

    swival_module = ModuleType("swival")
    swival_module.Session = _FakeSwivalSession
    mcp_module = ModuleType("swival.mcp_client")

    def _fake_converter(
        _server_name: str, tool: object
    ) -> tuple[dict[str, object], str]:
        return (
            {
                "type": "function",
                "function": {
                    "name": "mcp__demo__tool",
                    "_mcp_original_name": getattr(tool, "name", "demo.tool"),
                },
            },
            getattr(tool, "name", "demo.tool"),
        )

    mcp_module._mcp_tool_to_openai = _fake_converter
    monkeypatch.setitem(sys.modules, "swival", swival_module)
    monkeypatch.setitem(sys.modules, "swival.mcp_client", mcp_module)

    session_cls = hub_assistant_service._runtime.load_swival_session_cls()

    assert session_cls is _FakeSwivalSession
    schema, _original_name = mcp_module._mcp_tool_to_openai(
        "demo", SimpleNamespace(name="demo.tool")
    )
    assert schema["function"]["name"] == "mcp__demo__tool"
    assert "_mcp_original_name" not in schema["function"]
