from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Dict, Optional

import pytest

from app.core.config import settings
from app.features.extension_capabilities import common_router as extension_router_common
from app.features.extension_capabilities import hub_router as hub_extension_router
from app.features.hub_agents import admin_router
from app.features.hub_agents import router as hub_router
from app.integrations.a2a_extensions.errors import (
    A2AExtensionContractError,
    A2AExtensionNotSupportedError,
)
from app.integrations.a2a_runtime_status_contract import (
    runtime_status_contract_payload,
)
from tests.support.api_utils import create_test_client
from tests.support.utils import create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _valid_card_payload() -> Dict[str, Any]:
    return {
        "name": "Example Agent",
        "description": "Example",
        "url": "https://example.com",
        "version": "1.0",
        "capabilities": {"extensions": []},
        "defaultInputModes": [],
        "defaultOutputModes": [],
        "skills": [{"id": "s1", "name": "s1", "description": "d", "tags": []}],
    }


class _FakeCard:
    def __init__(self, payload: Dict[str, Any]) -> None:
        self._payload = payload

    def model_dump(self, **kwargs) -> Dict[str, Any]:
        return dict(self._payload)


class _FakeGateway:
    def __init__(self) -> None:
        self.card_calls: list[Dict[str, Any]] = []
        self.card_payload = _valid_card_payload()

    async def fetch_agent_card_detail(
        self,
        *,
        resolved,
        raise_on_failure: bool,
        policy=None,
        card_fetch_timeout=None,
    ):
        self.card_calls.append(
            {
                "resolved": resolved,
                "raise_on_failure": raise_on_failure,
                "policy": policy,
                "card_fetch_timeout": card_fetch_timeout,
            }
        )
        return _FakeCard(self.card_payload)


class _FakeA2AService:
    def __init__(self, gateway: _FakeGateway) -> None:
        self.gateway = gateway


@dataclass(slots=True)
class _FakeExtensionResult:
    success: bool
    result: Optional[Dict[str, Any]] = None
    error_code: Optional[str] = None
    source: Optional[str] = None
    jsonrpc_code: Optional[int] = None
    missing_params: Optional[list[Dict[str, Any]]] = None
    upstream_error: Optional[Dict[str, Any]] = None
    meta: Optional[Dict[str, Any]] = None


