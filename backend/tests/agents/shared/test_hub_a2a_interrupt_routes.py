from __future__ import annotations

from tests.agents.shared import hub_a2a_extensions_routes_support as support
from tests.agents.shared.hub_a2a_extensions_routes_support import (
    A2AExtensionContractError,
    A2AExtensionNotSupportedError,
    _create_allowlisted_hub_agent,
    _FakeElicitationReplyErrorService,
    _FakeExtensionsErrorService,
    _FakeExtensionsExceptionService,
    _FakeExtensionsService,
    _FakePermissionReplyErrorService,
    _FakePermissionsReplyErrorService,
    create_test_client,
    extension_router_common,
    hub_extension_router,
    pytest,
    settings,
)

pytestmark = support.pytestmark


@pytest.mark.asyncio
async def test_hub_interrupt_reply_rejects_legacy_payload_fields(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    agent_id, user = await _create_allowlisted_hub_agent(
        async_session_maker=async_session_maker,
        async_db_session=async_db_session,
        admin_email="admin_interrupt_legacy@example.com",
        user_email="alice_interrupt_legacy@example.com",
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
        resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/interrupts/permission:reply",
            json={"requestID": "perm-1", "decision": "allow"},
        )
        assert resp.status_code == 422

    assert fake_extensions.calls == []


@pytest.mark.asyncio
async def test_hub_interrupt_reply_rejects_invalid_elicitation_content_for_decline(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    agent_id, user = await _create_allowlisted_hub_agent(
        async_session_maker=async_session_maker,
        async_db_session=async_db_session,
        admin_email="admin_interrupt_elicitation_invalid@example.com",
        user_email="alice_interrupt_elicitation_invalid@example.com",
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
        resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/interrupts/elicitation:reply",
            json={
                "request_id": "eli-1",
                "action": "decline",
                "content": {"approved": False},
            },
        )
        assert resp.status_code == 422

    assert fake_extensions.calls == []


@pytest.mark.parametrize("reply", ["once", "reject", "always"])
@pytest.mark.asyncio
async def test_hub_opencode_permission_reply_accepts_supported_reply_values(
    async_session_maker,
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
    reply: str,
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    agent_id, user = await _create_allowlisted_hub_agent(
        async_session_maker=async_session_maker,
        async_db_session=async_db_session,
        admin_email="admin_permission_reply_values@example.com",
        user_email="alice_permission_reply_values@example.com",
        token="secret-token-opencode-permission-values",
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
        resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/interrupts/permission:reply",
            json={
                "request_id": "perm-reply-values",
                "reply": reply,
            },
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["success"] is True
        assert payload["result"] == {"ok": True, "request_id": "perm-reply-values"}

    permission_calls = [
        call
        for call in fake_extensions.calls
        if call["fn"] == "reply_permission_interrupt"
    ]
    assert len(permission_calls) == 1
    assert permission_calls[0]["reply"] == reply


@pytest.mark.parametrize(
    ("error_code", "message", "expected_status"),
    [
        ("session_not_found", "Session not found", 404),
        ("session_forbidden", "Session access denied", 403),
        ("method_disabled", "Method disabled", 403),
        ("invalid_params", "Invalid params", 400),
        ("interrupt_request_not_found", "Interrupt request not found", 404),
        ("interrupt_request_expired", "Interrupt request expired", 409),
        ("interrupt_type_mismatch", "Interrupt type mismatch", 409),
    ],
)
@pytest.mark.asyncio
async def test_hub_opencode_session_continue_maps_extension_error_to_http_status(
    async_session_maker,
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
    error_code: str,
    message: str,
    expected_status: int,
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    agent_id, user = await _create_allowlisted_hub_agent(
        async_session_maker=async_session_maker,
        async_db_session=async_db_session,
        admin_email="admin_extension_status_map@example.com",
        user_email="alice_extension_status_map@example.com",
        token="secret-token-opencode-status",
    )

    fake_extensions = _FakeExtensionsErrorService(
        error_code=error_code,
        message=message,
    )
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
        resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/sessions/sess-404:continue"
        )
        assert resp.status_code == expected_status
        payload = resp.json()
        detail = payload["detail"]
        assert detail["error_code"] == error_code
        assert detail["upstream_error"] == {"message": message}


@pytest.mark.asyncio
async def test_hub_opencode_session_continue_preserves_structured_error_details(
    async_session_maker,
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    agent_id, user = await _create_allowlisted_hub_agent(
        async_session_maker=async_session_maker,
        async_db_session=async_db_session,
        admin_email="admin_extension_structured_error@example.com",
        user_email="alice_extension_structured_error@example.com",
        token="secret-token-opencode-structured-error",
    )

    fake_extensions = _FakeExtensionsErrorService(
        error_code="invalid_params",
        message="project_id required",
        source="upstream_a2a",
        jsonrpc_code=-32602,
        missing_params=[{"name": "project_id", "required": True}],
    )
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
        resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/sessions/sess-structured:continue"
        )

    assert resp.status_code == 400
    payload = resp.json()
    detail = payload["detail"]
    assert detail["error_code"] == "invalid_params"
    assert detail["source"] == "upstream_a2a"
    assert detail["jsonrpc_code"] == -32602
    assert detail["missing_params"] == [{"name": "project_id", "required": True}]
    assert detail["upstream_error"] == {"message": "project_id required"}


@pytest.mark.parametrize(
    ("error_code", "message", "expected_status"),
    [
        ("interrupt_request_not_found", "Interrupt request not found", 404),
        ("interrupt_request_expired", "Interrupt request expired", 409),
        ("interrupt_type_mismatch", "Interrupt type mismatch", 409),
        ("invalid_params", "Invalid params", 400),
    ],
)
@pytest.mark.parametrize("reply", ["once", "reject", "always"])
@pytest.mark.asyncio
async def test_hub_opencode_permission_reply_maps_extension_error_to_http_status(
    async_session_maker,
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
    error_code: str,
    message: str,
    expected_status: int,
    reply: str,
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    agent_id, user = await _create_allowlisted_hub_agent(
        async_session_maker=async_session_maker,
        async_db_session=async_db_session,
        admin_email="admin_permission_status_map@example.com",
        user_email="alice_permission_status_map@example.com",
        token="secret-token-opencode-status-permission",
    )

    fake_extensions = _FakePermissionReplyErrorService(
        error_code=error_code,
        message=message,
    )
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
        resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/interrupts/permission:reply",
            json={
                "request_id": "perm-404",
                "reply": reply,
            },
        )
        assert resp.status_code == expected_status
        payload = resp.json()
        detail = payload["detail"]
        assert detail["error_code"] == error_code
        assert detail["upstream_error"] == {"message": message}
    assert len(fake_extensions.calls) == 1
    assert fake_extensions.calls[0]["reply"] == reply


@pytest.mark.parametrize(
    ("error_code", "message", "expected_status"),
    [
        ("interrupt_request_not_found", "Interrupt request not found", 404),
        ("interrupt_request_expired", "Interrupt request expired", 409),
        ("interrupt_type_mismatch", "Interrupt type mismatch", 409),
        ("invalid_params", "Invalid params", 400),
    ],
)
@pytest.mark.asyncio
async def test_hub_opencode_permissions_reply_maps_extension_error_to_http_status(
    async_session_maker,
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
    error_code: str,
    message: str,
    expected_status: int,
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    agent_id, user = await _create_allowlisted_hub_agent(
        async_session_maker=async_session_maker,
        async_db_session=async_db_session,
        admin_email="admin_permissions_status_map@example.com",
        user_email="alice_permissions_status_map@example.com",
        token="secret-token-opencode-status-permissions",
    )

    fake_extensions = _FakePermissionsReplyErrorService(
        error_code=error_code,
        message=message,
    )
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
        resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/interrupts/permissions:reply",
            json={
                "request_id": "perm-v2-404",
                "permissions": {"fileSystem": {"write": ["/workspace/project"]}},
                "scope": "session",
            },
        )
        assert resp.status_code == expected_status
        payload = resp.json()
        detail = payload["detail"]
        assert detail["error_code"] == error_code
        assert detail["upstream_error"] == {"message": message}
    assert len(fake_extensions.calls) == 1
    assert fake_extensions.calls[0]["scope"] == "session"


@pytest.mark.parametrize(
    ("error_code", "message", "expected_status"),
    [
        ("interrupt_request_not_found", "Interrupt request not found", 404),
        ("interrupt_request_expired", "Interrupt request expired", 409),
        ("interrupt_type_mismatch", "Interrupt type mismatch", 409),
        ("invalid_params", "Invalid params", 400),
    ],
)
@pytest.mark.asyncio
async def test_hub_opencode_elicitation_reply_maps_extension_error_to_http_status(
    async_session_maker,
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
    error_code: str,
    message: str,
    expected_status: int,
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    agent_id, user = await _create_allowlisted_hub_agent(
        async_session_maker=async_session_maker,
        async_db_session=async_db_session,
        admin_email="admin_elicitation_status_map@example.com",
        user_email="alice_elicitation_status_map@example.com",
        token="secret-token-opencode-status-elicitation",
    )

    fake_extensions = _FakeElicitationReplyErrorService(
        error_code=error_code,
        message=message,
    )
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
        resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/interrupts/elicitation:reply",
            json={
                "request_id": "eli-404",
                "action": "accept",
                "content": {"approved": True},
            },
        )
        assert resp.status_code == expected_status
        payload = resp.json()
        detail = payload["detail"]
        assert detail["error_code"] == error_code
        assert detail["upstream_error"] == {"message": message}
    assert len(fake_extensions.calls) == 1
    assert fake_extensions.calls[0]["action"] == "accept"


@pytest.mark.parametrize(
    ("exception", "error_code"),
    [
        (
            A2AExtensionContractError("extension contract is invalid"),
            "extension_contract_error",
        ),
        (
            A2AExtensionNotSupportedError("extension method is not supported"),
            "not_supported",
        ),
    ],
)
@pytest.mark.asyncio
async def test_hub_opencode_session_continue_contract_or_support_errors_use_4xx(
    async_session_maker,
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
    exception: Exception,
    error_code: str,
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    agent_id, user = await _create_allowlisted_hub_agent(
        async_session_maker=async_session_maker,
        async_db_session=async_db_session,
        admin_email="admin_extension_exc_map@example.com",
        user_email="alice_extension_exc_map@example.com",
        token="secret-token-opencode-exc",
    )

    fake_extensions = _FakeExtensionsExceptionService(exception)
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
        resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/sessions/sess-500:continue"
        )
        assert resp.status_code == 400
        payload = resp.json()
        detail = payload["detail"]
        assert detail["error_code"] == error_code
