from __future__ import annotations

from tests.agents.shared import hub_a2a_extensions_routes_support as support
from tests.agents.shared.hub_a2a_extensions_routes_support import (
    Any,
    Dict,
    _create_allowlisted_hub_agent,
    _FakeA2AService,
    _FakeGateway,
    admin_router,
    create_test_client,
    create_user,
    hub_router,
    pytest,
    settings,
)
from tests.support.a2a import build_session_query_extension_payload

pytestmark = support.pytestmark


@pytest.mark.asyncio
async def test_hub_card_validate_is_404_for_non_allowlisted_users(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    admin = await create_user(
        async_db_session, email="admin_validate_404@example.com", is_superuser=True
    )
    alice = await create_user(
        async_db_session, email="alice_validate_404@example.com", is_superuser=False
    )

    async with create_test_client(
        admin_router.router,
        async_session_maker=async_session_maker,
        current_user=admin,
        base_prefix=settings.api_v1_prefix,
    ) as admin_client:
        resp = await admin_client.post(
            f"{settings.api_v1_prefix}/admin/a2a/agents",
            json={
                "name": "Private Agent",
                "card_url": "https://example.com/.well-known/agent-card.json",
                "availability_policy": "allowlist",
                "auth_type": "bearer",
                "token": "secret-token-404",
                "enabled": True,
                "tags": [],
                "extra_headers": {},
            },
        )
        assert resp.status_code == 201
        agent_id = resp.json()["id"]

    async with create_test_client(
        hub_router.router,
        async_session_maker=async_session_maker,
        current_user=alice,
        base_prefix=settings.api_v1_prefix,
    ) as user_client:
        validate_resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/card:validate"
        )
        assert validate_resp.status_code == 404