class _FakeExtensionsService:
    def __init__(self) -> None:
        self.calls: list[Dict[str, Any]] = []
        self.capability_snapshot: Any = SimpleNamespace(
            model_selection=SimpleNamespace(status="unsupported"),
            provider_discovery=SimpleNamespace(status="unsupported"),
            session_query=SimpleNamespace(status="unsupported", capability=None),
        )

    async def resolve_capability_snapshot(self, *, runtime):
        self.calls.append(
            {
                "fn": "resolve_capability_snapshot",
                "runtime": runtime,
            }
        )
        return self.capability_snapshot

    async def continue_session(self, *, runtime, session_id: str):
        self.calls.append(
            {
                "fn": "continue_session",
                "runtime": runtime,
                "session_id": session_id,
            }
        )
        return _FakeExtensionResult(
            success=True,
            result={
                "contextId": session_id,
                "provider": "opencode",
                "metadata": {
                    "provider": "opencode",
                    "externalSessionId": session_id,
                    "contextId": session_id,
                },
            },
            meta={},
        )

    async def list_sessions(
        self, *, runtime, page: int, size, query, include_raw=False
    ):
        raw_items = [{"id": "sess-1", "title": "One", "provider": "opencode"}]
        self.calls.append(
            {
                "fn": "list_sessions",
                "runtime": runtime,
                "page": page,
                "size": size,
                "include_raw": include_raw,
                "query": query,
            }
        )
        result = {
            "items": [{"id": "sess-1", "title": "One"}],
            "pagination": {
                "page": page,
                "size": size or 20,
                "total": 1,
                "pages": 1,
            },
        }
        if include_raw:
            result["raw"] = raw_items
        return _FakeExtensionResult(
            success=True,
            result=result,
            meta={},
        )

    async def get_session_messages(
        self,
        *,
        runtime,
        session_id: str,
        page: int,
        size,
        query,
        include_raw=False,
    ):
        raw_items = [
            {
                "id": "msg-1",
                "role": "assistant",
                "text": "hello",
                "timestamp": "2026-02-09T00:00:00Z",
                "provider": "opencode",
            }
        ]
        self.calls.append(
            {
                "fn": "get_session_messages",
                "runtime": runtime,
                "session_id": session_id,
                "page": page,
                "size": size,
                "include_raw": include_raw,
                "query": query,
            }
        )
        result = {
            "items": [
                {
                    "id": "msg-1",
                    "role": "assistant",
                    "text": "hello",
                    "timestamp": "2026-02-09T00:00:00Z",
                }
            ],
            "pagination": {
                "page": page,
                "size": size or 50,
                "total": 1,
                "pages": 1,
            },
        }
        if include_raw:
            result["raw"] = raw_items
        return _FakeExtensionResult(
            success=True,
            result=result,
            meta={},
        )

    async def reply_permission_interrupt(
        self,
        *,
        runtime,
        request_id: str,
        reply: str,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.calls.append(
            {
                "fn": "reply_permission_interrupt",
                "runtime": runtime,
                "request_id": request_id,
                "reply": reply,
                "metadata": metadata,
            }
        )
        return _FakeExtensionResult(
            success=True,
            result={"ok": True, "request_id": request_id},
            meta={},
        )

    async def prompt_session_async(
        self,
        *,
        runtime,
        session_id: str,
        request_payload,
        metadata,
    ):
        self.calls.append(
            {
                "fn": "prompt_session_async",
                "runtime": runtime,
                "session_id": session_id,
                "request_payload": request_payload,
                "metadata": metadata,
            }
        )
        return _FakeExtensionResult(
            success=True,
            result={"ok": True, "session_id": session_id},
            meta={},
        )

    async def reply_question_interrupt(
        self,
        *,
        runtime,
        request_id: str,
        answers,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.calls.append(
            {
                "fn": "reply_question_interrupt",
                "runtime": runtime,
                "request_id": request_id,
                "answers": answers,
                "metadata": metadata,
            }
        )
        return _FakeExtensionResult(
            success=True,
            result={"ok": True, "request_id": request_id},
            meta={},
        )

    async def list_model_providers(
        self,
        *,
        runtime,
        session_metadata: Optional[Dict[str, Any]] = None,
    ):
        self.calls.append(
            {
                "fn": "list_model_providers",
                "runtime": runtime,
                "session_metadata": session_metadata,
            }
        )
        return _FakeExtensionResult(
            success=True,
            result={
                "items": [
                    {
                        "provider_id": "openai",
                        "name": "OpenAI",
                        "connected": True,
                        "default_model_id": "gpt-5",
                        "model_count": 2,
                    }
                ],
                "default_by_provider": {"openai": "gpt-5"},
                "connected": ["openai"],
            },
            meta={"extension_uri": "urn:opencode-a2a:provider-discovery/v1"},
        )

    async def list_models(
        self,
        *,
        runtime,
        provider_id: str | None = None,
        session_metadata: Optional[Dict[str, Any]] = None,
    ):
        self.calls.append(
            {
                "fn": "list_models",
                "runtime": runtime,
                "provider_id": provider_id,
                "session_metadata": session_metadata,
            }
        )
        return _FakeExtensionResult(
            success=True,
            result={
                "items": [
                    {
                        "provider_id": provider_id or "openai",
                        "model_id": "gpt-5",
                        "name": "GPT-5",
                        "connected": True,
                        "default": True,
                    }
                ],
                "default_by_provider": {provider_id or "openai": "gpt-5"},
                "connected": [provider_id or "openai"],
            },
            meta={"extension_uri": "urn:opencode-a2a:provider-discovery/v1"},
        )

    async def reject_question_interrupt(
        self,
        *,
        runtime,
        request_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.calls.append(
            {
                "fn": "reject_question_interrupt",
                "runtime": runtime,
                "request_id": request_id,
                "metadata": metadata,
            }
        )
        return _FakeExtensionResult(
            success=True,
            result={"ok": True, "request_id": request_id},
            meta={},
        )


class _FakeExtensionsErrorService:
    def __init__(
        self,
        *,
        error_code: str,
        message: str,
        source: str | None = None,
        jsonrpc_code: int | None = None,
        missing_params: list[Dict[str, Any]] | None = None,
    ) -> None:
        self.calls: list[Dict[str, Any]] = []
        self.error_code = error_code
        self.message = message
        self.source = source
        self.jsonrpc_code = jsonrpc_code
        self.missing_params = missing_params

    async def continue_session(self, *, runtime, session_id: str):
        self.calls.append(
            {
                "fn": "continue_session",
                "runtime": runtime,
                "session_id": session_id,
            }
        )
        return _FakeExtensionResult(
            success=False,
            error_code=self.error_code,
            source=self.source,
            jsonrpc_code=self.jsonrpc_code,
            missing_params=self.missing_params,
            upstream_error={"message": self.message},
            meta={},
        )


class _FakePermissionReplyErrorService:
    def __init__(self, *, error_code: str, message: str) -> None:
        self.calls: list[Dict[str, Any]] = []
        self.error_code = error_code
        self.message = message

    async def reply_permission_interrupt(
        self,
        *,
        runtime,
        request_id: str,
        reply: str,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.calls.append(
            {
                "fn": "reply_permission_interrupt",
                "runtime": runtime,
                "request_id": request_id,
                "reply": reply,
                "metadata": metadata,
            }
        )
        return _FakeExtensionResult(
            success=False,
            error_code=self.error_code,
            upstream_error={"message": self.message},
            meta={},
        )


class _FakeExtensionsExceptionService:
    def __init__(self, error: Exception) -> None:
        self.calls: list[Dict[str, Any]] = []
        self.error = error

    async def continue_session(self, *, runtime, session_id: str):
        self.calls.append(
            {
                "fn": "continue_session",
                "runtime": runtime,
                "session_id": session_id,
            }
        )
        raise self.error

    async def reply_question_interrupt(
        self, *, runtime, request_id: str, answers, metadata=None
    ):
        self.calls.append(
            {
                "fn": "reply_question_interrupt",
                "runtime": runtime,
                "request_id": request_id,
                "answers": answers,
                "metadata": metadata,
            }
        )
        return _FakeExtensionResult(
            success=True,
            result={"ok": True, "request_id": request_id},
            meta={},
        )

    async def reject_question_interrupt(
        self, *, runtime, request_id: str, metadata=None
    ):
        self.calls.append(
            {
                "fn": "reject_question_interrupt",
                "runtime": runtime,
                "request_id": request_id,
                "metadata": metadata,
            }
        )
        return _FakeExtensionResult(
            success=True,
            result={"ok": True, "request_id": request_id},
            meta={},
        )


async def _create_allowlisted_hub_agent(
    *,
    async_session_maker,
    async_db_session,
    admin_email: str,
    user_email: str,
    token: str,
) -> tuple[str, Any]:
    admin = await create_user(async_db_session, email=admin_email, is_superuser=True)
    user = await create_user(async_db_session, email=user_email, is_superuser=False)

    async with create_test_client(
        admin_router.router,
        async_session_maker=async_session_maker,
        current_user=admin,
        base_prefix=settings.api_v1_prefix,
    ) as admin_client:
        create_payload = {
            "name": "Private Agent",
            "card_url": "https://example.com/.well-known/agent-card.json",
            "availability_policy": "allowlist",
            "auth_type": "bearer",
            "token": token,
            "enabled": True,
            "tags": ["opencode"],
            "extra_headers": {},
        }
        resp = await admin_client.post(
            f"{settings.api_v1_prefix}/admin/a2a/agents", json=create_payload
        )
        assert resp.status_code == 201
        agent_id = resp.json()["id"]

        allow_resp = await admin_client.post(
            f"{settings.api_v1_prefix}/admin/a2a/agents/{agent_id}/allowlist",
            json={"email": user.email},
        )
        assert allow_resp.status_code == 201

    return agent_id, user


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
        {
            "uri": "urn:shared-a2a:session-query:v1",
            "params": {
                "provider": "opencode",
                "methods": {
                    "list_sessions": "shared.sessions.list",
                    "get_session_messages": "shared.sessions.messages.list",
                },
                "pagination": {
                    "mode": "page_size",
                    "default_size": 20,
                    "max_size": 100,
                },
                "result_envelope": {"raw": True, "items": True, "pagination": True},
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
    assert payload["shared_session_query"]["declared"] is True
    assert payload["shared_session_query"]["status"] == "legacy"
    assert payload["shared_session_query"]["uses_legacy_uri"] is True


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

    assert len(fake_extensions.calls) == 7
    prompt_calls = [
        c for c in fake_extensions.calls if c["fn"] == "prompt_session_async"
    ]
    assert len(prompt_calls) == 1
    assert prompt_calls[0]["request_payload"]["parts"][0]["text"].startswith("Continue")
    assert prompt_calls[0]["metadata"] == {
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
            json={"page": 1, "size": 50, "include_raw": True, "query": {}},
        )
        assert messages_raw_resp.status_code == 200
        messages_raw_payload = messages_raw_resp.json()
        assert messages_raw_payload["success"] is True
        assert messages_raw_payload["result"]["raw"][0]["provider"] == "opencode"

    session_calls = [
        call for call in fake_extensions.calls if call["fn"] == "list_sessions"
    ]
    assert [call["include_raw"] for call in session_calls] == [False, True]
    message_calls = [
        call for call in fake_extensions.calls if call["fn"] == "get_session_messages"
    ]
    assert [call["include_raw"] for call in message_calls] == [True]


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_hub_extension_capabilities_route_returns_model_selection_true(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    agent_id, user = await _create_allowlisted_hub_agent(
        async_session_maker=async_session_maker,
        async_db_session=async_db_session,
        admin_email="admin_opencode_cap_true@example.com",
        user_email="alice_opencode_cap_true@example.com",
        token="secret-token-opencode-capability-true",
    )

    fake_extensions = _FakeExtensionsService()
    fake_extensions.capability_snapshot = SimpleNamespace(
        model_selection=SimpleNamespace(status="supported"),
        provider_discovery=SimpleNamespace(status="supported"),
        session_query=SimpleNamespace(
            status="supported",
            capability=SimpleNamespace(
                ext=SimpleNamespace(
                    methods={"prompt_async": "shared.sessions.prompt_async"}
                )
            ),
        ),
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
        response = await user_client.get(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/capabilities"
        )

    assert response.status_code == 200
    assert response.json() == {
        "modelSelection": True,
        "providerDiscovery": True,
        "sessionPromptAsync": True,
        "runtimeStatus": runtime_status_contract_payload(),
    }
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_hub_extension_capabilities_route_returns_model_selection_false_for_unsupported_agent(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    agent_id, user = await _create_allowlisted_hub_agent(
        async_session_maker=async_session_maker,
        async_db_session=async_db_session,
        admin_email="admin_opencode_cap_false@example.com",
        user_email="alice_opencode_cap_false@example.com",
        token="secret-token-opencode-capability-false",
    )

    fake_extensions = _FakeExtensionsService()
    fake_extensions.capability_snapshot = SimpleNamespace(
        model_selection=SimpleNamespace(status="supported"),
        provider_discovery=SimpleNamespace(status="unsupported"),
        session_query=SimpleNamespace(
            status="supported",
            capability=SimpleNamespace(
                ext=SimpleNamespace(methods={"prompt_async": None})
            ),
        ),
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
        response = await user_client.get(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/capabilities"
        )

    assert response.status_code == 200
    assert response.json() == {
        "modelSelection": True,
        "providerDiscovery": False,
        "sessionPromptAsync": False,
        "runtimeStatus": runtime_status_contract_payload(),
    }
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_hub_extension_capabilities_route_distinguishes_model_selection_from_provider_discovery(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    agent_id, user = await _create_allowlisted_hub_agent(
        async_session_maker=async_session_maker,
        async_db_session=async_db_session,
        admin_email="admin_model_selection_only@example.com",
        user_email="alice_model_selection_only@example.com",
        token="secret-token-model-selection-only",
    )

    fake_extensions = _FakeExtensionsService()
    fake_extensions.capability_snapshot = SimpleNamespace(
        model_selection=SimpleNamespace(status="unsupported"),
        provider_discovery=SimpleNamespace(status="supported"),
        session_query=SimpleNamespace(
            status="supported",
            capability=SimpleNamespace(
                ext=SimpleNamespace(
                    methods={"prompt_async": "shared.sessions.prompt_async"}
                )
            ),
        ),
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
        response = await user_client.get(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/capabilities"
        )

    assert response.status_code == 200
    assert response.json() == {
        "modelSelection": False,
        "providerDiscovery": True,
        "sessionPromptAsync": True,
        "runtimeStatus": runtime_status_contract_payload(),
    }


@pytest.mark.asyncio
async def test_hub_generic_model_discovery_routes_forward_session_metadata(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    agent_id, user = await _create_allowlisted_hub_agent(
        async_session_maker=async_session_maker,
        async_db_session=async_db_session,
        admin_email="admin_model_discovery@example.com",
        user_email="alice_model_discovery@example.com",
        token="secret-token-model-discovery",
    )

    fake_extensions = _FakeExtensionsService()
    monkeypatch.setattr(
        extension_router_common,
        "get_a2a_extensions_service",
        lambda: fake_extensions,
    )

    session_metadata = {
        "shared": {"model": {"providerID": "openai", "modelID": "gpt-5"}},
        "opencode": {"directory": "/workspace"},
    }

    async with create_test_client(
        hub_extension_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as user_client:
        providers_resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/models/providers:list",
            json={"session_metadata": session_metadata},
        )
        assert providers_resp.status_code == 200
        providers_payload = providers_resp.json()
        assert providers_payload["success"] is True
        assert providers_payload["result"]["items"][0]["provider_id"] == "openai"

        models_resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/models:list",
            json={
                "provider_id": "openai",
                "session_metadata": session_metadata,
            },
        )
        assert models_resp.status_code == 200
        models_payload = models_resp.json()
        assert models_payload["success"] is True
        assert models_payload["result"]["items"][0]["model_id"] == "gpt-5"

    assert len(fake_extensions.calls) == 2
    assert fake_extensions.calls[0]["fn"] == "list_model_providers"
    assert fake_extensions.calls[0]["session_metadata"] == session_metadata
    assert fake_extensions.calls[1]["fn"] == "list_models"
    assert fake_extensions.calls[1]["provider_id"] == "openai"
    assert fake_extensions.calls[1]["session_metadata"] == session_metadata
    for call in fake_extensions.calls:
        resolved = call["runtime"].resolved
        assert resolved.headers["Authorization"].endswith(
            "secret-token-model-discovery"
        )


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
