from __future__ import annotations

import json
from typing import Any, Dict

import httpx
import pytest

from app.integrations.a2a_extensions.jsonrpc import JsonRpcClient


@pytest.mark.asyncio
async def test_jsonrpc_client_builds_request_and_parses_result() -> None:
    captured: Dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        body = json.loads(request.content.decode("utf-8"))
        captured["body"] = body
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": body.get("id"), "result": {"items": []}},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        transport=transport, base_url="https://example.com"
    ) as http:
        client = JsonRpcClient(http)
        resp = await client.call(
            url="https://example.com/jsonrpc",
            method="opencode.sessions.list",
            params={"page": 1, "size": 10},
            headers={"Authorization": "Bearer secret"},
            timeout_seconds=5.0,
        )

    assert resp.ok is True
    assert resp.result == {"items": []}
    assert captured["method"] == "POST"
    assert captured["url"] == "https://example.com/jsonrpc"
    assert captured["body"]["jsonrpc"] == "2.0"
    assert captured["body"]["method"] == "opencode.sessions.list"
    assert captured["body"]["params"] == {"page": 1, "size": 10}


@pytest.mark.asyncio
async def test_jsonrpc_client_parses_error_object() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body.get("id"),
                "error": {"code": -32001, "message": "not found"},
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = JsonRpcClient(http)
        resp = await client.call(
            url="https://example.com/jsonrpc",
            method="opencode.sessions.messages.list",
            params={"session_id": "s", "page": 1, "size": 10},
            headers={},
            timeout_seconds=5.0,
        )

    assert resp.ok is False
    assert resp.error == {"code": -32001, "message": "not found"}


@pytest.mark.asyncio
async def test_jsonrpc_client_rejects_id_mismatch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": "wrong", "result": {"items": []}},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = JsonRpcClient(http)
        with pytest.raises(ValueError, match="id mismatch"):
            await client.call(
                url="https://example.com/jsonrpc",
                method="m",
                params={},
                headers={},
                timeout_seconds=5.0,
            )


@pytest.mark.asyncio
async def test_jsonrpc_client_rejects_non_2_0() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={"jsonrpc": "1.0", "id": body.get("id"), "result": {"items": []}},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = JsonRpcClient(http)
        with pytest.raises(ValueError, match="jsonrpc must be '2.0'"):
            await client.call(
                url="https://example.com/jsonrpc",
                method="m",
                params={},
                headers={},
                timeout_seconds=5.0,
            )
