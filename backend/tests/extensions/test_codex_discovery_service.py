from __future__ import annotations

import pytest

from app.integrations.a2a_extensions.codex_discovery_service import (
    UpstreamDiscoveryService,
)
from app.integrations.a2a_extensions.service_common import ExtensionCallResult


class _FakeSupport:
    @staticmethod
    async def perform_jsonrpc_call(**_kwargs):
        raise AssertionError("perform_jsonrpc_call should be stubbed per test")

    @staticmethod
    def record_extension_metric(*_args, **_kwargs):
        return None

    @staticmethod
    def build_upstream_error_details(*_args, **_kwargs):
        raise AssertionError("error details helper should not be used in these tests")


@pytest.mark.asyncio
async def test_list_skills_normalizes_skill_scopes() -> None:
    service = UpstreamDiscoveryService(_FakeSupport())
    runtime = object()

    async def _fake_invoke_method(**kwargs):
        assert kwargs["method_name"] == "codex.discovery.skills.list"
        return ExtensionCallResult(
            success=True,
            result={
                "items": [
                    {
                        "cwd": "/workspace/project",
                        "skills": [
                            {
                                "name": "Planning",
                                "path": "/workspace/project/.codex/skills/PLANNING/SKILL.md",
                                "description": "Summarize plans.",
                                "enabled": True,
                                "scope": "project",
                                "interface": {"input": "rich-text"},
                                "codex": {"raw": {"id": "planning"}},
                            }
                        ],
                        "errors": [],
                        "codex": {"raw": {"cwd": "/workspace/project"}},
                    }
                ]
            },
            meta=kwargs["meta"],
        )

    service.invoke_method = _fake_invoke_method  # type: ignore[method-assign]

    result = await service.list_skills(
        runtime=runtime,
        jsonrpc_url="https://example.com/jsonrpc",
        method_name="codex.discovery.skills.list",
        meta={"capability_area": "upstream_discovery"},
    )

    assert result.success is True
    assert result.result == {
        "items": [
            {
                "cwd": "/workspace/project",
                "skills": [
                    {
                        "name": "Planning",
                        "path": "/workspace/project/.codex/skills/PLANNING/SKILL.md",
                        "description": "Summarize plans.",
                        "enabled": True,
                        "scope": "project",
                        "interface": {"input": "rich-text"},
                        "codex": {"raw": {"id": "planning"}},
                    }
                ],
                "errors": [],
                "codex": {"raw": {"cwd": "/workspace/project"}},
            }
        ]
    }


@pytest.mark.asyncio
async def test_list_apps_normalizes_items_and_cursor() -> None:
    service = UpstreamDiscoveryService(_FakeSupport())
    runtime = object()

    async def _fake_invoke_method(**kwargs):
        assert kwargs["method_name"] == "codex.discovery.apps.list"
        return ExtensionCallResult(
            success=True,
            result={
                "items": [
                    {
                        "id": "demo-app",
                        "name": "Demo App",
                        "description": "Launch demos.",
                        "isAccessible": True,
                        "isEnabled": True,
                        "installUrl": "https://example.com/install",
                        "mention_path": "app://demo-app",
                        "branding": {"icon": "spark"},
                        "labels": [{"name": "beta"}],
                        "codex": {"raw": {"id": "demo-app"}},
                    }
                ],
                "next_cursor": "cursor-2",
            },
            meta=kwargs["meta"],
        )

    service.invoke_method = _fake_invoke_method  # type: ignore[method-assign]

    result = await service.list_apps(
        runtime=runtime,
        jsonrpc_url="https://example.com/jsonrpc",
        method_name="codex.discovery.apps.list",
        meta={"capability_area": "upstream_discovery"},
    )

    assert result.success is True
    assert result.result == {
        "items": [
            {
                "id": "demo-app",
                "name": "Demo App",
                "description": "Launch demos.",
                "isAccessible": True,
                "isEnabled": True,
                "installUrl": "https://example.com/install",
                "mentionPath": "app://demo-app",
                "branding": {"icon": "spark"},
                "labels": [{"name": "beta"}],
                "codex": {"raw": {"id": "demo-app"}},
            }
        ],
        "nextCursor": "cursor-2",
    }