@pytest.mark.asyncio
async def test_hub_card_validate_success_for_allowlisted_user(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    agent_id, user = await _create_allowlisted_hub_agent(
        async_session_maker=async_session_maker,
        async_db_session=async_db_session,
        admin_email="admin_validate_ok@example.com",
        user_email="alice_validate_ok@example.com",
        token="secret-token-validate",
    )

    fake_gateway = _FakeGateway()
    monkeypatch.setattr(
        hub_router, "get_a2a_service", lambda: _FakeA2AService(fake_gateway)
    )

    async with create_test_client(
        hub_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as user_client:
        resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/card:validate"
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["success"] is True
        assert payload["card_name"] == "Example Agent"

    assert len(fake_gateway.card_calls) == 1
    resolved = fake_gateway.card_calls[0]["resolved"]
    assert resolved.headers["Authorization"].endswith("secret-token-validate")


@pytest.mark.asyncio
async def test_hub_card_validate_closes_read_only_transaction_before_remote_fetch(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    agent_id, user = await _create_allowlisted_hub_agent(
        async_session_maker=async_session_maker,
        async_db_session=async_db_session,
        admin_email="admin_validate_close_tx@example.com",
        user_email="alice_validate_close_tx@example.com",
        token="secret-token-validate-close",
    )

    call_order: list[str] = []

    async def fake_load_for_external_call(_db, operation):
        call_order.append("prepare_external_call")
        return await operation(_db)

    class _OrderedGateway(_FakeGateway):
        async def fetch_agent_card_detail(self, **kwargs):
            call_order.append("fetch_card")
            return await super().fetch_agent_card_detail(**kwargs)

    monkeypatch.setattr(
        hub_router,
        "load_for_external_call",
        fake_load_for_external_call,
    )
    monkeypatch.setattr(
        hub_router, "get_a2a_service", lambda: _FakeA2AService(_OrderedGateway())
    )

    async with create_test_client(
        hub_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as user_client:
        resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/card:validate"
        )

    assert resp.status_code == 200
    assert call_order == ["prepare_external_call", "fetch_card"]


@pytest.mark.asyncio
async def test_hub_card_validate_logs_traceback_for_upstream_failure(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    agent_id, user = await _create_allowlisted_hub_agent(
        async_session_maker=async_session_maker,
        async_db_session=async_db_session,
        admin_email="admin_validate_log@example.com",
        user_email="alice_validate_log@example.com",
        token="secret-token-validate-log",
    )
    logged: list[Dict[str, Any]] = []

    async def _raise_unavailable(**_kwargs: Any) -> Any:
        raise hub_router.A2AAgentUnavailableError("hub upstream failed")

    def _capture(message: str, *args: Any, **kwargs: Any) -> None:
        logged.append({"message": message, **kwargs})

    monkeypatch.setattr(hub_router, "fetch_and_validate_agent_card", _raise_unavailable)
    monkeypatch.setattr(hub_router.logger, "exception", _capture)

    async with create_test_client(
        hub_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as user_client:
        resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/card:validate"
        )

    assert resp.status_code == 502
    assert resp.json()["detail"] == "hub upstream failed"
    assert len(logged) == 1
    assert logged[0]["message"] == "Shared A2A agent card validation failed"
    assert logged[0]["extra"]["user_id"] == str(user.id)
    assert logged[0]["extra"]["agent_id"] == str(agent_id)


@pytest.mark.asyncio
async def test_hub_card_validate_returns_warning_for_empty_skills(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    agent_id, user = await _create_allowlisted_hub_agent(
        async_session_maker=async_session_maker,
        async_db_session=async_db_session,
        admin_email="admin_validate_warn@example.com",
        user_email="alice_validate_warn@example.com",
        token="secret-token-validate-warn",
    )

    fake_gateway = _FakeGateway()
    fake_gateway.card_payload["skills"] = []
    monkeypatch.setattr(
        hub_router, "get_a2a_service", lambda: _FakeA2AService(fake_gateway)
    )

    async with create_test_client(
        hub_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as user_client:
        resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/card:validate"
        )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["success"] is True
    assert payload["message"] == "Agent card validated with warnings"
    assert payload["validation_warnings"] == [
        (
            "Field 'skills' array is empty. Agent must have at least one skill "
            "if it performs actions."
        )
    ]


@pytest.mark.asyncio
async def test_hub_card_validate_reports_shared_session_query_diagnostics(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    agent_id, user = await _create_allowlisted_hub_agent(
        async_session_maker=async_session_maker,
        async_db_session=async_db_session,
        admin_email="admin_validate_diag@example.com",
        user_email="alice_validate_diag@example.com",
        token="secret-token-validate-diag",
    )

    fake_gateway = _FakeGateway()
    fake_gateway.card_payload["capabilities"]["extensions"] = [
        build_session_query_extension_payload(
            uri="urn:shared-a2a:session-query:v1",
            result_envelope={"raw": True, "items": True, "pagination": True},
        )
    ]
    monkeypatch.setattr(
        hub_router, "get_a2a_service", lambda: _FakeA2AService(fake_gateway)
    )

    async with create_test_client(
        hub_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as user_client:
        resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/card:validate"
        )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["success"] is True
    assert payload["shared_session_query"]["declared"] is True
    assert payload["shared_session_query"]["status"] == "unsupported"
    assert "normalizedContractFamily" not in payload["shared_session_query"]
    assert (
        payload["shared_session_query"]["error"]
        == "Shared session query extension URI is not supported by Hub"
    )
    assert payload["validation_warnings"] == [
        "Shared session query extension URI is not supported by Hub"
    ]


@pytest.mark.asyncio
async def test_hub_card_validate_accepts_limit_and_optional_cursor_session_query(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    agent_id, user = await _create_allowlisted_hub_agent(
        async_session_maker=async_session_maker,
        async_db_session=async_db_session,
        admin_email="admin_validate_cursor@example.com",
        user_email="alice_validate_cursor@example.com",
        token="secret-token-validate-cursor",
    )

    fake_gateway = _FakeGateway()
    fake_gateway.card_payload["capabilities"]["extensions"] = [
        build_session_query_extension_payload(
            uri="urn:opencode-a2a:session-query/v1",
            methods={
                "list_sessions": "opencode.sessions.list",
                "get_session_messages": "opencode.sessions.messages.list",
            },
            pagination={
                "mode": "limit_and_optional_cursor",
                "default_limit": 20,
                "max_limit": 100,
                "params": ["limit", "before"],
                "cursor_param": "before",
                "result_cursor_field": "next_cursor",
                "cursor_applies_to": ["opencode.sessions.messages.list"],
            },
            result_envelope={"raw": True, "items": True, "pagination": True},
        )
    ]
    monkeypatch.setattr(
        hub_router, "get_a2a_service", lambda: _FakeA2AService(fake_gateway)
    )

    async with create_test_client(
        hub_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as user_client:
        resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/card:validate"
        )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["success"] is True
    assert payload["message"] == "Agent card validated"
    assert (
        payload["extensionCapabilities"]["sessionControl"]["command"]["declared"]
        is False
    )
    assert payload["shared_session_query"]["status"] == "supported"
    assert payload["shared_session_query"]["declaredContractVariant"] == "opencode"
    assert "normalizedContractFamily" not in payload["shared_session_query"]
    assert payload["shared_session_query"]["pagination_mode"] == (
        "limit_and_optional_cursor"
    )
    assert payload["shared_session_query"]["pagination_params"] == ["limit", "before"]


@pytest.mark.asyncio
async def test_hub_card_validate_exposes_request_execution_options_capabilities(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    agent_id, user = await _create_allowlisted_hub_agent(
        async_session_maker=async_session_maker,
        async_db_session=async_db_session,
        admin_email="admin_validate_exec_opts@example.com",
        user_email="alice_validate_exec_opts@example.com",
        token="secret-token-validate-exec-opts",
    )

    fake_gateway = _FakeGateway()
    fake_gateway.card_payload["capabilities"]["extensions"] = [
        build_session_query_extension_payload(
            uri="urn:opencode-a2a:session-query/v1",
            methods={
                "list_sessions": "opencode.sessions.list",
                "get_session_messages": "opencode.sessions.messages.list",
            },
            pagination={
                "mode": "limit",
                "default_limit": 20,
                "max_limit": 100,
            },
            result_envelope={"raw": True, "items": True, "pagination": True},
        )
    ]
    fake_gateway.card_payload["capabilities"]["extensions"][0]["params"][
        "request_execution_options"
    ] = {
        "metadata_field": "metadata.codex.execution",
        "fields": ["model", "effort"],
        "persists_for_thread": True,
        "notes": ["Execution overrides are provider-private."],
    }
    monkeypatch.setattr(
        hub_router, "get_a2a_service", lambda: _FakeA2AService(fake_gateway)
    )

    async with create_test_client(
        hub_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as user_client:
        resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/card:validate"
        )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["success"] is True
    assert payload["extensionCapabilities"]["requestExecutionOptions"] == {
        "declared": True,
        "consumedByHub": True,
        "status": "supported",
        "metadataField": "metadata.codex.execution",
        "fields": ["model", "effort"],
        "persistsForThread": True,
        "sourceExtensions": ["urn:opencode-a2a:session-query/v1"],
        "notes": ["Execution overrides are provider-private."],
    }


@pytest.mark.asyncio
async def test_hub_card_validate_reports_compatibility_profile_diagnostics(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    agent_id, user = await _create_allowlisted_hub_agent(
        async_session_maker=async_session_maker,
        async_db_session=async_db_session,
        admin_email="admin_validate_profile@example.com",
        user_email="alice_validate_profile@example.com",
        token="secret-token-validate-profile",
    )

    fake_gateway = _FakeGateway()
    fake_gateway.card_payload["capabilities"]["extensions"] = [
        {
            "uri": "urn:a2a:compatibility-profile/v1",
            "params": {
                "extension_retention": {
                    "urn:opencode-a2a:session-query/v1": {
                        "surface": "jsonrpc-extension",
                        "availability": "always",
                        "retention": "stable",
                    }
                },
                "method_retention": {
                    "opencode.sessions.shell": {
                        "surface": "extension",
                        "availability": "disabled",
                        "retention": "deployment-conditional",
                        "extension_uri": "urn:opencode-a2a:session-query/v1",
                        "toggle": "A2A_ENABLE_SESSION_SHELL",
                    }
                },
                "service_behaviors": {
                    "classification": "stable-service-semantics",
                    "methods": {"tasks/cancel": {"retention": "stable"}},
                },
                "consumer_guidance": [
                    "Treat opencode.sessions.shell as deployment-conditional."
                ],
            },
        }
    ]
    monkeypatch.setattr(
        hub_router, "get_a2a_service", lambda: _FakeA2AService(fake_gateway)
    )

    async with create_test_client(
        hub_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as user_client:
        resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/card:validate"
        )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["success"] is True
    assert payload["compatibility_profile"]["declared"] is True
    assert payload["compatibility_profile"]["status"] == "supported"
    assert payload["compatibility_profile"]["advisoryOnly"] is True
    assert payload["compatibility_profile"]["methodRetentionCount"] == 1
    assert payload["compatibility_profile"]["extensionRetentionCount"] == 1
    assert payload["compatibility_profile"]["serviceBehaviorKeys"] == [
        "classification",
        "methods",
    ]
