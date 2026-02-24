from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import pytest

from app.api.routers import _opencode_extension_router as opencode_router_common
from app.api.routers import admin_a2a_agents as admin_router
from app.api.routers import hub_a2a_agents as hub_router
from app.api.routers import hub_a2a_extensions_opencode as hub_opencode_router
from app.core.config import settings
from app.integrations.a2a_extensions.errors import (
    A2AExtensionContractError,
    A2AExtensionNotSupportedError,
)
from tests.api_utils import create_test_client
from tests.utils import create_user

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

    async def fetch_agent_card_detail(self, *, resolved, raise_on_failure: bool):
        self.card_calls.append(
            {"resolved": resolved, "raise_on_failure": raise_on_failure}
        )
        return _FakeCard(_valid_card_payload())


class _FakeA2AService:
    def __init__(self, gateway: _FakeGateway) -> None:
        self.gateway = gateway


@dataclass(slots=True)
class _FakeExtensionResult:
    success: bool
    result: Optional[Dict[str, Any]] = None
    error_code: Optional[str] = None
    upstream_error: Optional[Dict[str, Any]] = None
    meta: Optional[Dict[str, Any]] = None


class _FakeExtensionsService:
    def __init__(self) -> None:
        self.calls: list[Dict[str, Any]] = []

    async def opencode_continue_session(self, *, runtime, session_id: str):
        self.calls.append(
            {
                "fn": "opencode_continue_session",
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
                    "opencode_session_id": session_id,
                },
            },
            meta={},
        )

    async def opencode_list_sessions(self, *, runtime, page: int, size, query):
        self.calls.append(
            {
                "fn": "opencode_list_sessions",
                "runtime": runtime,
                "page": page,
                "size": size,
                "query": query,
            }
        )
        return _FakeExtensionResult(
            success=True,
            result={
                "items": [{"id": "sess-1", "title": "One"}],
                "pagination": {
                    "page": page,
                    "size": size or 20,
                    "total": 1,
                    "pages": 1,
                },
                "meta": {},
            },
            meta={},
        )

    async def opencode_get_session_messages(
        self, *, runtime, session_id: str, page: int, size, query
    ):
        self.calls.append(
            {
                "fn": "opencode_get_session_messages",
                "runtime": runtime,
                "session_id": session_id,
                "page": page,
                "size": size,
                "query": query,
            }
        )
        return _FakeExtensionResult(
            success=True,
            result={
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
                "meta": {},
            },
            meta={},
        )

    async def opencode_reply_permission(self, *, runtime, request_id: str, reply: str):
        self.calls.append(
            {
                "fn": "opencode_reply_permission",
                "runtime": runtime,
                "request_id": request_id,
                "reply": reply,
            }
        )
        return _FakeExtensionResult(
            success=True,
            result={"ok": True, "request_id": request_id},
            meta={},
        )

    async def opencode_prompt_async(
        self,
        *,
        runtime,
        session_id: str,
        request_payload,
        metadata,
    ):
        self.calls.append(
            {
                "fn": "opencode_prompt_async",
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

    async def opencode_reply_question(self, *, runtime, request_id: str, answers):
        self.calls.append(
            {
                "fn": "opencode_reply_question",
                "runtime": runtime,
                "request_id": request_id,
                "answers": answers,
            }
        )
        return _FakeExtensionResult(
            success=True,
            result={"ok": True, "request_id": request_id},
            meta={},
        )

    async def opencode_reject_question(self, *, runtime, request_id: str):
        self.calls.append(
            {
                "fn": "opencode_reject_question",
                "runtime": runtime,
                "request_id": request_id,
            }
        )
        return _FakeExtensionResult(
            success=True,
            result={"ok": True, "request_id": request_id},
            meta={},
        )


class _FakeExtensionsErrorService:
    def __init__(self, *, error_code: str, message: str) -> None:
        self.calls: list[Dict[str, Any]] = []
        self.error_code = error_code
        self.message = message

    async def opencode_continue_session(self, *, runtime, session_id: str):
        self.calls.append(
            {
                "fn": "opencode_continue_session",
                "runtime": runtime,
                "session_id": session_id,
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

    async def opencode_continue_session(self, *, runtime, session_id: str):
        self.calls.append(
            {
                "fn": "opencode_continue_session",
                "runtime": runtime,
                "session_id": session_id,
            }
        )
        raise self.error

    async def opencode_reply_question(self, *, runtime, request_id: str, answers):
        self.calls.append(
            {
                "fn": "opencode_reply_question",
                "runtime": runtime,
                "request_id": request_id,
                "answers": answers,
            }
        )
        return _FakeExtensionResult(
            success=True,
            result={"ok": True, "request_id": request_id},
            meta={},
        )

    async def opencode_reject_question(self, *, runtime, request_id: str):
        self.calls.append(
            {
                "fn": "opencode_reject_question",
                "runtime": runtime,
                "request_id": request_id,
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
        opencode_router_common,
        "get_a2a_extensions_service",
        lambda: fake_extensions,
    )

    async with create_test_client(
        hub_opencode_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as user_client:
        continue_resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/opencode/sessions/sess-1:continue"
        )
        assert continue_resp.status_code == 200
        continue_payload = continue_resp.json()
        assert continue_payload["success"] is True

        sessions_resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/opencode/sessions:query",
            json={"page": 1, "size": 20, "query": {}},
        )
        assert sessions_resp.status_code == 200
        sessions_payload = sessions_resp.json()
        assert sessions_payload["success"] is True

        messages_resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/opencode/sessions/sess-1/messages:query",
            json={"page": 1, "size": 50, "query": {}},
        )
        assert messages_resp.status_code == 200
        messages_payload = messages_resp.json()
        assert messages_payload["success"] is True

        permission_reply_resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/opencode/interrupts/permission:reply",
            json={"request_id": "perm-1", "reply": "once"},
        )
        assert permission_reply_resp.status_code == 200
        assert permission_reply_resp.json()["result"] == {
            "ok": True,
            "request_id": "perm-1",
        }

        question_reply_resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/opencode/interrupts/question:reply",
            json={"request_id": "q-1", "answers": [["A"], ["B"]]},
        )
        assert question_reply_resp.status_code == 200
        assert question_reply_resp.json()["result"] == {
            "ok": True,
            "request_id": "q-1",
        }

        question_reject_resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/opencode/interrupts/question:reject",
            json={"request_id": "q-2"},
        )
        assert question_reject_resp.status_code == 200
        assert question_reject_resp.json()["result"] == {
            "ok": True,
            "request_id": "q-2",
        }

        prompt_async_resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/opencode/sessions/sess-1:prompt-async",
            json={
                "request": {
                    "parts": [{"type": "text", "text": "Continue and summarize"}],
                    "noReply": True,
                },
                "metadata": {"opencode": {"directory": "/workspace/project"}},
            },
        )
        assert prompt_async_resp.status_code == 200
        assert prompt_async_resp.json()["result"] == {
            "ok": True,
            "session_id": "sess-1",
        }

    assert len(fake_extensions.calls) == 7
    prompt_calls = [
        c for c in fake_extensions.calls if c["fn"] == "opencode_prompt_async"
    ]
    assert len(prompt_calls) == 1
    assert prompt_calls[0]["request_payload"]["parts"][0]["text"].startswith("Continue")
    assert prompt_calls[0]["metadata"] == {
        "opencode": {"directory": "/workspace/project"}
    }
    for call in fake_extensions.calls:
        resolved = call["runtime"].resolved
        assert resolved.headers["Authorization"].endswith("secret-token-opencode")


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
        opencode_router_common,
        "get_a2a_extensions_service",
        lambda: fake_extensions,
    )

    async with create_test_client(
        hub_opencode_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as user_client:
        resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/opencode/interrupts/permission:reply",
            json={"requestID": "perm-1", "decision": "allow"},
        )
        assert resp.status_code == 422

    assert fake_extensions.calls == []


@pytest.mark.parametrize(
    ("error_code", "message", "expected_status"),
    [
        ("session_not_found", "Session not found", 404),
        ("session_forbidden", "Session access denied", 403),
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
        opencode_router_common,
        "get_a2a_extensions_service",
        lambda: fake_extensions,
    )

    async with create_test_client(
        hub_opencode_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as user_client:
        resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/opencode/sessions/sess-404:continue"
        )
        assert resp.status_code == expected_status
        payload = resp.json()
        assert payload["success"] is False
        assert payload["error_code"] == error_code
        assert payload["upstream_error"] == {"message": message}


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
        opencode_router_common,
        "get_a2a_extensions_service",
        lambda: fake_extensions,
    )

    async with create_test_client(
        hub_opencode_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
        base_prefix=settings.api_v1_prefix,
    ) as user_client:
        resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/opencode/sessions/sess-500:continue"
        )
        assert resp.status_code == 400
        payload = resp.json()
        assert payload["success"] is False
        assert payload["error_code"] == error_code
