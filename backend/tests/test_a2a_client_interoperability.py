"""Interoperability matrix tests for A2A binding and dialect selection."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from a2a.types import TransportProtocol

from app.integrations.a2a_client import client as client_module
from app.integrations.a2a_client.adapters import sdk as sdk_module
from app.integrations.a2a_client.adapters.sdk import (
    SDKA2AAdapter,
    SDKA2AAdapterRetiredError,
)
from app.integrations.a2a_client.client import A2AClient, ClientCacheEntry
from app.integrations.a2a_client.errors import (
    A2AAgentUnavailableError,
    A2AOutboundNotAllowedError,
    A2APeerProtocolError,
)
from app.utils.outbound_url import OutboundURLNotAllowedError


class _FakeResolver:
    base_url = "http://example-agent.internal:24020"
    agent_card_path = ".well-known/agent-card.json"

    def __init__(self, card_payload: SimpleNamespace) -> None:
        self._card_payload = card_payload

    async def get_agent_card(self, **_kwargs):
        return self._card_payload


def _build_card(**overrides: object) -> SimpleNamespace:
    payload = {
        "name": "Gateway",
        "preferred_transport": "JSONRPC",
        "url": "http://example-agent.internal:24020/jsonrpc",
        "additional_interfaces": [],
        "capabilities": SimpleNamespace(streaming=False),
        "protocol_version": "1.0",
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


@pytest.fixture(autouse=True)
def clear_dialect_cache() -> None:
    client_module.global_dialect_cache._entries.clear()


@pytest.mark.asyncio
async def test_get_preferred_dialects_prefers_cached_jsonrpc_variant() -> None:
    descriptor = client_module.build_peer_descriptor(
        agent_url="http://example-agent.internal:24020",
        card=_build_card(),
        selected_transport="JSONRPC",
        selected_url="http://example-agent.internal:24020/jsonrpc",
    )
    client_module.global_dialect_cache.set(
        agent_url=descriptor.agent_url,
        card_fingerprint=descriptor.card_fingerprint,
        dialect=client_module.JSONRPC_PASCAL_DIALECT,
    )

    a2a_client = A2AClient("http://example-agent.internal:24020")

    dialects = await a2a_client._get_preferred_dialects(descriptor)

    assert dialects == [
        client_module.JSONRPC_PASCAL_DIALECT,
        client_module.JSONRPC_SLASH_DIALECT,
    ]


@pytest.mark.asyncio
async def test_get_preferred_dialects_ignores_cache_for_changed_card_fingerprint() -> (
    None
):
    cached_descriptor = client_module.build_peer_descriptor(
        agent_url="http://example-agent.internal:24020",
        card=_build_card(),
        selected_transport="JSONRPC",
        selected_url="http://example-agent.internal:24020/jsonrpc",
    )
    refreshed_descriptor = client_module.build_peer_descriptor(
        agent_url="http://example-agent.internal:24020",
        card=_build_card(
            additional_interfaces=[
                SimpleNamespace(
                    transport="JSONRPC",
                    url="http://example-agent.internal:24020/jsonrpc-v2",
                )
            ]
        ),
        selected_transport="JSONRPC",
        selected_url="http://example-agent.internal:24020/jsonrpc-v2",
    )
    client_module.global_dialect_cache.set(
        agent_url=cached_descriptor.agent_url,
        card_fingerprint=cached_descriptor.card_fingerprint,
        dialect=client_module.JSONRPC_PASCAL_DIALECT,
    )

    a2a_client = A2AClient("http://example-agent.internal:24020")

    dialects = await a2a_client._get_preferred_dialects(refreshed_descriptor)

    assert dialects == [
        client_module.JSONRPC_SLASH_DIALECT,
        client_module.JSONRPC_PASCAL_DIALECT,
    ]


@pytest.mark.asyncio
async def test_get_preferred_dialects_uses_sdk_for_http_json() -> None:
    descriptor = client_module.build_peer_descriptor(
        agent_url="http://example-agent.internal:24020",
        card=_build_card(
            preferred_transport="HTTP+JSON",
            url="http://example-agent.internal:24020/http-json",
        ),
        selected_transport="HTTP+JSON",
        selected_url="http://example-agent.internal:24020/http-json",
    )
    a2a_client = A2AClient("http://example-agent.internal:24020")

    dialects = await a2a_client._get_preferred_dialects(descriptor)

    assert dialects == [client_module.SDK_DIALECT]


@pytest.mark.asyncio
async def test_get_agent_card_ignores_non_selected_non_http_interfaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    card = _build_card(
        preferred_transport="HTTP+JSON",
        url="http://example-agent.internal:24020/a2a/external_gateway",
        additional_interfaces=[
            SimpleNamespace(
                transport="JSONRPC",
                url="http://example-agent.internal:24020/a2a/external_gateway/",
            ),
            SimpleNamespace(
                transport="GRPC",
                url="grpc://example-agent.internal:8090",
            ),
        ],
    )
    validate_calls: list[str] = []

    def fake_validate_outbound_http_url(
        url: str,
        *,
        allowed_hosts,
        purpose: str = "outbound HTTP request",
    ) -> str:
        validate_calls.append(url)
        if url.startswith("grpc://"):
            raise OutboundURLNotAllowedError(
                f"{purpose}: URL must be http(s)",
                code="invalid_scheme",
            )
        return url

    monkeypatch.setattr(
        client_module,
        "validate_outbound_http_url",
        fake_validate_outbound_http_url,
    )
    monkeypatch.setattr(
        client_module.a2a_proxy_service,
        "get_effective_allowed_hosts_sync",
        lambda: ["example-agent.internal:24020", "example-agent.internal:8090"],
    )

    a2a_client = A2AClient("http://example-agent.internal:24020")
    a2a_client._get_http_client = AsyncMock(return_value=Mock())
    a2a_client._build_card_resolver = Mock(return_value=_FakeResolver(card))

    fetched = await a2a_client.get_agent_card()

    assert fetched is card
    assert all(not value.startswith("grpc://") for value in validate_calls)


@pytest.mark.asyncio
async def test_get_agent_card_raises_when_no_compatible_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    card = _build_card(
        preferred_transport="GRPC",
        url="grpc://example-agent.internal:8090",
        additional_interfaces=[],
    )
    validate_calls: list[str] = []

    def fake_validate_outbound_http_url(
        url: str,
        *,
        allowed_hosts,
        purpose: str = "outbound HTTP request",
    ) -> str:
        validate_calls.append(url)
        return url

    monkeypatch.setattr(
        client_module,
        "validate_outbound_http_url",
        fake_validate_outbound_http_url,
    )
    monkeypatch.setattr(
        client_module.a2a_proxy_service,
        "get_effective_allowed_hosts_sync",
        lambda: ["example-agent.internal:24020", "example-agent.internal:8090"],
    )

    a2a_client = A2AClient("http://example-agent.internal:24020")
    a2a_client._get_http_client = AsyncMock(return_value=Mock())
    a2a_client._build_card_resolver = Mock(return_value=_FakeResolver(card))

    with pytest.raises(A2AAgentUnavailableError, match="no compatible transports"):
        await a2a_client.get_agent_card()

    assert validate_calls == ["http://example-agent.internal:24020"]


@pytest.mark.asyncio
async def test_get_agent_card_honors_client_preference_transport_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    card = _build_card(
        preferred_transport="HTTP+JSON",
        url="http://example-agent.internal:24020/http-json",
        additional_interfaces=[
            SimpleNamespace(
                transport="JSONRPC",
                url="http://example-agent.internal:24020/jsonrpc",
            )
        ],
    )
    validate_calls: list[str] = []

    def fake_validate_outbound_http_url(
        url: str,
        *,
        allowed_hosts,
        purpose: str = "outbound HTTP request",
    ) -> str:
        validate_calls.append(url)
        return url

    monkeypatch.setattr(
        client_module,
        "validate_outbound_http_url",
        fake_validate_outbound_http_url,
    )
    monkeypatch.setattr(
        client_module.a2a_proxy_service,
        "get_effective_allowed_hosts_sync",
        lambda: ["example-agent.internal:24020"],
    )

    a2a_client = A2AClient(
        "http://example-agent.internal:24020",
        use_client_preference=True,
        supported_transports=["JSONRPC", "HTTP+JSON"],
    )
    a2a_client._get_http_client = AsyncMock(return_value=Mock())
    a2a_client._build_card_resolver = Mock(return_value=_FakeResolver(card))

    fetched = await a2a_client.get_agent_card()

    assert fetched is card
    assert validate_calls == [
        "http://example-agent.internal:24020",
        "http://example-agent.internal:24020/jsonrpc",
    ]


def test_supported_transports_is_copied_on_init() -> None:
    supported_transports = ["JSONRPC"]
    a2a_client = A2AClient(
        "http://example-agent.internal:24020",
        use_client_preference=True,
        supported_transports=supported_transports,
    )

    supported_transports.insert(0, "HTTP+JSON")
    card = _build_card(
        preferred_transport="HTTP+JSON",
        url="http://example-agent.internal:24020/http-json",
        additional_interfaces=[
            SimpleNamespace(
                transport="JSONRPC",
                url="http://example-agent.internal:24020/jsonrpc",
            )
        ],
    )

    selected_transport, selected_url, _ = (
        a2a_client._resolve_negotiated_transport_target(card)
    )

    assert selected_transport == "JSONRPC"
    assert selected_url == "http://example-agent.internal:24020/jsonrpc"


@pytest.mark.asyncio
async def test_get_agent_card_blocks_selected_interface_not_in_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    card = _build_card(
        url="http://blocked-agent.internal:24020/jsonrpc",
        additional_interfaces=[
            SimpleNamespace(
                transport="HTTP+JSON",
                url="http://example-agent.internal:24020/http-json",
            )
        ],
    )
    monkeypatch.setattr(
        client_module.a2a_proxy_service,
        "get_effective_allowed_hosts_sync",
        lambda: ["example-agent.internal:24020"],
    )

    a2a_client = A2AClient("http://example-agent.internal:24020")
    a2a_client._get_http_client = AsyncMock(return_value=Mock())
    a2a_client._build_card_resolver = Mock(return_value=_FakeResolver(card))

    with pytest.raises(A2AOutboundNotAllowedError):
        await a2a_client.get_agent_card()


@pytest.mark.asyncio
async def test_get_agent_card_uses_sdk_exact_transport_matching_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    card = _build_card(additional_interfaces=[])
    validate_calls: list[str] = []

    def fake_validate_outbound_http_url(
        url: str,
        *,
        allowed_hosts,
        purpose: str = "outbound HTTP request",
    ) -> str:
        validate_calls.append(url)
        return url

    monkeypatch.setattr(
        client_module,
        "validate_outbound_http_url",
        fake_validate_outbound_http_url,
    )
    monkeypatch.setattr(
        client_module.a2a_proxy_service,
        "get_effective_allowed_hosts_sync",
        lambda: ["example-agent.internal:24020"],
    )

    a2a_client = A2AClient(
        "http://example-agent.internal:24020",
        supported_transports=[" jsonrpc "],
    )
    a2a_client._get_http_client = AsyncMock(return_value=Mock())
    a2a_client._build_card_resolver = Mock(return_value=_FakeResolver(card))

    with pytest.raises(A2AAgentUnavailableError, match="no compatible transports"):
        await a2a_client.get_agent_card()

    assert validate_calls == ["http://example-agent.internal:24020"]


@pytest.mark.asyncio
async def test_call_agent_falls_back_to_pascal_jsonrpc_on_method_not_found() -> None:
    card = _build_card()
    descriptor = client_module.build_peer_descriptor(
        agent_url="http://example-agent.internal:24020",
        card=card,
        selected_transport="JSONRPC",
        selected_url="http://example-agent.internal:24020/jsonrpc",
    )

    class SlashAdapter:
        async def send_message(self, _request):
            raise A2APeerProtocolError(
                "Unknown method: message/send",
                error_code="method_not_found",
                rpc_code=-32601,
            )

    class PascalAdapter:
        async def send_message(self, _request):
            return {"parts": [{"text": "pascal-result"}]}

    a2a_client = A2AClient("http://example-agent.internal:24020")
    a2a_client._peer_descriptor = descriptor
    a2a_client._get_adapter = AsyncMock(side_effect=[SlashAdapter(), PascalAdapter()])
    a2a_client._discard_adapter = AsyncMock()

    result = await a2a_client.call_agent("hello")

    assert result["success"] is True
    assert result["content"] == "pascal-result"
    a2a_client._discard_adapter.assert_awaited_once()
    assert a2a_client._discard_adapter.await_args.args == (
        client_module.JSONRPC_SLASH_DIALECT,
    )


@pytest.mark.asyncio
async def test_call_agent_does_not_fallback_for_non_method_not_found_jsonrpc_error() -> (
    None
):
    card = _build_card()
    descriptor = client_module.build_peer_descriptor(
        agent_url="http://example-agent.internal:24020",
        card=card,
        selected_transport="JSONRPC",
        selected_url="http://example-agent.internal:24020/jsonrpc",
    )

    class SlashAdapter:
        async def send_message(self, _request):
            raise A2APeerProtocolError(
                "Permission denied",
                error_code="forbidden",
                rpc_code=-32001,
            )

    a2a_client = A2AClient("http://example-agent.internal:24020")
    a2a_client._peer_descriptor = descriptor
    a2a_client._get_adapter = AsyncMock(return_value=SlashAdapter())
    a2a_client._discard_adapter = AsyncMock()

    result = await a2a_client.call_agent("hello")

    assert result["success"] is False
    assert result["error"] == "Permission denied"
    a2a_client._get_adapter.assert_awaited_once_with(
        client_module.JSONRPC_SLASH_DIALECT
    )
    a2a_client._discard_adapter.assert_not_awaited()


@pytest.mark.asyncio
async def test_call_agent_pascal_fallback_includes_message_id_for_http_json_preferred_peer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    card = _build_card(
        preferred_transport="HTTP+JSON",
        url="http://example-agent.internal:24020/v1",
        additional_interfaces=[
            SimpleNamespace(
                transport="JSONRPC",
                url="http://example-agent.internal:24020/jsonrpc",
            )
        ],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": captured["body"]["id"],
                "result": {"parts": [{"text": "pascal-result"}]},
            },
        )

    def fake_validate_outbound_http_url(
        url: str,
        *,
        allowed_hosts,
        purpose: str = "outbound HTTP request",
    ) -> str:
        _ = allowed_hosts, purpose
        return url

    class FakeSlashAdapter:
        def __init__(self, *_args, **_kwargs) -> None:
            return None

        async def send_message(self, _request):
            raise A2APeerProtocolError(
                "Unknown method: message/send",
                error_code="method_not_found",
                rpc_code=-32601,
            )

        async def retire(self) -> None:
            return None

        async def close(self) -> None:
            return None

    monkeypatch.setattr(
        client_module,
        "validate_outbound_http_url",
        fake_validate_outbound_http_url,
    )
    monkeypatch.setattr(
        client_module.a2a_proxy_service,
        "get_effective_allowed_hosts_sync",
        lambda: ["example-agent.internal:24020"],
    )
    monkeypatch.setattr(client_module, "JsonRpcSlashAdapter", FakeSlashAdapter)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        a2a_client = A2AClient(
            "http://example-agent.internal:24020",
            use_client_preference=True,
        )
        a2a_client._get_http_client = AsyncMock(return_value=http_client)
        a2a_client._build_card_resolver = Mock(return_value=_FakeResolver(card))

        result = await a2a_client.call_agent(
            "hello",
            context_id="ctx-1",
            metadata={"trace_id": "trace-1"},
        )

    assert result["success"] is True
    assert result["content"] == "pascal-result"
    assert a2a_client._peer_descriptor is not None
    assert a2a_client._peer_descriptor.selected_transport == "JSONRPC"
    assert a2a_client._peer_descriptor.selected_url == (
        "http://example-agent.internal:24020/jsonrpc"
    )
    assert captured["method"] == "POST"
    assert captured["url"] == "http://example-agent.internal:24020/jsonrpc"
    assert captured["body"]["method"] == "SendMessage"
    message = captured["body"]["params"]["message"]
    assert isinstance(message["messageId"], str)
    assert message["messageId"]
    assert message["contextId"] == "ctx-1"
    assert message["metadata"] == {"trace_id": "trace-1"}


@pytest.mark.asyncio
async def test_jsonrpc_slash_stream_message_maps_application_json_method_not_found_without_replaying() -> (
    None
):
    captured_requests: list[dict[str, object]] = []
    descriptor = SimpleNamespace(
        selected_transport="JSONRPC",
        selected_url="http://example-agent.internal:24020/jsonrpc",
        supports_streaming=True,
        card=Mock(),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(
            {
                "method": request.method,
                "url": str(request.url),
                "body": json.loads(request.content.decode("utf-8")),
            }
        )
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": captured_requests[-1]["body"]["id"],
                "error": {
                    "code": -32601,
                    "message": "Unknown method: message/stream",
                },
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        adapter = client_module.JsonRpcSlashAdapter(
            descriptor,
            http_client=http_client,
        )

        with pytest.raises(
            A2APeerProtocolError,
            match="Unknown method: message/stream",
        ) as exc_info:
            async for _payload in adapter.stream_message(
                client_module.A2AMessageRequest(
                    query="hello",
                    context_id="ctx-1",
                )
            ):
                pass

    assert exc_info.value.error_code == "method_not_found"
    assert exc_info.value.code == -32601
    assert len(captured_requests) == 1
    assert captured_requests[0]["body"]["method"] == "message/stream"


@pytest.mark.asyncio
async def test_stream_agent_falls_back_to_pascal_jsonrpc_streaming_for_http_json_preferred_peer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_requests: list[dict[str, object]] = []
    card = _build_card(
        preferred_transport="HTTP+JSON",
        url="http://example-agent.internal:24020/v1",
        additional_interfaces=[
            SimpleNamespace(
                transport="JSONRPC",
                url="http://example-agent.internal:24020/jsonrpc",
            )
        ],
        capabilities=SimpleNamespace(streaming=True),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        captured_requests.append(
            {
                "method": request.method,
                "url": str(request.url),
                "body": body,
            }
        )
        if body["method"] == "message/stream":
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "error": {
                        "code": -32601,
                        "message": "Unknown method: message/stream",
                    },
                },
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=(
                "event: TaskArtifactUpdateEvent\n"
                'data: {"taskId":"task-1","contextId":"ctx-1","artifact":{"parts":[{"type":"text","text":"hello"}]}}\n\n'
                "event: TaskStatusUpdateEvent\n"
                'data: {"taskId":"task-1","contextId":"ctx-1","status":{"state":"completed"}}\n\n'
            ),
        )

    def fake_validate_outbound_http_url(
        url: str,
        *,
        allowed_hosts,
        purpose: str = "outbound HTTP request",
    ) -> str:
        _ = allowed_hosts, purpose
        return url

    monkeypatch.setattr(
        client_module,
        "validate_outbound_http_url",
        fake_validate_outbound_http_url,
    )
    monkeypatch.setattr(
        client_module.a2a_proxy_service,
        "get_effective_allowed_hosts_sync",
        lambda: ["example-agent.internal:24020"],
    )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        a2a_client = A2AClient(
            "http://example-agent.internal:24020",
            use_client_preference=True,
        )
        a2a_client._get_http_client = AsyncMock(return_value=http_client)
        a2a_client._build_card_resolver = Mock(return_value=_FakeResolver(card))

        events: list[dict[str, object]] = []
        async for event in a2a_client.stream_agent(
            "hello",
            context_id="ctx-1",
            metadata={"trace_id": "trace-1"},
        ):
            events.append(event)

    assert a2a_client._peer_descriptor is not None
    assert a2a_client._peer_descriptor.selected_transport == "JSONRPC"
    assert [item["body"]["method"] for item in captured_requests] == [
        "message/stream",
        "SendStreamingMessage",
    ]
    assert events[0]["kind"] == "artifact-update"
    assert events[1]["kind"] == "status-update"
    assert events[1]["final"] is True


@pytest.mark.asyncio
async def test_sdk_http_json_adapter_send_message_uses_sdk_transport_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeFactory:
        def __init__(self, *, config, consumers) -> None:
            captured["config"] = config
            captured["consumers"] = consumers

        def create(self, *_args, **_kwargs):
            class FakeClient:
                async def send_message(self, _message):
                    yield {"parts": [{"text": "ignored"}]}
                    yield {"parts": [{"text": "sdk-http-json"}]}

                async def close(self) -> None:
                    return None

            return FakeClient()

    monkeypatch.setattr(sdk_module, "ClientFactory", FakeFactory)

    adapter = SDKA2AAdapter(
        SimpleNamespace(card=Mock(), selected_transport="HTTP+JSON"),
        transport_http_client=AsyncMock(),
    )

    result = await adapter.send_message(
        client_module.A2AMessageRequest(query="hello", context_id="ctx-1")
    )

    assert result == {"parts": [{"text": "sdk-http-json"}]}
    assert captured["config"].streaming is False
    assert captured["config"].supported_transports == [
        TransportProtocol.jsonrpc,
        TransportProtocol.http_json,
    ]
    await adapter.close()


@pytest.mark.asyncio
async def test_sdk_http_json_adapter_stream_message_uses_streaming_client_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeFactory:
        def __init__(self, *, config, consumers) -> None:
            captured["config"] = config
            captured["consumers"] = consumers

        def create(self, *_args, **_kwargs):
            class FakeClient:
                async def send_message(self, _message):
                    yield {"event": "chunk-1"}
                    yield {"event": "chunk-2"}

                async def close(self) -> None:
                    return None

            return FakeClient()

    monkeypatch.setattr(sdk_module, "ClientFactory", FakeFactory)

    adapter = SDKA2AAdapter(
        SimpleNamespace(card=Mock(), selected_transport="HTTP+JSON"),
        transport_http_client=AsyncMock(),
    )

    events: list[dict[str, str]] = []
    async for payload in adapter.stream_message(
        client_module.A2AMessageRequest(query="hello", context_id="ctx-1")
    ):
        events.append(payload)

    assert events == [{"event": "chunk-1"}, {"event": "chunk-2"}]
    assert captured["config"].streaming is True
    assert captured["config"].supported_transports == [
        TransportProtocol.jsonrpc,
        TransportProtocol.http_json,
    ]
    await adapter.close()


@pytest.mark.asyncio
async def test_call_agent_retries_sdk_dialect_after_transport_reset() -> None:
    descriptor = client_module.build_peer_descriptor(
        agent_url="http://example-agent.internal:24020",
        card=_build_card(
            preferred_transport="HTTP+JSON",
            url="http://example-agent.internal:24020/v1",
        ),
        selected_transport="HTTP+JSON",
        selected_url="http://example-agent.internal:24020/v1",
    )

    class ResettingSdkAdapter(sdk_module.SDKA2AAdapter):
        def __init__(self) -> None:
            self.invalidate_borrowed_transport = AsyncMock(return_value=True)
            self.send_message = AsyncMock(
                side_effect=RuntimeError(
                    "Cannot send a request, as the client has been closed."
                )
            )
            self.retire = AsyncMock()

    class HealthySdkAdapter(sdk_module.SDKA2AAdapter):
        def __init__(self) -> None:
            self.send_message = AsyncMock(
                return_value={"parts": [{"text": "sdk-recovered"}]}
            )
            self.retire = AsyncMock()

    first_adapter = ResettingSdkAdapter()
    second_adapter = HealthySdkAdapter()

    a2a_client = A2AClient("http://example-agent.internal:24020")
    a2a_client._peer_descriptor = descriptor

    async def fake_get_adapter(dialect: str):
        adapter = first_adapter if fake_get_adapter.calls == 0 else second_adapter
        fake_get_adapter.calls += 1
        a2a_client._clients[dialect] = ClientCacheEntry(client=adapter)
        return adapter

    fake_get_adapter.calls = 0
    a2a_client._get_adapter = AsyncMock(side_effect=fake_get_adapter)

    result = await a2a_client.call_agent("hello")

    assert result["success"] is True
    assert result["content"] == "sdk-recovered"
    first_adapter.invalidate_borrowed_transport.assert_awaited_once()
    first_adapter.retire.assert_awaited_once()


@pytest.mark.asyncio
async def test_call_agent_retries_retired_sdk_adapter_without_transport_invalidation() -> (
    None
):
    descriptor = client_module.build_peer_descriptor(
        agent_url="http://example-agent.internal:24020",
        card=_build_card(
            preferred_transport="HTTP+JSON",
            url="http://example-agent.internal:24020/v1",
        ),
        selected_transport="HTTP+JSON",
        selected_url="http://example-agent.internal:24020/v1",
    )

    class RetiredSdkAdapter(sdk_module.SDKA2AAdapter):
        def __init__(self) -> None:
            self.invalidate_borrowed_transport = AsyncMock(return_value=True)
            self.send_message = AsyncMock(
                side_effect=SDKA2AAdapterRetiredError("retired")
            )
            self.retire = AsyncMock()

    class HealthySdkAdapter(sdk_module.SDKA2AAdapter):
        def __init__(self) -> None:
            self.send_message = AsyncMock(
                return_value={"parts": [{"text": "sdk-recovered"}]}
            )
            self.retire = AsyncMock()

    first_adapter = RetiredSdkAdapter()
    second_adapter = HealthySdkAdapter()

    a2a_client = A2AClient("http://example-agent.internal:24020")
    a2a_client._peer_descriptor = descriptor

    async def fake_get_adapter(dialect: str):
        adapter = first_adapter if fake_get_adapter.calls == 0 else second_adapter
        fake_get_adapter.calls += 1
        a2a_client._clients[dialect] = ClientCacheEntry(client=adapter)
        return adapter

    fake_get_adapter.calls = 0
    a2a_client._get_adapter = AsyncMock(side_effect=fake_get_adapter)

    result = await a2a_client.call_agent("hello")

    assert result["success"] is True
    assert result["content"] == "sdk-recovered"
    first_adapter.invalidate_borrowed_transport.assert_not_awaited()
    first_adapter.retire.assert_awaited_once()
