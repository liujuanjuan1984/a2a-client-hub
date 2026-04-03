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
            interrupt_recovery=SimpleNamespace(status="unsupported"),
            invoke_metadata=SimpleNamespace(status="unsupported", ext=None),
            session_query=SimpleNamespace(status="unsupported", capability=None),
            compatibility_profile=SimpleNamespace(
                status="unsupported",
                ext=None,
                error="Compatibility profile extension not found",
            ),
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
        self, *, runtime, page: int, size, query, filters=None, include_raw=False
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
                "filters": filters,
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
        before,
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
                "before": before,
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
            "pageInfo": {
                "hasMoreBefore": True,
                "nextBefore": "cursor-2" if before else None,
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

    async def recover_interrupts(self, *, runtime, session_id: str | None = None):
        self.calls.append(
            {
                "fn": "recover_interrupts",
                "runtime": runtime,
                "session_id": session_id,
            }
        )
        items = [
            {
                "request_id": "perm-1",
                "session_id": session_id or "sess-1",
                "type": "permission",
                "details": {"permission": "write"},
                "expires_at": 123.0,
            }
        ]
        return _FakeExtensionResult(success=True, result={"items": items}, meta={})

    async def reply_permissions_interrupt(
        self,
        *,
        runtime,
        request_id: str,
        permissions: Dict[str, Any],
        scope: str | None = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.calls.append(
            {
                "fn": "reply_permissions_interrupt",
                "runtime": runtime,
                "request_id": request_id,
                "permissions": permissions,
                "scope": scope,
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

    async def command_session(
        self,
        *,
        runtime,
        session_id: str,
        request_payload,
        metadata,
    ):
        self.calls.append(
            {
                "fn": "command_session",
                "runtime": runtime,
                "session_id": session_id,
                "request_payload": request_payload,
                "metadata": metadata,
            }
        )
        return _FakeExtensionResult(
            success=True,
            result={
                "item": {
                    "kind": "message",
                    "messageId": "msg-cmd-1",
                    "role": "assistant",
                }
            },
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

    async def reply_elicitation_interrupt(
        self,
        *,
        runtime,
        request_id: str,
        action: str,
        content=None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.calls.append(
            {
                "fn": "reply_elicitation_interrupt",
                "runtime": runtime,
                "request_id": request_id,
                "action": action,
                "content": content,
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

    async def list_codex_skills(self, *, runtime):
        self.calls.append({"fn": "list_codex_skills", "runtime": runtime})
        return _FakeExtensionResult(
            success=True,
            result={
                "items": [
                    {
                        "id": "skill-1",
                        "kind": "skill",
                        "name": "planning",
                        "title": "Planning",
                        "summary": "Summarize plans.",
                        "description": None,
                        "tags": ["analysis"],
                        "metadata": {"source": "codex"},
                    }
                ],
                "nextCursor": "cursor-2",
            },
            meta={"capability_area": "codex_discovery"},
        )

    async def list_codex_apps(self, *, runtime):
        self.calls.append({"fn": "list_codex_apps", "runtime": runtime})
        return _FakeExtensionResult(
            success=True,
            result={
                "items": [
                    {
                        "id": "app-1",
                        "kind": "app",
                        "name": "workspace",
                        "title": "Workspace",
                        "summary": "Manage files.",
                        "description": None,
                        "tags": [],
                        "metadata": {},
                    }
                ]
            },
            meta={"capability_area": "codex_discovery"},
        )

    async def list_codex_plugins(self, *, runtime):
        self.calls.append({"fn": "list_codex_plugins", "runtime": runtime})
        return _FakeExtensionResult(
            success=True,
            result={
                "items": [
                    {
                        "id": "plugin-1",
                        "kind": "plugin",
                        "name": "planner",
                        "title": "Planner",
                        "summary": "Coordinates work.",
                        "description": None,
                        "tags": ["planning"],
                        "metadata": {"version": "1.0"},
                    }
                ]
            },
            meta={"capability_area": "codex_discovery"},
        )

    async def read_codex_plugin(self, *, runtime, plugin_id: str):
        self.calls.append(
            {
                "fn": "read_codex_plugin",
                "runtime": runtime,
                "plugin_id": plugin_id,
            }
        )
        return _FakeExtensionResult(
            success=True,
            result={
                "plugin": {
                    "id": plugin_id,
                    "kind": "plugin",
                    "name": "planner",
                    "title": "Planner",
                    "summary": None,
                    "description": "Coordinates work.",
                    "tags": [],
                    "metadata": {"version": "1.0"},
                    "content": {"readme": "Use for planning"},
                }
            },
            meta={"capability_area": "codex_discovery"},
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


class _FakePermissionsReplyErrorService:
    def __init__(self, *, error_code: str, message: str) -> None:
        self.calls: list[Dict[str, Any]] = []
        self.error_code = error_code
        self.message = message

    async def reply_permissions_interrupt(
        self,
        *,
        runtime,
        request_id: str,
        permissions: Dict[str, Any],
        scope: str | None = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.calls.append(
            {
                "fn": "reply_permissions_interrupt",
                "runtime": runtime,
                "request_id": request_id,
                "permissions": permissions,
                "scope": scope,
                "metadata": metadata,
            }
        )
        return _FakeExtensionResult(
            success=False,
            error_code=self.error_code,
            upstream_error={"message": self.message},
            meta={},
        )


class _FakeElicitationReplyErrorService:
    def __init__(self, *, error_code: str, message: str) -> None:
        self.calls: list[Dict[str, Any]] = []
        self.error_code = error_code
        self.message = message

    async def reply_elicitation_interrupt(
        self,
        *,
        runtime,
        request_id: str,
        action: str,
        content=None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.calls.append(
            {
                "fn": "reply_elicitation_interrupt",
                "runtime": runtime,
                "request_id": request_id,
                "action": action,
                "content": content,
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
    assert payload["shared_session_query"]["status"] == "supported"
    assert payload["shared_session_query"]["declaredContractFamily"] == "legacy"
    assert payload["shared_session_query"]["normalizedContractFamily"] == (
        "a2a_client_hub"
    )
    assert payload["shared_session_query"]["uses_legacy_uri"] is True


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
        {
            "uri": "urn:opencode-a2a:session-query/v1",
            "params": {
                "provider": "opencode",
                "methods": {
                    "list_sessions": "opencode.sessions.list",
                    "get_session_messages": "opencode.sessions.messages.list",
                },
                "pagination": {
                    "mode": "limit_and_optional_cursor",
                    "default_limit": 20,
                    "max_limit": 100,
                    "params": ["limit", "before"],
                    "cursor_param": "before",
                    "result_cursor_field": "next_cursor",
                    "cursor_applies_to": ["opencode.sessions.messages.list"],
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
    assert payload["message"] == "Agent card validated"
    assert payload["shared_session_query"]["status"] == "supported"
    assert payload["shared_session_query"]["declaredContractFamily"] == "opencode"
    assert payload["shared_session_query"]["normalizedContractFamily"] == (
        "a2a_client_hub"
    )
    assert payload["shared_session_query"]["pagination_mode"] == (
        "limit_and_optional_cursor"
    )
    assert payload["shared_session_query"]["pagination_params"] == ["limit", "before"]


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
    assert payload["compatibility_profile"]["methodRetention"] == {
        "opencode.sessions.shell": {
            "surface": "extension",
            "availability": "disabled",
            "retention": "deployment-conditional",
            "extensionUri": "urn:opencode-a2a:session-query/v1",
            "toggle": "A2A_ENABLE_SESSION_SHELL",
        }
    }


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
        interrupt_recovery=SimpleNamespace(status="supported"),
        wire_contract=SimpleNamespace(
            status="supported",
            error=None,
            ext=SimpleNamespace(
                protocol_version="0.3.0",
                preferred_transport="HTTP+JSON",
                additional_transports=("JSON-RPC",),
                all_jsonrpc_methods=(
                    "shared.sessions.prompt_async",
                    "shared.sessions.command",
                    "providers.list",
                    "models.list",
                    "codex.discovery.skills.list",
                    "codex.discovery.plugins.list",
                    "codex.discovery.plugins.read",
                    "codex.threads.watch",
                    "codex.exec.start",
                    "codex.exec.terminate",
                ),
                extension_uris=(
                    "urn:opencode-a2a:provider-discovery/v1",
                    "urn:opencode-a2a:session-query/v1",
                ),
                conditionally_available_methods={
                    "opencode.sessions.shell": SimpleNamespace(
                        reason="disabled_by_configuration",
                        toggle="A2A_ENABLE_SESSION_SHELL",
                    )
                },
                unsupported_method_error=SimpleNamespace(
                    code=-32601,
                    type="METHOD_NOT_SUPPORTED",
                    data_fields=(
                        "type",
                        "method",
                        "supported_methods",
                        "protocol_version",
                    ),
                ),
            ),
        ),
        compatibility_profile=SimpleNamespace(
            status="supported",
            error=None,
            ext=SimpleNamespace(
                uri="urn:a2a:compatibility-profile/v1",
                extension_retention={
                    "urn:opencode-a2a:session-query/v1": SimpleNamespace(
                        surface="jsonrpc-extension",
                        availability="always",
                        retention="stable",
                        extension_uri=None,
                        toggle=None,
                    )
                },
                method_retention={
                    "opencode.sessions.shell": SimpleNamespace(
                        surface="extension",
                        availability="disabled",
                        retention="deployment-conditional",
                        extension_uri="urn:opencode-a2a:session-query/v1",
                        toggle="A2A_ENABLE_SESSION_SHELL",
                    )
                },
                service_behaviors={
                    "classification": "stable-service-semantics",
                    "methods": {"tasks/cancel": {"retention": "stable"}},
                },
                consumer_guidance=(
                    "Treat opencode.sessions.shell as deployment-conditional.",
                ),
            ),
        ),
        codex_discovery=SimpleNamespace(
            declared=True,
            consumed_by_hub=True,
            status="supported",
            declaration_source="wire_contract",
            declaration_confidence="authoritative",
            negotiation_state="supported",
            diagnostic_note=None,
            methods={
                "skillsList": SimpleNamespace(
                    declared=True,
                    consumed_by_hub=True,
                    method="codex.discovery.skills.list",
                ),
                "appsList": SimpleNamespace(
                    declared=False,
                    consumed_by_hub=False,
                    method=None,
                ),
                "pluginsList": SimpleNamespace(
                    declared=True,
                    consumed_by_hub=True,
                    method="codex.discovery.plugins.list",
                ),
                "pluginsRead": SimpleNamespace(
                    declared=True,
                    consumed_by_hub=True,
                    method="codex.discovery.plugins.read",
                ),
                "watch": SimpleNamespace(
                    declared=False,
                    consumed_by_hub=False,
                    method=None,
                ),
            },
        ),
        codex_thread_watch=SimpleNamespace(
            declared=True,
            consumed_by_hub=False,
            status="unsupported_by_design",
            method="codex.threads.watch",
        ),
        codex_exec=SimpleNamespace(
            declared=True,
            consumed_by_hub=False,
            status="unsupported_by_design",
            methods={
                "start": SimpleNamespace(
                    declared=True,
                    consumed_by_hub=False,
                    method="codex.exec.start",
                ),
                "write": SimpleNamespace(
                    declared=False,
                    consumed_by_hub=False,
                    method=None,
                ),
                "resize": SimpleNamespace(
                    declared=False,
                    consumed_by_hub=False,
                    method=None,
                ),
                "terminate": SimpleNamespace(
                    declared=True,
                    consumed_by_hub=False,
                    method="codex.exec.terminate",
                ),
            },
        ),
        session_query=SimpleNamespace(
            status="supported",
            capability=SimpleNamespace(
                control_methods={
                    "prompt_async": SimpleNamespace(
                        declared=True,
                        availability="always",
                        method="shared.sessions.prompt_async",
                    ),
                    "command": SimpleNamespace(
                        declared=True,
                        availability="always",
                        method="shared.sessions.command",
                    ),
                    "shell": SimpleNamespace(
                        declared=False,
                        availability="conditional",
                        config_key="A2A_ENABLE_SESSION_SHELL",
                        enabled_by_default=False,
                    ),
                }
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
        "interruptRecovery": True,
        "sessionPromptAsync": True,
        "sessionControl": {
            "promptAsync": {
                "declared": True,
                "consumedByHub": True,
                "availability": "always",
                "method": "shared.sessions.prompt_async",
                "enabledByDefault": None,
                "configKey": None,
            },
            "command": {
                "declared": True,
                "consumedByHub": True,
                "availability": "always",
                "method": "shared.sessions.command",
                "enabledByDefault": None,
                "configKey": None,
            },
            "shell": {
                "declared": False,
                "consumedByHub": False,
                "availability": "conditional",
                "method": None,
                "enabledByDefault": False,
                "configKey": "A2A_ENABLE_SESSION_SHELL",
            },
        },
        "invokeMetadata": {
            "declared": False,
            "consumedByHub": True,
            "metadataField": None,
            "appliesToMethods": [],
            "fields": [],
        },
        "wireContract": {
            "declared": True,
            "consumedByHub": True,
            "status": "supported",
            "protocolVersion": "0.3.0",
            "preferredTransport": "HTTP+JSON",
            "additionalTransports": ["JSON-RPC"],
            "allJsonrpcMethods": [
                "shared.sessions.prompt_async",
                "shared.sessions.command",
                "providers.list",
                "models.list",
                "codex.discovery.skills.list",
                "codex.discovery.plugins.list",
                "codex.discovery.plugins.read",
                "codex.threads.watch",
                "codex.exec.start",
                "codex.exec.terminate",
            ],
            "extensionUris": [
                "urn:opencode-a2a:provider-discovery/v1",
                "urn:opencode-a2a:session-query/v1",
            ],
            "conditionalMethods": {
                "opencode.sessions.shell": {
                    "reason": "disabled_by_configuration",
                    "toggle": "A2A_ENABLE_SESSION_SHELL",
                }
            },
            "unsupportedMethodError": {
                "code": -32601,
                "type": "METHOD_NOT_SUPPORTED",
                "dataFields": [
                    "type",
                    "method",
                    "supported_methods",
                    "protocol_version",
                ],
            },
            "error": None,
        },
        "compatibilityProfile": {
            "declared": True,
            "status": "supported",
            "uri": "urn:a2a:compatibility-profile/v1",
            "extensionRetention": {
                "urn:opencode-a2a:session-query/v1": {
                    "surface": "jsonrpc-extension",
                    "availability": "always",
                    "retention": "stable",
                    "extensionUri": None,
                    "toggle": None,
                }
            },
            "methodRetention": {
                "opencode.sessions.shell": {
                    "surface": "extension",
                    "availability": "disabled",
                    "retention": "deployment-conditional",
                    "extensionUri": "urn:opencode-a2a:session-query/v1",
                    "toggle": "A2A_ENABLE_SESSION_SHELL",
                }
            },
            "serviceBehaviors": {
                "classification": "stable-service-semantics",
                "methods": {"tasks/cancel": {"retention": "stable"}},
            },
            "consumerGuidance": [
                "Treat opencode.sessions.shell as deployment-conditional."
            ],
            "error": None,
        },
        "codexDiscovery": {
            "declared": True,
            "consumedByHub": True,
            "status": "supported",
            "declarationSource": "wire_contract",
            "declarationConfidence": "authoritative",
            "negotiationState": "supported",
            "diagnosticNote": None,
            "methods": {
                "skillsList": {
                    "declared": True,
                    "consumedByHub": True,
                    "method": "codex.discovery.skills.list",
                },
                "appsList": {
                    "declared": False,
                    "consumedByHub": False,
                    "method": None,
                },
                "pluginsList": {
                    "declared": True,
                    "consumedByHub": True,
                    "method": "codex.discovery.plugins.list",
                },
                "pluginsRead": {
                    "declared": True,
                    "consumedByHub": True,
                    "method": "codex.discovery.plugins.read",
                },
                "watch": {
                    "declared": False,
                    "consumedByHub": False,
                    "method": None,
                },
            },
        },
        "codexThreadWatch": {
            "declared": True,
            "consumedByHub": False,
            "status": "unsupported_by_design",
            "method": "codex.threads.watch",
        },
        "codexExec": {
            "declared": True,
            "consumedByHub": False,
            "status": "unsupported_by_design",
            "declarationSource": None,
            "declarationConfidence": None,
            "negotiationState": None,
            "diagnosticNote": None,
            "methods": {
                "start": {
                    "declared": True,
                    "consumedByHub": False,
                    "method": "codex.exec.start",
                },
                "write": {
                    "declared": False,
                    "consumedByHub": False,
                    "method": None,
                },
                "resize": {
                    "declared": False,
                    "consumedByHub": False,
                    "method": None,
                },
                "terminate": {
                    "declared": True,
                    "consumedByHub": False,
                    "method": "codex.exec.terminate",
                },
            },
        },
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
        interrupt_recovery=SimpleNamespace(status="unsupported"),
        wire_contract=SimpleNamespace(
            status="unsupported",
            ext=None,
            error="Wire contract extension not found",
        ),
        compatibility_profile=SimpleNamespace(
            status="unsupported",
            ext=None,
            error="Compatibility profile extension not found",
        ),
        session_query=SimpleNamespace(
            status="supported",
            capability=SimpleNamespace(
                control_methods={
                    "prompt_async": SimpleNamespace(
                        declared=False,
                        availability="unsupported",
                        method=None,
                    ),
                    "command": SimpleNamespace(
                        declared=False,
                        availability="unsupported",
                        method=None,
                    ),
                    "shell": SimpleNamespace(
                        declared=False,
                        availability="unsupported",
                        method=None,
                    ),
                }
            ),
        ),
        invoke_metadata=SimpleNamespace(status="unsupported", ext=None),
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
        "interruptRecovery": False,
        "sessionPromptAsync": False,
        "sessionControl": {
            "promptAsync": {
                "declared": False,
                "consumedByHub": True,
                "availability": "unsupported",
                "method": None,
                "enabledByDefault": None,
                "configKey": None,
            },
            "command": {
                "declared": False,
                "consumedByHub": True,
                "availability": "unsupported",
                "method": None,
                "enabledByDefault": None,
                "configKey": None,
            },
            "shell": {
                "declared": False,
                "consumedByHub": False,
                "availability": "unsupported",
                "method": None,
                "enabledByDefault": None,
                "configKey": None,
            },
        },
        "invokeMetadata": {
            "declared": False,
            "consumedByHub": True,
            "metadataField": None,
            "appliesToMethods": [],
            "fields": [],
        },
        "wireContract": {
            "declared": False,
            "consumedByHub": True,
            "status": "unsupported",
            "protocolVersion": None,
            "preferredTransport": None,
            "additionalTransports": [],
            "allJsonrpcMethods": [],
            "extensionUris": [],
            "conditionalMethods": {},
            "unsupportedMethodError": None,
            "error": "Wire contract extension not found",
        },
        "compatibilityProfile": {
            "declared": False,
            "status": "unsupported",
            "uri": None,
            "extensionRetention": {},
            "methodRetention": {},
            "serviceBehaviors": {},
            "consumerGuidance": [],
            "error": "Compatibility profile extension not found",
        },
        "codexDiscovery": {
            "declared": False,
            "consumedByHub": False,
            "status": "unsupported",
            "methods": {},
            "declarationSource": None,
            "declarationConfidence": None,
            "negotiationState": None,
            "diagnosticNote": None,
        },
        "codexThreadWatch": {
            "declared": False,
            "consumedByHub": False,
            "status": "unsupported",
            "method": None,
        },
        "codexExec": {
            "declared": False,
            "consumedByHub": False,
            "status": "unsupported",
            "declarationSource": None,
            "declarationConfidence": None,
            "negotiationState": None,
            "diagnosticNote": None,
            "methods": {},
        },
        "runtimeStatus": runtime_status_contract_payload(),
    }


@pytest.mark.asyncio
async def test_hub_extension_capabilities_closes_read_only_transaction_before_upstream_call(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    agent_id, user = await _create_allowlisted_hub_agent(
        async_session_maker=async_session_maker,
        async_db_session=async_db_session,
        admin_email="admin_opencode_cap_close@example.com",
        user_email="alice_opencode_cap_close@example.com",
        token="secret-token-opencode-cap-close",
    )

    call_order: list[str] = []
    fake_extensions = _FakeExtensionsService()

    async def fake_load_for_external_call(_db, operation):
        call_order.append("prepare_external_call")
        return await operation(_db)

    async def fake_resolve_capability_snapshot(*, runtime):
        call_order.append("resolve_capability_snapshot")
        return await _FakeExtensionsService.resolve_capability_snapshot(
            fake_extensions,
            runtime=runtime,
        )

    monkeypatch.setattr(
        extension_router_common,
        "load_for_external_call",
        fake_load_for_external_call,
    )
    monkeypatch.setattr(
        fake_extensions,
        "resolve_capability_snapshot",
        fake_resolve_capability_snapshot,
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
    assert call_order == ["prepare_external_call", "resolve_capability_snapshot"]
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
        interrupt_recovery=SimpleNamespace(status="unsupported"),
        wire_contract=SimpleNamespace(
            status="invalid",
            ext=None,
            error="Extension contract missing/invalid 'params.extensions.jsonrpc_methods'",
        ),
        compatibility_profile=SimpleNamespace(
            status="invalid",
            ext=None,
            error="Extension contract missing/invalid 'params.method_retention'",
        ),
        session_query=SimpleNamespace(
            status="supported",
            capability=SimpleNamespace(
                control_methods={
                    "prompt_async": SimpleNamespace(
                        declared=True,
                        availability="always",
                        method="shared.sessions.prompt_async",
                    ),
                    "command": SimpleNamespace(
                        declared=True,
                        availability="always",
                        method="shared.sessions.command",
                    ),
                    "shell": SimpleNamespace(
                        declared=False,
                        availability="conditional",
                        config_key="A2A_ENABLE_SESSION_SHELL",
                        enabled_by_default=False,
                    ),
                }
            ),
        ),
        invoke_metadata=SimpleNamespace(status="unsupported", ext=None),
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
        "interruptRecovery": False,
        "sessionPromptAsync": True,
        "sessionControl": {
            "promptAsync": {
                "declared": True,
                "consumedByHub": True,
                "availability": "always",
                "method": "shared.sessions.prompt_async",
                "enabledByDefault": None,
                "configKey": None,
            },
            "command": {
                "declared": True,
                "consumedByHub": True,
                "availability": "always",
                "method": "shared.sessions.command",
                "enabledByDefault": None,
                "configKey": None,
            },
            "shell": {
                "declared": False,
                "consumedByHub": False,
                "availability": "conditional",
                "method": None,
                "enabledByDefault": False,
                "configKey": "A2A_ENABLE_SESSION_SHELL",
            },
        },
        "invokeMetadata": {
            "declared": False,
            "consumedByHub": True,
            "metadataField": None,
            "appliesToMethods": [],
            "fields": [],
        },
        "wireContract": {
            "declared": True,
            "consumedByHub": True,
            "status": "invalid",
            "protocolVersion": None,
            "preferredTransport": None,
            "additionalTransports": [],
            "allJsonrpcMethods": [],
            "extensionUris": [],
            "conditionalMethods": {},
            "unsupportedMethodError": None,
            "error": "Extension contract missing/invalid 'params.extensions.jsonrpc_methods'",
        },
        "compatibilityProfile": {
            "declared": True,
            "status": "invalid",
            "uri": None,
            "extensionRetention": {},
            "methodRetention": {},
            "serviceBehaviors": {},
            "consumerGuidance": [],
            "error": "Extension contract missing/invalid 'params.method_retention'",
        },
        "codexDiscovery": {
            "declared": False,
            "consumedByHub": False,
            "status": "unsupported",
            "methods": {},
            "declarationSource": None,
            "declarationConfidence": None,
            "negotiationState": None,
            "diagnosticNote": None,
        },
        "codexThreadWatch": {
            "declared": False,
            "consumedByHub": False,
            "status": "unsupported",
            "method": None,
        },
        "codexExec": {
            "declared": False,
            "consumedByHub": False,
            "status": "unsupported",
            "declarationSource": None,
            "declarationConfidence": None,
            "negotiationState": None,
            "diagnosticNote": None,
            "methods": {},
        },
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
async def test_hub_codex_discovery_routes_return_normalized_results(
    async_session_maker, async_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    agent_id, user = await _create_allowlisted_hub_agent(
        async_session_maker=async_session_maker,
        async_db_session=async_db_session,
        admin_email="admin_codex_discovery@example.com",
        user_email="alice_codex_discovery@example.com",
        token="secret-token-codex-discovery",
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
        skills_resp = await user_client.get(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/codex/skills"
        )
        assert skills_resp.status_code == 200
        skills_payload = skills_resp.json()
        assert skills_payload["success"] is True
        assert skills_payload["result"]["items"][0]["kind"] == "skill"
        assert skills_payload["result"]["nextCursor"] == "cursor-2"

        plugin_resp = await user_client.post(
            f"{settings.api_v1_prefix}/a2a/agents/{agent_id}/extensions/codex/plugins:read",
            json={"pluginId": "planner"},
        )
        assert plugin_resp.status_code == 200
        plugin_payload = plugin_resp.json()
        assert plugin_payload["success"] is True
        assert plugin_payload["result"]["plugin"]["id"] == "planner"
        assert plugin_payload["result"]["plugin"]["content"] == {
            "readme": "Use for planning"
        }

    assert fake_extensions.calls[0]["fn"] == "list_codex_skills"
    assert fake_extensions.calls[1]["fn"] == "read_codex_plugin"
    assert fake_extensions.calls[1]["plugin_id"] == "planner"


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
