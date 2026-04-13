from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.models.a2a_agent import A2AAgent
from app.features.personal_agents import router as personal_router
from app.features.personal_agents.service import a2a_agent_service
from app.integrations.a2a_extensions import service as extensions_service_module
from app.integrations.a2a_extensions.errors import A2AExtensionNotSupportedError
from app.integrations.a2a_extensions.types import (
    ResolvedInvokeMetadataExtension,
    ResolvedInvokeMetadataField,
)
from tests.support.api_utils import create_test_client
from tests.support.utils import create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class _FakeCard:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def model_dump(self, **kwargs) -> dict[str, Any]:
        return dict(self._payload)


class _FakeGateway:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.invoke_response: dict[str, Any] = {"success": True, "content": "ok"}
        self.stream_events: list[dict[str, Any]] = [{"content": "ok"}]

    async def invoke(self, *, resolved, query: str, context_id=None, metadata=None):
        self.calls.append(
            {
                "resolved": resolved,
                "query": query,
                "context_id": context_id,
                "metadata": metadata,
            }
        )
        return dict(self.invoke_response)

    async def stream(
        self, *, session=None, resolved, query: str, context_id=None, metadata=None
    ):
        self.calls.append(
            {
                "session": session,
                "resolved": resolved,
                "query": query,
                "context_id": context_id,
                "metadata": metadata,
                "stream": True,
            }
        )

        class _MockMessage:
            def __init__(self, payload: dict[str, Any]) -> None:
                self._payload = payload

            def model_dump(self, **kwargs):
                return dict(self._payload)

        for event_payload in self.stream_events:
            yield _MockMessage(event_payload)

    async def fetch_agent_card_detail(
        self,
        *,
        resolved,  # noqa: ARG002
        raise_on_failure: bool,  # noqa: ARG002
        policy=None,  # noqa: ARG002
        card_fetch_timeout=None,  # noqa: ARG002
    ):
        self.calls.append({"card_fetch": True})
        return _FakeCard(
            {
                "name": "Example Agent",
                "description": "Example",
                "url": "https://example.com",
                "version": "1.0",
                "capabilities": {"extensions": []},
                "defaultInputModes": [],
                "defaultOutputModes": [],
                "skills": [{"id": "s1", "name": "s1", "description": "d", "tags": []}],
            }
        )


class _FakeA2AService:
    def __init__(self, gateway: _FakeGateway) -> None:
        self.gateway = gateway


class _FakeExtensionsService:
    def __init__(self, *, invoke_metadata_ext: Any | None = None) -> None:
        self.invoke_metadata_ext = invoke_metadata_ext

    async def resolve_invoke_metadata(self, *, runtime):  # noqa: ARG002
        if self.invoke_metadata_ext is None:
            raise A2AExtensionNotSupportedError(
                "invoke metadata extension not configured"
            )
        return self.invoke_metadata_ext


