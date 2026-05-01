from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Dict, Optional

import pytest

from app.core.config import settings
from app.features.agents.shared import admin_router
from app.features.agents.shared import router as hub_router
from app.features.extension_capabilities import common_router as extension_router_common
from app.features.extension_capabilities import hub_router as hub_extension_router
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
        "version": "1.0",
        "supportedInterfaces": [
            {
                "url": "https://example.com/jsonrpc",
                "protocolBinding": "JSONRPC",
            }
        ],
        "capabilities": {"extensions": []},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
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
                "metadata": {
                    "contextId": session_id,
                    "shared": {
                        "session": {
                            "id": session_id,
                            "provider": "opencode",
                        }
                    },
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

    async def get_session(
        self,
        *,
        runtime,
        session_id: str,
        include_raw=False,
    ):
        raw_item = {"id": session_id, "title": "One", "provider": "opencode"}
        self.calls.append(
            {
                "fn": "get_session",
                "runtime": runtime,
                "session_id": session_id,
                "include_raw": include_raw,
            }
        )
        result = {"item": {"id": session_id, "title": "One"}}
        if include_raw:
            result["raw"] = raw_item
        return _FakeExtensionResult(success=True, result=result, meta={})

    async def get_session_children(
        self,
        *,
        runtime,
        session_id: str,
        include_raw=False,
    ):
        raw_items = [{"id": "child-1", "parentId": session_id, "provider": "opencode"}]
        self.calls.append(
            {
                "fn": "get_session_children",
                "runtime": runtime,
                "session_id": session_id,
                "include_raw": include_raw,
            }
        )
        result = {"items": [{"id": "child-1", "parentId": session_id}]}
        if include_raw:
            result["raw"] = raw_items
        return _FakeExtensionResult(success=True, result=result, meta={})

    async def get_session_todo(
        self,
        *,
        runtime,
        session_id: str,
        include_raw=False,
    ):
        raw_items = [{"id": "todo-1", "sessionId": session_id, "provider": "opencode"}]
        self.calls.append(
            {
                "fn": "get_session_todo",
                "runtime": runtime,
                "session_id": session_id,
                "include_raw": include_raw,
            }
        )
        result = {"items": [{"id": "todo-1", "sessionId": session_id}]}
        if include_raw:
            result["raw"] = raw_items
        return _FakeExtensionResult(success=True, result=result, meta={})

    async def get_session_diff(
        self,
        *,
        runtime,
        session_id: str,
        message_id: str | None = None,
        include_raw=False,
    ):
        raw_items = [
            {
                "path": "README.md",
                "sessionId": session_id,
                "messageId": message_id,
                "provider": "opencode",
            }
        ]
        self.calls.append(
            {
                "fn": "get_session_diff",
                "runtime": runtime,
                "session_id": session_id,
                "message_id": message_id,
                "include_raw": include_raw,
            }
        )
        result = {
            "items": [
                {"path": "README.md", "sessionId": session_id, "messageId": message_id}
            ]
        }
        if include_raw:
            result["raw"] = raw_items
        return _FakeExtensionResult(success=True, result=result, meta={})

    async def get_session_message(
        self,
        *,
        runtime,
        session_id: str,
        message_id: str,
        include_raw=False,
    ):
        raw_item = {
            "id": message_id,
            "sessionId": session_id,
            "text": "hello",
            "provider": "opencode",
        }
        self.calls.append(
            {
                "fn": "get_session_message",
                "runtime": runtime,
                "session_id": session_id,
                "message_id": message_id,
                "include_raw": include_raw,
            }
        )
        result = {"item": {"id": message_id, "sessionId": session_id, "text": "hello"}}
        if include_raw:
            result["raw"] = raw_item
        return _FakeExtensionResult(success=True, result=result, meta={})

    async def fork_session(
        self,
        *,
        runtime,
        session_id: str,
        request_payload=None,
        metadata=None,
    ):
        self.calls.append(
            {
                "fn": "fork_session",
                "runtime": runtime,
                "session_id": session_id,
                "request_payload": request_payload,
                "metadata": metadata,
            }
        )
        return _FakeExtensionResult(
            success=True,
            result={"item": {"id": f"{session_id}-fork", "parentId": session_id}},
            meta={},
        )

    async def share_session(self, *, runtime, session_id: str, metadata=None):
        self.calls.append(
            {
                "fn": "share_session",
                "runtime": runtime,
                "session_id": session_id,
                "metadata": metadata,
            }
        )
        return _FakeExtensionResult(
            success=True,
            result={"item": {"id": session_id, "shared": True}},
            meta={},
        )

    async def unshare_session(self, *, runtime, session_id: str, metadata=None):
        self.calls.append(
            {
                "fn": "unshare_session",
                "runtime": runtime,
                "session_id": session_id,
                "metadata": metadata,
            }
        )
        return _FakeExtensionResult(
            success=True,
            result={"item": {"id": session_id, "shared": False}},
            meta={},
        )

    async def summarize_session(
        self,
        *,
        runtime,
        session_id: str,
        request_payload=None,
        metadata=None,
    ):
        self.calls.append(
            {
                "fn": "summarize_session",
                "runtime": runtime,
                "session_id": session_id,
                "request_payload": request_payload,
                "metadata": metadata,
            }
        )
        return _FakeExtensionResult(
            success=True,
            result={"ok": True, "sessionId": session_id},
            meta={},
        )

    async def revert_session(
        self,
        *,
        runtime,
        session_id: str,
        request_payload,
        metadata=None,
    ):
        self.calls.append(
            {
                "fn": "revert_session",
                "runtime": runtime,
                "session_id": session_id,
                "request_payload": request_payload,
                "metadata": metadata,
            }
        )
        return _FakeExtensionResult(
            success=True,
            result={"item": {"id": session_id, "revertedTo": request_payload}},
            meta={},
        )

    async def unrevert_session(self, *, runtime, session_id: str, metadata=None):
        self.calls.append(
            {
                "fn": "unrevert_session",
                "runtime": runtime,
                "session_id": session_id,
                "metadata": metadata,
            }
        )
        return _FakeExtensionResult(
            success=True,
            result={"item": {"id": session_id, "reverted": False}},
            meta={},
        )

    async def reply_permission_interrupt(
        self,
        *,
        runtime,
        request_id: str,
        reply: str,
        metadata: Optional[Dict[str, Any]] = None,
        working_directory: str | None = None,
    ):
        self.calls.append(
            {
                "fn": "reply_permission_interrupt",
                "runtime": runtime,
                "request_id": request_id,
                "reply": reply,
                "metadata": metadata,
                "working_directory": working_directory,
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
        working_directory: str | None = None,
    ):
        self.calls.append(
            {
                "fn": "reply_permissions_interrupt",
                "runtime": runtime,
                "request_id": request_id,
                "permissions": permissions,
                "scope": scope,
                "metadata": metadata,
                "working_directory": working_directory,
            }
        )
        return _FakeExtensionResult(
            success=True,
            result={"ok": True, "request_id": request_id},
            meta={},
        )

    async def append_session_control(
        self,
        *,
        runtime,
        session_id: str,
        request_payload,
        metadata,
        working_directory: str | None = None,
    ):
        self.calls.append(
            {
                "fn": "append_session_control",
                "runtime": runtime,
                "session_id": session_id,
                "request_payload": request_payload,
                "metadata": metadata,
                "working_directory": working_directory,
            }
        )
        return _FakeExtensionResult(
            success=True,
            result={"ok": True, "session_id": session_id},
            meta={},
        )

    async def prompt_session_async(
        self,
        *,
        runtime,
        session_id: str,
        request_payload,
        metadata,
        working_directory: str | None = None,
    ):
        self.calls.append(
            {
                "fn": "prompt_session_async",
                "runtime": runtime,
                "session_id": session_id,
                "request_payload": request_payload,
                "metadata": metadata,
                "working_directory": working_directory,
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
        working_directory: str | None = None,
    ):
        self.calls.append(
            {
                "fn": "command_session",
                "runtime": runtime,
                "session_id": session_id,
                "request_payload": request_payload,
                "metadata": metadata,
                "working_directory": working_directory,
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
        working_directory: str | None = None,
    ):
        self.calls.append(
            {
                "fn": "reply_question_interrupt",
                "runtime": runtime,
                "request_id": request_id,
                "answers": answers,
                "metadata": metadata,
                "working_directory": working_directory,
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
        working_directory: str | None = None,
    ):
        self.calls.append(
            {
                "fn": "reply_elicitation_interrupt",
                "runtime": runtime,
                "request_id": request_id,
                "action": action,
                "content": content,
                "metadata": metadata,
                "working_directory": working_directory,
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
        working_directory: str | None = None,
    ):
        self.calls.append(
            {
                "fn": "list_model_providers",
                "runtime": runtime,
                "session_metadata": session_metadata,
                "working_directory": working_directory,
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
        working_directory: str | None = None,
    ):
        self.calls.append(
            {
                "fn": "list_models",
                "runtime": runtime,
                "provider_id": provider_id,
                "session_metadata": session_metadata,
                "working_directory": working_directory,
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

    async def list_upstream_skills(self, *, runtime):
        self.calls.append({"fn": "list_upstream_skills", "runtime": runtime})
        return _FakeExtensionResult(
            success=True,
            result={
                "items": [
                    {
                        "cwd": "/workspace/project",
                        "skills": [
                            {
                                "name": "planning",
                                "path": "/workspace/project/.codex/skills/PLANNING/SKILL.md",
                                "description": "Summarize plans.",
                                "enabled": True,
                                "scope": "project",
                                "interface": {"input": "rich-text"},
                                "providerPrivate": {"raw": {"name": "planning"}},
                            }
                        ],
                        "errors": [],
                        "providerPrivate": {"raw": {"cwd": "/workspace/project"}},
                    }
                ]
            },
            meta={"capability_area": "upstream_discovery"},
        )

    async def list_upstream_apps(self, *, runtime):
        self.calls.append({"fn": "list_upstream_apps", "runtime": runtime})
        return _FakeExtensionResult(
            success=True,
            result={
                "items": [
                    {
                        "id": "app-1",
                        "name": "workspace",
                        "description": "Manage files.",
                        "isAccessible": True,
                        "isEnabled": True,
                        "installUrl": "https://example.com/install",
                        "mentionPath": "app://app-1",
                        "branding": {"icon": "workspace"},
                        "labels": [],
                        "providerPrivate": {"raw": {"id": "app-1"}},
                    }
                ],
                "nextCursor": None,
            },
            meta={"capability_area": "upstream_discovery"},
        )

    async def list_upstream_plugins(self, *, runtime):
        self.calls.append({"fn": "list_upstream_plugins", "runtime": runtime})
        return _FakeExtensionResult(
            success=True,
            result={
                "items": [
                    {
                        "marketplaceName": "test",
                        "marketplacePath": "/workspace/project/.codex/plugins/marketplace.json",
                        "interface": {"transport": "mcp"},
                        "plugins": [
                            {
                                "name": "planner",
                                "description": "Coordinates work.",
                                "enabled": True,
                                "mentionPath": "plugin://planner@test",
                                "providerPrivate": {"raw": {"name": "planner"}},
                            }
                        ],
                        "providerPrivate": {"raw": {"name": "test"}},
                    }
                ],
                "featuredPluginIds": ["test:planner"],
                "marketplaceLoadErrors": [],
                "remoteSyncError": None,
            },
            meta={"capability_area": "upstream_discovery"},
        )

    async def read_upstream_plugin(
        self, *, runtime, marketplace_path: str, plugin_name: str
    ):
        self.calls.append(
            {
                "fn": "read_upstream_plugin",
                "runtime": runtime,
                "marketplace_path": marketplace_path,
                "plugin_name": plugin_name,
            }
        )
        return _FakeExtensionResult(
            success=True,
            result={
                "item": {
                    "name": plugin_name,
                    "marketplaceName": "test",
                    "marketplacePath": marketplace_path,
                    "mentionPath": "plugin://planner@test",
                    "summary": ["Use for planning"],
                    "skills": [{"name": "planning"}],
                    "apps": [{"id": "app-1"}],
                    "mcpServers": ["planner-server"],
                    "interface": {"transport": "mcp"},
                    "providerPrivate": {"raw": {"name": plugin_name}},
                }
            },
            meta={"capability_area": "upstream_discovery"},
        )

    async def reject_question_interrupt(
        self,
        *,
        runtime,
        request_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        working_directory: str | None = None,
    ):
        self.calls.append(
            {
                "fn": "reject_question_interrupt",
                "runtime": runtime,
                "request_id": request_id,
                "metadata": metadata,
                "working_directory": working_directory,
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
        working_directory: str | None = None,
    ):
        self.calls.append(
            {
                "fn": "reply_permission_interrupt",
                "runtime": runtime,
                "request_id": request_id,
                "reply": reply,
                "metadata": metadata,
                "working_directory": working_directory,
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
        working_directory: str | None = None,
    ):
        self.calls.append(
            {
                "fn": "reply_permissions_interrupt",
                "runtime": runtime,
                "request_id": request_id,
                "permissions": permissions,
                "scope": scope,
                "metadata": metadata,
                "working_directory": working_directory,
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
        working_directory: str | None = None,
    ):
        self.calls.append(
            {
                "fn": "reply_elicitation_interrupt",
                "runtime": runtime,
                "request_id": request_id,
                "action": action,
                "content": content,
                "metadata": metadata,
                "working_directory": working_directory,
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
        self,
        *,
        runtime,
        request_id: str,
        answers,
        metadata=None,
        working_directory: str | None = None,
    ):
        self.calls.append(
            {
                "fn": "reply_question_interrupt",
                "runtime": runtime,
                "request_id": request_id,
                "answers": answers,
                "metadata": metadata,
                "working_directory": working_directory,
            }
        )
        return _FakeExtensionResult(
            success=True,
            result={"ok": True, "request_id": request_id},
            meta={},
        )

    async def reject_question_interrupt(
        self,
        *,
        runtime,
        request_id: str,
        metadata=None,
        working_directory: str | None = None,
    ):
        self.calls.append(
            {
                "fn": "reject_question_interrupt",
                "runtime": runtime,
                "request_id": request_id,
                "metadata": metadata,
                "working_directory": working_directory,
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


__all__ = [
    "A2AExtensionContractError",
    "A2AExtensionNotSupportedError",
    "Any",
    "Dict",
    "SimpleNamespace",
    "_FakeA2AService",
    "_FakeElicitationReplyErrorService",
    "_FakeExtensionsErrorService",
    "_FakeExtensionsExceptionService",
    "_FakeExtensionsService",
    "_FakeGateway",
    "_FakePermissionReplyErrorService",
    "_FakePermissionsReplyErrorService",
    "_create_allowlisted_hub_agent",
    "admin_router",
    "create_test_client",
    "create_user",
    "extension_router_common",
    "hub_extension_router",
    "hub_router",
    "pytest",
    "runtime_status_contract_payload",
    "settings",
]