@pytest.mark.asyncio
async def test_list_plugins_normalizes_marketplaces() -> None:
    service = UpstreamDiscoveryService(_FakeSupport())
    runtime = object()

    async def _fake_invoke_method(**kwargs):
        assert kwargs["method_name"] == "codex.discovery.plugins.list"
        return ExtensionCallResult(
            success=True,
            result={
                "items": [
                    {
                        "marketplace_name": "test",
                        "marketplace_path": "/workspace/.codex/plugins/marketplace.json",
                        "interface": {"transport": "mcp"},
                        "plugins": [
                            {
                                "name": "planner",
                                "description": "Coordinates work.",
                                "enabled": True,
                                "mention_path": "plugin://planner@test",
                                "codex": {"raw": {"name": "planner"}},
                            }
                        ],
                        "codex": {"raw": {"name": "test"}},
                    }
                ],
                "featuredPluginIds": ["test:planner"],
                "marketplaceLoadErrors": [{"path": "broken"}],
                "remoteSyncError": "timeout",
            },
            meta=kwargs["meta"],
        )

    service.invoke_method = _fake_invoke_method  # type: ignore[method-assign]

    result = await service.list_plugins(
        runtime=runtime,
        jsonrpc_url="https://example.com/jsonrpc",
        method_name="codex.discovery.plugins.list",
        meta={"capability_area": "upstream_discovery"},
    )

    assert result.success is True
    assert result.result == {
        "items": [
            {
                "marketplaceName": "test",
                "marketplacePath": "/workspace/.codex/plugins/marketplace.json",
                "interface": {"transport": "mcp"},
                "plugins": [
                    {
                        "name": "planner",
                        "description": "Coordinates work.",
                        "enabled": True,
                        "interface": None,
                        "mentionPath": "plugin://planner@test",
                        "codex": {"raw": {"name": "planner"}},
                    }
                ],
                "codex": {"raw": {"name": "test"}},
            }
        ],
        "featuredPluginIds": ["test:planner"],
        "marketplaceLoadErrors": [{"path": "broken"}],
        "remoteSyncError": "timeout",
    }


@pytest.mark.asyncio
async def test_read_plugin_normalizes_item_payload() -> None:
    service = UpstreamDiscoveryService(_FakeSupport())
    runtime = object()

    async def _fake_invoke_method(**kwargs):
        assert kwargs["params"] == {
            "marketplacePath": "/workspace/.codex/plugins/marketplace.json",
            "pluginName": "planner",
        }
        return ExtensionCallResult(
            success=True,
            result={
                "item": {
                    "name": "planner",
                    "marketplace_name": "test",
                    "marketplace_path": "/workspace/.codex/plugins/marketplace.json",
                    "mention_path": "plugin://planner@test",
                    "summary": ["Use for planning"],
                    "skills": [{"name": "planning"}],
                    "apps": [{"id": "demo-app"}],
                    "mcp_servers": ["planner-server"],
                    "interface": {"transport": "mcp"},
                    "codex": {"raw": {"name": "planner"}},
                }
            },
            meta=kwargs["meta"],
        )

    service.invoke_method = _fake_invoke_method  # type: ignore[method-assign]

    result = await service.read_plugin(
        runtime=runtime,
        jsonrpc_url="https://example.com/jsonrpc",
        method_name="codex.discovery.plugins.read",
        marketplace_path="/workspace/.codex/plugins/marketplace.json",
        plugin_name="planner",
        meta={"capability_area": "upstream_discovery"},
    )

    assert result.success is True
    assert result.result == {
        "item": {
            "name": "planner",
            "marketplaceName": "test",
            "marketplacePath": "/workspace/.codex/plugins/marketplace.json",
            "mentionPath": "plugin://planner@test",
            "summary": ["Use for planning"],
            "skills": [{"name": "planning"}],
            "apps": [{"id": "demo-app"}],
            "mcpServers": ["planner-server"],
            "interface": {"transport": "mcp"},
            "codex": {"raw": {"name": "planner"}},
        }
    }


@pytest.mark.asyncio
async def test_list_skills_returns_payload_error_for_invalid_items() -> None:
    service = UpstreamDiscoveryService(_FakeSupport())
    runtime = object()

    async def _fake_invoke_method(**kwargs):
        return ExtensionCallResult(
            success=True,
            result={"items": ["not-an-object"]},
            meta=kwargs["meta"],
        )

    service.invoke_method = _fake_invoke_method  # type: ignore[method-assign]

    result = await service.list_skills(
        runtime=runtime,
        jsonrpc_url="https://example.com/jsonrpc",
        method_name="codex.discovery.skills.list",
        meta={"capability_area": "upstream_discovery"},
    )

    assert result.success is False
    assert result.error_code == "upstream_payload_error"
    assert result.source == "upstream_discovery"
