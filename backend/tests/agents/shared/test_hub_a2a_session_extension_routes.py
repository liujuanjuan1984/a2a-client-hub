from __future__ import annotations

from tests.agents.shared import hub_a2a_extensions_routes_support as support
from tests.agents.shared.hub_a2a_extensions_routes_support import (
    Any,
    _create_allowlisted_hub_agent,
    _FakeExtensionsService,
    create_test_client,
    extension_router_common,
    hub_extension_router,
    pytest,
    settings,
)

pytestmark = support.pytestmark


@pytest.mark.asyncio
async def test_hub_opencode_routes_use_hub_runtime_and_remain_non_enumerable(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    agent_id, user = await _create_allowlisted_hub_agent(
        async_session_maker=async_session_maker,
        async_db_session=async_db_session,
        admin_email="admin_opencode_ok@example.com",
        user_email="alice_opencode_ok@example.com",
        token="secret-token-opencode",
    )

    fake_extensions = _FakeExtensionsService()
    monkeypatch.setattr(
        extension_router_common,
        "get_a2a_extensions_service",
        lambda: fake_extensions,
    )

    async with create_test_client(
        hub_extension_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as user_client:
        continue_resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/sessions/sess-1:continue"
        )
        assert continue_resp.status_code == 200
        continue_payload = continue_resp.json()
        assert continue_payload["success"] is True

        sessions_resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/sessions:query",
            json={"page": 1, "size": 20, "query": {}},
        )
        assert sessions_resp.status_code == 200
        sessions_payload = sessions_resp.json()
        assert sessions_payload["success"] is True

        messages_resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/sessions/sess-1/messages:query",
            json={"page": 1, "size": 50, "query": {}},
        )
        assert messages_resp.status_code == 200
        messages_payload = messages_resp.json()
        assert messages_payload["success"] is True

        permission_reply_resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/interrupts/permission:reply",
            json={
                "request_id": "perm-1",
                "reply": "once",
                "metadata": {"provider": "opencode", "requestScope": "shared"},
            },
        )
        assert permission_reply_resp.status_code == 200
        assert permission_reply_resp.json()["result"] == {
            "ok": True,
            "request_id": "perm-1",
        }

        question_reply_resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/interrupts/question:reply",
            json={
                "request_id": "q-1",
                "answers": [["A"], ["B"]],
                "metadata": {"provider": "opencode", "requestScope": "shared"},
            },
        )
        assert question_reply_resp.status_code == 200
        assert question_reply_resp.json()["result"] == {
            "ok": True,
            "request_id": "q-1",
        }

        question_reject_resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/interrupts/question:reject",
            json={
                "request_id": "q-2",
                "metadata": {"provider": "opencode", "requestScope": "shared"},
            },
        )
        assert question_reject_resp.status_code == 200
        assert question_reject_resp.json()["result"] == {
            "ok": True,
            "request_id": "q-2",
        }

        permissions_reply_resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/interrupts/permissions:reply",
            json={
                "request_id": "perm-v2-1",
                "permissions": {"fileSystem": {"write": ["/workspace/project"]}},
                "scope": "session",
                "metadata": {"provider": "opencode", "requestScope": "shared"},
            },
        )
        assert permissions_reply_resp.status_code == 200
        assert permissions_reply_resp.json()["result"] == {
            "ok": True,
            "request_id": "perm-v2-1",
        }

        elicitation_reply_resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/interrupts/elicitation:reply",
            json={
                "request_id": "eli-1",
                "action": "accept",
                "content": {"approved": True},
                "metadata": {"provider": "opencode", "requestScope": "shared"},
            },
        )
        assert elicitation_reply_resp.status_code == 200
        assert elicitation_reply_resp.json()["result"] == {
            "ok": True,
            "request_id": "eli-1",
        }

        interrupt_recovery_resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/interrupts:recover",
            json={"sessionId": "sess-1"},
        )
        assert interrupt_recovery_resp.status_code == 200
        assert interrupt_recovery_resp.json() == {
            "items": [
                {
                    "requestId": "perm-1",
                    "sessionId": "sess-1",
                    "type": "permission",
                    "details": {"permission": "write"},
                    "expiresAt": 123.0,
                    "source": "recovery",
                }
            ]
        }

        prompt_async_resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/sessions/sess-1:prompt-async",
            json={
                "request": {
                    "parts": [{"type": "text", "text": "Continue and summarize"}],
                    "noReply": True,
                },
                "metadata": {"provider": "opencode", "externalSessionId": "sess-1"},
            },
        )
        assert prompt_async_resp.status_code == 200
        assert prompt_async_resp.json()["result"] == {
            "ok": True,
            "session_id": "sess-1",
        }

        command_resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/sessions/sess-1:command",
            json={
                "request": {
                    "command": "/review",
                    "arguments": "--quick",
                    "parts": [{"type": "text", "text": "Focus on tests"}],
                },
                "metadata": {"provider": "opencode", "externalSessionId": "sess-1"},
            },
        )
        assert command_resp.status_code == 200
        assert command_resp.json()["result"] == {
            "item": {
                "kind": "message",
                "messageId": "msg-cmd-1",
                "role": "assistant",
            }
        }

    assert len(fake_extensions.calls) == 11
    prompt_calls = [
        c for c in fake_extensions.calls if c["fn"] == "prompt_session_async"
    ]
    assert len(prompt_calls) == 1
    assert prompt_calls[0]["request_payload"]["parts"][0]["text"].startswith("Continue")
    assert prompt_calls[0]["metadata"] == {
        "provider": "opencode",
        "externalSessionId": "sess-1",
    }
    command_calls = [c for c in fake_extensions.calls if c["fn"] == "command_session"]
    assert len(command_calls) == 1
    assert command_calls[0]["request_payload"]["command"] == "/review"
    assert command_calls[0]["request_payload"]["arguments"] == "--quick"
    assert command_calls[0]["metadata"] == {
        "provider": "opencode",
        "externalSessionId": "sess-1",
    }
    permission_calls = [
        c for c in fake_extensions.calls if c["fn"] == "reply_permission_interrupt"
    ]
    assert permission_calls[0]["metadata"] == {
        "provider": "opencode",
        "requestScope": "shared",
    }
    question_reply_calls = [
        c for c in fake_extensions.calls if c["fn"] == "reply_question_interrupt"
    ]
    assert question_reply_calls[0]["metadata"] == {
        "provider": "opencode",
        "requestScope": "shared",
    }
    question_reject_calls = [
        c for c in fake_extensions.calls if c["fn"] == "reject_question_interrupt"
    ]
    assert question_reject_calls[0]["metadata"] == {
        "provider": "opencode",
        "requestScope": "shared",
    }
    permissions_reply_calls = [
        c for c in fake_extensions.calls if c["fn"] == "reply_permissions_interrupt"
    ]
    assert permissions_reply_calls[0]["permissions"] == {
        "fileSystem": {"write": ["/workspace/project"]}
    }
    assert permissions_reply_calls[0]["scope"] == "session"
    assert permissions_reply_calls[0]["metadata"] == {
        "provider": "opencode",
        "requestScope": "shared",
    }
    elicitation_reply_calls = [
        c for c in fake_extensions.calls if c["fn"] == "reply_elicitation_interrupt"
    ]
    assert elicitation_reply_calls[0]["action"] == "accept"
    assert elicitation_reply_calls[0]["content"] == {"approved": True}
    assert elicitation_reply_calls[0]["metadata"] == {
        "provider": "opencode",
        "requestScope": "shared",
    }
    recovery_calls = [
        c for c in fake_extensions.calls if c["fn"] == "recover_interrupts"
    ]
    assert recovery_calls[0]["session_id"] == "sess-1"
    for call in fake_extensions.calls:
        resolved = call["runtime"].resolved
        assert resolved.headers["Authorization"].endswith("secret-token-opencode")


