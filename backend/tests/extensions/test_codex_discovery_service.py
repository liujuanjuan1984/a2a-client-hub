from __future__ import annotations

import pytest

from app.integrations.a2a_extensions.codex_discovery_service import (
    CodexDiscoveryService,
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
async def test_list_items_normalizes_items_and_cursor() -> None:
    service = CodexDiscoveryService(_FakeSupport())
    runtime = object()

    async def _fake_invoke_method(**kwargs):
        assert kwargs["method_name"] == "codex.discovery.skills.list"
        return ExtensionCallResult(
            success=True,
            result={
                "skills": [
                    {
                        "id": "skill-1",
                        "title": "Planning",
                        "summary": "Summarize plans.",
                        "tags": ["analysis", "planning"],
                        "metadata": {"source": "codex"},
                    }
                ],
                "nextCursor": "cursor-2",
            },
            meta=kwargs["meta"],
        )

    service.invoke_method = _fake_invoke_method  # type: ignore[method-assign]

    result = await service.list_items(
        runtime=runtime,
        jsonrpc_url="https://example.com/jsonrpc",
        method_name="codex.discovery.skills.list",
        kind="skill",
        list_key="skills",
        meta={"capability_area": "codex_discovery"},
    )

    assert result.success is True
    assert result.result == {
        "items": [
            {
                "id": "skill-1",
                "kind": "skill",
                "name": None,
                "title": "Planning",
                "summary": "Summarize plans.",
                "description": None,
                "tags": ["analysis", "planning"],
                "metadata": {"source": "codex"},
            }
        ],
        "nextCursor": "cursor-2",
    }


@pytest.mark.asyncio
async def test_list_items_returns_payload_error_for_invalid_items() -> None:
    service = CodexDiscoveryService(_FakeSupport())
    runtime = object()

    async def _fake_invoke_method(**kwargs):
        return ExtensionCallResult(
            success=True,
            result={"skills": ["not-an-object"]},
            meta=kwargs["meta"],
        )

    service.invoke_method = _fake_invoke_method  # type: ignore[method-assign]

    result = await service.list_items(
        runtime=runtime,
        jsonrpc_url="https://example.com/jsonrpc",
        method_name="codex.discovery.skills.list",
        kind="skill",
        list_key="skills",
        meta={"capability_area": "codex_discovery"},
    )

    assert result.success is False
    assert result.error_code == "upstream_payload_error"
    assert result.source == "codex_discovery"


@pytest.mark.asyncio
async def test_read_plugin_normalizes_plugin_payload() -> None:
    service = CodexDiscoveryService(_FakeSupport())
    runtime = object()

    async def _fake_invoke_method(**kwargs):
        assert kwargs["params"] == {"id": "planner"}
        return ExtensionCallResult(
            success=True,
            result={
                "plugin": {
                    "id": "planner",
                    "name": "planner",
                    "title": "Planner",
                    "description": "Coordinates work.",
                    "content": {"readme": "Use for planning"},
                    "metadata": {"version": "1.0"},
                }
            },
            meta=kwargs["meta"],
        )

    service.invoke_method = _fake_invoke_method  # type: ignore[method-assign]

    result = await service.read_plugin(
        runtime=runtime,
        jsonrpc_url="https://example.com/jsonrpc",
        method_name="codex.discovery.plugins.read",
        plugin_id="planner",
        meta={"capability_area": "codex_discovery"},
    )

    assert result.success is True
    assert result.result == {
        "plugin": {
            "id": "planner",
            "kind": "plugin",
            "name": "planner",
            "title": "Planner",
            "summary": None,
            "description": "Coordinates work.",
            "tags": [],
            "metadata": {"version": "1.0"},
            "content": {"readme": "Use for planning"},
        }
    }