@pytest.mark.asyncio
async def test_personal_agent_http_invoke_works_with_dependency_injected_db(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])
    user = await create_user(async_db_session, email="personal-http@example.com")
    record = await a2a_agent_service.create_agent(
        async_db_session,
        user_id=user.id,
        name="Personal HTTP Agent",
        card_url="https://example.com/.well-known/agent-card.json",
        auth_type="none",
        enabled=True,
        tags=[],
        extra_headers={},
    )
    fake_gateway = _FakeGateway()
    monkeypatch.setattr(
        personal_router, "get_a2a_service", lambda: _FakeA2AService(fake_gateway)
    )

    async with create_test_client(
        personal_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as client:
        response = await client.post(
            f"{settings.api_v1_prefix}/me/a2a/agents/{record.id}/invoke",
            json={"query": "hello", "metadata": {}},
        )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert len(fake_gateway.calls) == 1


@pytest.mark.asyncio
async def test_personal_agent_card_validate_closes_read_only_transaction_before_remote_fetch(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])
    user = await create_user(async_db_session, email="personal-card-close@example.com")
    record = await a2a_agent_service.create_agent(
        async_db_session,
        user_id=user.id,
        name="Personal Card Agent",
        card_url="https://example.com/.well-known/agent-card.json",
        auth_type="none",
        enabled=True,
        tags=[],
        extra_headers={},
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
        personal_router,
        "load_for_external_call",
        fake_load_for_external_call,
    )
    monkeypatch.setattr(
        personal_router, "get_a2a_service", lambda: _FakeA2AService(_OrderedGateway())
    )

    async with create_test_client(
        personal_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as client:
        response = await client.post(
            f"{settings.api_v1_prefix}/me/a2a/agents/{record.id}/card:validate"
        )

    assert response.status_code == 200
    assert call_order == ["prepare_external_call", "fetch_card"]


@pytest.mark.asyncio
async def test_personal_agent_card_validate_logs_traceback_for_upstream_failure(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])
    user = await create_user(async_db_session, email="personal-card-log@example.com")
    record = await a2a_agent_service.create_agent(
        async_db_session,
        user_id=user.id,
        name="Personal Card Agent",
        card_url="https://example.com/.well-known/agent-card.json",
        auth_type="none",
        enabled=True,
        tags=[],
        extra_headers={},
    )
    logged: list[dict[str, Any]] = []

    async def _raise_unavailable(**_kwargs: Any) -> Any:
        raise personal_router.A2AAgentUnavailableError("upstream failed")

    def _capture(message: str, *args: Any, **kwargs: Any) -> None:
        logged.append({"message": message, **kwargs})

    monkeypatch.setattr(
        personal_router, "fetch_and_validate_agent_card", _raise_unavailable
    )
    monkeypatch.setattr(personal_router.logger, "exception", _capture)

    async with create_test_client(
        personal_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as client:
        response = await client.post(
            f"{settings.api_v1_prefix}/me/a2a/agents/{record.id}/card:validate"
        )

    assert response.status_code == 502
    assert response.json()["detail"] == "upstream failed"
    assert len(logged) == 1
    assert logged[0]["message"] == "Personal A2A agent card validation failed"
    assert logged[0]["extra"]["user_id"] == str(user.id)
    assert logged[0]["extra"]["agent_id"] == str(record.id)


@pytest.mark.asyncio
async def test_personal_agent_http_invoke_injects_session_bound_invoke_metadata(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])
    user = await create_user(
        async_db_session, email="personal-http-invoke-metadata@example.com"
    )
    record = await a2a_agent_service.create_agent(
        async_db_session,
        user_id=user.id,
        name="Personal HTTP Agent",
        card_url="https://example.com/.well-known/agent-card.json",
        auth_type="none",
        enabled=True,
        tags=[],
        extra_headers={},
    )
    fake_gateway = _FakeGateway()
    monkeypatch.setattr(
        personal_router, "get_a2a_service", lambda: _FakeA2AService(fake_gateway)
    )
    monkeypatch.setattr(
        extensions_service_module,
        "get_a2a_extensions_service",
        lambda: _FakeExtensionsService(
            invoke_metadata_ext=ResolvedInvokeMetadataExtension(
                uri="urn:a2a:invoke-metadata/v1",
                required=False,
                provider="commonground",
                metadata_field="metadata.shared.invoke",
                behavior="merge_bound_metadata_into_invoke",
                applies_to_methods=("message/send", "message/stream"),
                fields=(
                    ResolvedInvokeMetadataField(name="project_id", required=True),
                    ResolvedInvokeMetadataField(name="channel_id", required=True),
                ),
                supported_metadata=(
                    "shared.invoke.bindings.project_id",
                    "shared.invoke.bindings.channel_id",
                ),
            )
        ),
    )

    async with create_test_client(
        personal_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as client:
        response = await client.post(
            f"{settings.api_v1_prefix}/me/a2a/agents/{record.id}/invoke",
            json={
                "query": "hello",
                "metadata": {
                    "shared": {
                        "invoke": {
                            "bindings": {
                                "project_id": "proj-1",
                                "channel_id": "chan-1",
                            }
                        }
                    }
                },
            },
        )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert fake_gateway.calls[0]["metadata"] == {
        "project_id": "proj-1",
        "channel_id": "chan-1",
    }


@pytest.mark.asyncio
async def test_personal_agent_http_invoke_returns_preflight_binding_error_when_declared_fields_missing(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])
    user = await create_user(
        async_db_session, email="personal-http-metadata-preflight@example.com"
    )
    record = await a2a_agent_service.create_agent(
        async_db_session,
        user_id=user.id,
        name="Personal HTTP Agent",
        card_url="https://example.com/.well-known/agent-card.json",
        auth_type="none",
        enabled=True,
        tags=[],
        extra_headers={},
    )
    fake_gateway = _FakeGateway()
    monkeypatch.setattr(
        personal_router, "get_a2a_service", lambda: _FakeA2AService(fake_gateway)
    )
    monkeypatch.setattr(
        extensions_service_module,
        "get_a2a_extensions_service",
        lambda: _FakeExtensionsService(
            invoke_metadata_ext=ResolvedInvokeMetadataExtension(
                uri="urn:a2a:invoke-metadata/v1",
                required=False,
                provider="commonground",
                metadata_field="metadata.shared.invoke",
                behavior="merge_bound_metadata_into_invoke",
                applies_to_methods=("message/send", "message/stream"),
                fields=(
                    ResolvedInvokeMetadataField(name="project_id", required=True),
                    ResolvedInvokeMetadataField(name="channel_id", required=True),
                ),
                supported_metadata=(
                    "shared.invoke.bindings.project_id",
                    "shared.invoke.bindings.channel_id",
                ),
            )
        ),
    )

    async with create_test_client(
        personal_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as client:
        response = await client.post(
            f"{settings.api_v1_prefix}/me/a2a/agents/{record.id}/invoke",
            json={
                "query": "hello",
                "metadata": {
                    "shared": {"invoke": {"bindings": {"project_id": "proj-1"}}}
                },
            },
        )

    assert response.status_code == 400
    assert response.json()["detail"]["error_code"] == "invoke_metadata_not_bound"
    assert response.json()["detail"]["missing_params"] == [
        {"name": "channel_id", "required": True}
    ]
    assert fake_gateway.calls == []


@pytest.mark.asyncio
async def test_personal_agent_http_invoke_rejects_client_owned_context_id(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])
    user = await create_user(async_db_session, email="personal-invalid@example.com")
    record = await a2a_agent_service.create_agent(
        async_db_session,
        user_id=user.id,
        name="Personal HTTP Agent",
        card_url="https://example.com/.well-known/agent-card.json",
        auth_type="none",
        enabled=True,
        tags=[],
        extra_headers={},
    )

    async with create_test_client(
        personal_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as client:
        response = await client.post(
            f"{settings.api_v1_prefix}/me/a2a/agents/{record.id}/invoke",
            json={
                "query": "hello",
                "conversationId": str(uuid4()),
                "contextId": "ctx-client",
                "metadata": {},
            },
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_personal_agent_sse_invoke_streams_with_dependency_injected_db(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])
    user = await create_user(async_db_session, email="personal-sse@example.com")
    record = await a2a_agent_service.create_agent(
        async_db_session,
        user_id=user.id,
        name="Personal Stream Agent",
        card_url="https://example.com/.well-known/agent-card.json",
        auth_type="none",
        enabled=True,
        tags=[],
        extra_headers={},
    )
    fake_gateway = _FakeGateway()
    fake_gateway.stream_events = [
        {
            "content": "ok",
            "contextId": f"ctx-{uuid4()}",
            "metadata": {"provider": "opencode", "externalSessionId": f"ext-{uuid4()}"},
        }
    ]
    monkeypatch.setattr(
        personal_router, "get_a2a_service", lambda: _FakeA2AService(fake_gateway)
    )
    monkeypatch.setattr(personal_router, "validate_message", lambda payload: [])

    async with create_test_client(
        personal_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as client:
        async with client.stream(
            "POST",
            f"{settings.api_v1_prefix}/me/a2a/agents/{record.id}/invoke",
            params={"stream": "true"},
            json={
                "query": "hello",
                "conversationId": str(uuid4()),
                "metadata": {},
            },
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            body = (await response.aread()).decode("utf-8")
            assert "data:" in body
            assert "event: stream_end" in body

    assert len(fake_gateway.calls) == 1
    assert fake_gateway.calls[0]["stream"] is True


@pytest.mark.asyncio
async def test_personal_agents_list_supports_health_bucket_and_counts(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])
    user = await create_user(async_db_session, email="personal-health-list@example.com")

    for index in range(4):
        await a2a_agent_service.create_agent(
            async_db_session,
            user_id=user.id,
            name=f"Personal Agent {index + 1}",
            card_url=f"https://example.com/agent-{index + 1}/.well-known/agent-card.json",
            auth_type="none",
            enabled=True,
            tags=[],
            extra_headers={},
        )

    records = (
        await async_db_session.execute(
            select(A2AAgent)
            .where(
                A2AAgent.user_id == user.id,
                A2AAgent.agent_scope == A2AAgent.SCOPE_PERSONAL,
            )
            .order_by(A2AAgent.created_at.asc(), A2AAgent.id.asc())
        )
    ).scalars()
    agents = list(records)
    assert len(agents) == 4

    agents[0].health_status = A2AAgent.HEALTH_HEALTHY
    agents[1].health_status = A2AAgent.HEALTH_DEGRADED
    agents[2].health_status = A2AAgent.HEALTH_UNAVAILABLE
    agents[3].health_status = A2AAgent.HEALTH_UNKNOWN
    await async_db_session.commit()

    async with create_test_client(
        personal_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as client:
        healthy_response = await client.get(
            f"{settings.api_v1_prefix}/me/a2a/agents",
            params={"page": 1, "size": 10, "health_bucket": "healthy"},
        )
        assert healthy_response.status_code == 200
        healthy_payload = healthy_response.json()
        assert [item["health_status"] for item in healthy_payload["items"]] == [
            "healthy"
        ]
        assert healthy_payload["meta"]["counts"] == {
            "healthy": 1,
            "degraded": 1,
            "unavailable": 1,
            "unknown": 1,
        }

        degraded_response = await client.get(
            f"{settings.api_v1_prefix}/me/a2a/agents",
            params={"page": 1, "size": 10, "health_bucket": "degraded"},
        )
        assert degraded_response.status_code == 200
        degraded_payload = degraded_response.json()
        assert [item["health_status"] for item in degraded_payload["items"]] == [
            "degraded"
        ]

        unavailable_response = await client.get(
            f"{settings.api_v1_prefix}/me/a2a/agents",
            params={"page": 1, "size": 10, "health_bucket": "unavailable"},
        )
        assert unavailable_response.status_code == 200
        unavailable_payload = unavailable_response.json()
        assert [item["health_status"] for item in unavailable_payload["items"]] == [
            "unavailable"
        ]

        unknown_response = await client.get(
            f"{settings.api_v1_prefix}/me/a2a/agents",
            params={"page": 1, "size": 10, "health_bucket": "unknown"},
        )
        assert unknown_response.status_code == 200
        unknown_payload = unknown_response.json()
        assert [item["health_status"] for item in unknown_payload["items"]] == [
            "unknown"
        ]

        attention_response = await client.get(
            f"{settings.api_v1_prefix}/me/a2a/agents",
            params={"page": 1, "size": 10, "health_bucket": "attention"},
        )
        assert attention_response.status_code == 200
        attention_payload = attention_response.json()
        assert {item["health_status"] for item in attention_payload["items"]} == {
            "degraded",
            "unavailable",
            "unknown",
        }


@pytest.mark.asyncio
async def test_personal_agents_health_check_routes_return_summary_and_items(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])
    user = await create_user(
        async_db_session, email="personal-health-check@example.com"
    )

    record = await a2a_agent_service.create_agent(
        async_db_session,
        user_id=user.id,
        name="Personal Health Agent",
        card_url="https://example.com/.well-known/agent-card.json",
        auth_type="none",
        enabled=True,
        tags=[],
        extra_headers={},
    )

    captured_calls: list[dict[str, Any]] = []

    async def _fake_check_agents_health(
        *,
        user_id,
        force: bool = False,
        agent_id=None,
    ):
        captured_calls.append(
            {
                "user_id": user_id,
                "force": force,
                "agent_id": agent_id,
            }
        )
        checked_at = datetime(2026, 3, 25, 12, 0, tzinfo=UTC)
        summary = SimpleNamespace(
            requested=1,
            checked=1,
            skipped_cooldown=0,
            healthy=1,
            degraded=0,
            unavailable=0,
            unknown=0,
        )
        items = [
            SimpleNamespace(
                agent_id=record.id,
                health_status="healthy",
                checked_at=checked_at,
                skipped_cooldown=False,
                error=None,
                reason_code=None,
            )
        ]
        return summary, items

    monkeypatch.setattr(
        a2a_agent_service, "check_agents_health", _fake_check_agents_health
    )

    async with create_test_client(
        personal_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as client:
        batch_response = await client.post(
            f"{settings.api_v1_prefix}/me/a2a/agents/check-health",
            params={"force": "false"},
        )
        assert batch_response.status_code == 200
        assert batch_response.json()["summary"] == {
            "requested": 1,
            "checked": 1,
            "skipped_cooldown": 0,
            "healthy": 1,
            "degraded": 0,
            "unavailable": 0,
            "unknown": 0,
        }

        single_response = await client.post(
            f"{settings.api_v1_prefix}/me/a2a/agents/{record.id}/check-health",
            params={"force": "true"},
        )
        assert single_response.status_code == 200
        single_payload = single_response.json()
        assert len(single_payload["items"]) == 1
        assert single_payload["items"][0]["agent_id"] == str(record.id)
        assert single_payload["items"][0]["health_status"] == "healthy"
        assert single_payload["items"][0]["reason_code"] is None

    assert captured_calls == [
        {
            "user_id": user.id,
            "force": False,
            "agent_id": None,
        },
        {
            "user_id": user.id,
            "force": True,
            "agent_id": record.id,
        },
    ]