@pytest.mark.asyncio
async def test_hub_session_query_routes_exclude_raw_by_default_and_allow_include_raw(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    agent_id, user = await _create_allowlisted_hub_agent(
        async_session_maker=async_session_maker,
        async_db_session=async_db_session,
        admin_email="admin_opencode_envelope@example.com",
        user_email="alice_opencode_envelope@example.com",
        token="secret-token-opencode-envelope",
    )

    fake_extensions = _FakeExtensionsService()
    monkeypatch.setattr(
        extension_router_common,
        "get_a2a_extensions_service",
        lambda: fake_extensions,
    )

    async with create_test_client(
        hub_extension_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as user_client:
        sessions_resp = await user_client.get(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/sessions?page=1&size=20"
        )
        assert sessions_resp.status_code == 200
        sessions_payload = sessions_resp.json()
        assert sessions_payload["success"] is True
        assert "raw" not in sessions_payload["result"]

        sessions_raw_resp = await user_client.get(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/sessions?page=1&size=20&include_raw=true"
        )
        assert sessions_raw_resp.status_code == 200
        sessions_raw_payload = sessions_raw_resp.json()
        assert sessions_raw_payload["success"] is True
        assert sessions_raw_payload["result"]["raw"][0]["provider"] == "opencode"

        messages_raw_resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/sessions/sess-1/messages:query",
            json={
                "page": 1,
                "size": 50,
                "before": "cursor-1",
                "include_raw": True,
                "query": {},
            },
        )
        assert messages_raw_resp.status_code == 200
        messages_raw_payload = messages_raw_resp.json()
        assert messages_raw_payload["success"] is True
        assert messages_raw_payload["result"]["raw"][0]["provider"] == "opencode"
        assert messages_raw_payload["result"]["pageInfo"] == {
            "hasMoreBefore": True,
            "nextBefore": "cursor-2",
        }

    session_calls = [
        call for call in fake_extensions.calls if call["fn"] == "list_sessions"
    ]
    assert [call["include_raw"] for call in session_calls] == [False, True]
    message_calls = [
        call for call in fake_extensions.calls if call["fn"] == "get_session_messages"
    ]
    assert [call["include_raw"] for call in message_calls] == [True]
    assert [call["before"] for call in message_calls] == ["cursor-1"]


@pytest.mark.asyncio
async def test_hub_session_query_routes_forward_typed_session_list_filters(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    agent_id, user = await _create_allowlisted_hub_agent(
        async_session_maker=async_session_maker,
        async_db_session=async_db_session,
        admin_email="admin_opencode_filters@example.com",
        user_email="alice_opencode_filters@example.com",
        token="secret-token-opencode-filters",
    )

    fake_extensions = _FakeExtensionsService()
    monkeypatch.setattr(
        extension_router_common,
        "get_a2a_extensions_service",
        lambda: fake_extensions,
    )

    async with create_test_client(
        hub_extension_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as user_client:
        post_resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/sessions:query",
            json={
                "page": 1,
                "size": 20,
                "filters": {
                    "directory": "services/api",
                    "roots": True,
                    "start": 40,
                    "search": "planner",
                },
                "query": {"status": "open"},
            },
        )
        assert post_resp.status_code == 200
        assert post_resp.json()["success"] is True

        get_resp = await user_client.get(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/sessions"
            "?page=1&size=20&directory=services/api&roots=true&start=40&search=planner"
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["success"] is True

    session_calls = [
        call for call in fake_extensions.calls if call["fn"] == "list_sessions"
    ]
    assert len(session_calls) == 2
    assert session_calls[0]["query"] == {"status": "open"}
    assert session_calls[0]["filters"] == {
        "directory": "services/api",
        "roots": True,
        "start": 40,
        "search": "planner",
    }
    assert session_calls[1]["query"] is None
    assert session_calls[1]["filters"] == {
        "directory": "services/api",
        "roots": True,
        "start": 40,
        "search": "planner",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path_suffix", "expected_fn", "expected"),
    [
        ("/extensions/sessions/ses-1", "get_session", {"session_id": "ses-1"}),
        (
            "/extensions/sessions/ses-1/children",
            "get_session_children",
            {"session_id": "ses-1"},
        ),
        (
            "/extensions/sessions/ses-1/todo",
            "get_session_todo",
            {"session_id": "ses-1"},
        ),
        (
            "/extensions/sessions/ses-1/diff?messageId=msg-9",
            "get_session_diff",
            {"session_id": "ses-1", "message_id": "msg-9"},
        ),
        (
            "/extensions/sessions/ses-1/messages/msg-9",
            "get_session_message",
            {"session_id": "ses-1", "message_id": "msg-9"},
        ),
    ],
)
async def test_hub_session_management_read_routes_forward_calls(
    async_session_maker,
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
    path_suffix: str,
    expected_fn: str,
    expected: dict[str, Any],
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    agent_id, user = await _create_allowlisted_hub_agent(
        async_session_maker=async_session_maker,
        async_db_session=async_db_session,
        admin_email="admin_opencode_session_reads@example.com",
        user_email="alice_opencode_session_reads@example.com",
        token="secret-token-opencode-session-reads",
    )

    fake_extensions = _FakeExtensionsService()
    monkeypatch.setattr(
        extension_router_common,
        "get_a2a_extensions_service",
        lambda: fake_extensions,
    )

    async with create_test_client(
        hub_extension_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as user_client:
        response = await user_client.get(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}{path_suffix}"
        )

    assert response.status_code == 200
    call = next(c for c in fake_extensions.calls if c["fn"] == expected_fn)
    for key, value in expected.items():
        assert call[key] == value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path_suffix", "payload", "expected_fn", "expected"),
    [
        (
            "/extensions/sessions/ses-1:fork",
            {"request": {"messageID": "msg-1"}, "metadata": {"provider": "opencode"}},
            "fork_session",
            {
                "session_id": "ses-1",
                "request_payload": {"messageID": "msg-1"},
                "metadata": {"provider": "opencode"},
            },
        ),
        (
            "/extensions/sessions/ses-1:share",
            {"metadata": {"provider": "opencode"}},
            "share_session",
            {"session_id": "ses-1", "metadata": {"provider": "opencode"}},
        ),
        (
            "/extensions/sessions/ses-1:unshare",
            {"metadata": {"provider": "opencode"}},
            "unshare_session",
            {"session_id": "ses-1", "metadata": {"provider": "opencode"}},
        ),
        (
            "/extensions/sessions/ses-1:summarize",
            {"request": {"providerID": "openai", "auto": True}},
            "summarize_session",
            {
                "session_id": "ses-1",
                "request_payload": {"providerID": "openai", "auto": True},
                "metadata": None,
            },
        ),
        (
            "/extensions/sessions/ses-1:revert",
            {"request": {"messageID": "msg-1", "partID": "part-2"}},
            "revert_session",
            {
                "session_id": "ses-1",
                "request_payload": {"messageID": "msg-1", "partID": "part-2"},
                "metadata": None,
            },
        ),
        (
            "/extensions/sessions/ses-1:unrevert",
            {"metadata": {"provider": "opencode"}},
            "unrevert_session",
            {"session_id": "ses-1", "metadata": {"provider": "opencode"}},
        ),
    ],
)
async def test_hub_session_management_mutation_routes_forward_calls(
    async_session_maker,
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
    path_suffix: str,
    payload: dict[str, Any],
    expected_fn: str,
    expected: dict[str, Any],
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    agent_id, user = await _create_allowlisted_hub_agent(
        async_session_maker=async_session_maker,
        async_db_session=async_db_session,
        admin_email="admin_opencode_session_mutations@example.com",
        user_email="alice_opencode_session_mutations@example.com",
        token="secret-token-opencode-session-mutations",
    )

    fake_extensions = _FakeExtensionsService()
    monkeypatch.setattr(
        extension_router_common,
        "get_a2a_extensions_service",
        lambda: fake_extensions,
    )

    async with create_test_client(
        hub_extension_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as user_client:
        response = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}{path_suffix}",
            json=payload,
        )

    assert response.status_code == 200
    call = next(c for c in fake_extensions.calls if c["fn"] == expected_fn)
    for key, value in expected.items():
        assert call[key] == value
