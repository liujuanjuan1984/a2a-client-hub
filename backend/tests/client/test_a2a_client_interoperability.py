"""Interoperability tests for the SDK-only A2A 1.0 client path."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call

import pytest
from a2a.utils.constants import TransportProtocol

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
    A2AUnsupportedOperationError,
)
from app.utils.outbound_url import OutboundURLNotAllowedError


class _FakeResolver:
    base_url = "http://example-agent.internal:24020"
    agent_card_path = ".well-known/agent-card.json"

    def __init__(self, card_payload: SimpleNamespace) -> None:
        self._card_payload = card_payload

    async def get_agent_card(self, **_kwargs):
        return self._card_payload


def _build_interface(
    protocol_binding: str,
    url: str,
    *,
    protocol_version: str | None = "1.0",
) -> SimpleNamespace:
    return SimpleNamespace(
        protocol_binding=protocol_binding,
        url=url,
        protocol_version=protocol_version,
    )


def _build_card(**overrides: object) -> SimpleNamespace:
    payload = {
        "name": "Gateway",
        "description": "SDK-only peer",
        "supported_interfaces": [
            _build_interface(
                "JSONRPC",
                "http://example-agent.internal:24020/jsonrpc",
            )
        ],
        "capabilities": SimpleNamespace(
            streaming=False,
            extended_agent_card=False,
        ),
        "version": "1.0",
        "default_input_modes": ["text/plain"],
        "default_output_modes": ["text/plain"],
        "skills": [],
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


@pytest.fixture(autouse=True)
def clear_dialect_cache() -> None:
    client_module.global_dialect_cache._entries.clear()


@pytest.mark.asyncio
async def test_get_preferred_dialects_always_uses_sdk_even_with_stale_cache() -> None:
    descriptor = client_module.build_peer_descriptor(
        agent_url="http://example-agent.internal:24020",
        card=_build_card(),
        selected_transport="JSONRPC",
        selected_url="http://example-agent.internal:24020/jsonrpc",
    )
    client_module.global_dialect_cache.set(
        agent_url=descriptor.agent_url,
        card_fingerprint=descriptor.card_fingerprint,
        dialect="jsonrpc_pascal",
    )

    a2a_client = A2AClient("http://example-agent.internal:24020")

    dialects = await a2a_client._get_preferred_dialects(descriptor)

    assert dialects == [client_module.SDK_DIALECT]


@pytest.mark.asyncio
async def test_get_agent_card_ignores_incompatible_non_http_interfaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    card = _build_card(
        supported_interfaces=[
            _build_interface(
                "HTTP+JSON",
                "http://example-agent.internal:24020/a2a/external_gateway",
            ),
            _build_interface(
                "JSONRPC",
                "http://example-agent.internal:24020/a2a/external_gateway/",
            ),
            _build_interface("GRPC", "grpc://example-agent.internal:8090"),
        ]
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
        supported_interfaces=[_build_interface("GRPC", "grpc://example-agent:8090")]
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
        supported_interfaces=[
            _build_interface(
                "HTTP+JSON",
                "http://example-agent.internal:24020/http-json",
            ),
            _build_interface(
                "JSONRPC",
                "http://example-agent.internal:24020/jsonrpc",
            ),
        ]
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
        supported_interfaces=[
            _build_interface(
                "HTTP+JSON",
                "http://example-agent.internal:24020/http-json",
            ),
            _build_interface(
                "JSONRPC",
                "http://example-agent.internal:24020/jsonrpc",
            ),
        ]
    )

    selected_transport, selected_url, _, _ = (
        a2a_client._resolve_negotiated_transport_target(card)
    )

    assert selected_transport == "JSONRPC"
    assert selected_url == "http://example-agent.internal:24020/jsonrpc"


@pytest.mark.asyncio
async def test_get_agent_card_blocks_selected_interface_not_in_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    card = _build_card(
        supported_interfaces=[
            _build_interface(
                "JSONRPC",
                "http://blocked-agent.internal:24020/jsonrpc",
            ),
            _build_interface(
                "HTTP+JSON",
                "http://example-agent.internal:24020/http-json",
            ),
        ]
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
async def test_get_agent_card_uses_exact_transport_matching_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    a2a_client._build_card_resolver = Mock(return_value=_FakeResolver(_build_card()))

    with pytest.raises(A2AAgentUnavailableError, match="no compatible transports"):
        await a2a_client.get_agent_card()

    assert validate_calls == ["http://example-agent.internal:24020"]


def test_build_card_resolver_uses_root_base_for_standard_http_extended_card_path() -> (
    None
):
    a2a_client = A2AClient("http://example-agent.internal:24020")

    resolver = a2a_client._build_card_resolver(
        Mock(),
        agent_card_path_override=client_module.AUTHENTICATED_EXTENDED_AGENT_CARD_HTTP_PATH,
    )

    assert resolver.base_url == "http://example-agent.internal:24020"
    assert resolver.agent_card_path == "v1/card"


def test_build_card_resolver_rebases_standard_http_extended_card_path_from_well_known_card_url() -> (
    None
):
    a2a_client = A2AClient(
        "http://example-agent.internal:24020/.well-known/agent-card.json"
    )

    resolver = a2a_client._build_card_resolver(
        Mock(),
        agent_card_path_override=client_module.AUTHENTICATED_EXTENDED_AGENT_CARD_HTTP_PATH,
    )

    assert resolver.base_url == "http://example-agent.internal:24020"
    assert resolver.agent_card_path == "v1/card"


@pytest.mark.asyncio
async def test_get_authenticated_extended_agent_card_prefers_sdk_route() -> None:
    public_card = _build_card(
        capabilities=SimpleNamespace(streaming=False, extended_agent_card=True)
    )
    extended_card = _build_card(
        name="Extended Gateway",
        capabilities=SimpleNamespace(streaming=False, extended_agent_card=True),
    )

    a2a_client = A2AClient("http://example-agent.internal:24020")
    a2a_client._agent_card = public_card
    a2a_client._peer_descriptor = SimpleNamespace(selected_transport="JSONRPC")
    a2a_client._get_authenticated_extended_agent_card_with_jsonrpc_fallback = AsyncMock(
        return_value=extended_card
    )
    a2a_client._fetch_card = AsyncMock()

    fetched = await a2a_client.get_authenticated_extended_agent_card()

    assert fetched is extended_card
    a2a_client._get_authenticated_extended_agent_card_with_jsonrpc_fallback.assert_awaited_once()
    a2a_client._fetch_card.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_authenticated_extended_agent_card_falls_back_to_standard_http() -> (
    None
):
    public_card = _build_card(
        capabilities=SimpleNamespace(streaming=False, extended_agent_card=True)
    )
    extended_card = _build_card(
        name="Extended Gateway",
        capabilities=SimpleNamespace(streaming=False, extended_agent_card=True),
    )

    a2a_client = A2AClient("http://example-agent.internal:24020")
    a2a_client._agent_card = public_card
    a2a_client._peer_descriptor = SimpleNamespace(selected_transport="JSONRPC")
    a2a_client._get_authenticated_extended_agent_card_with_jsonrpc_fallback = AsyncMock(
        side_effect=A2AUnsupportedOperationError("method not found")
    )
    a2a_client._fetch_card = AsyncMock(return_value=extended_card)

    fetched = await a2a_client.get_authenticated_extended_agent_card()

    assert fetched is extended_card
    assert a2a_client._fetch_card.await_args_list == [
        call(
            agent_card_path_override=client_module.AUTHENTICATED_EXTENDED_AGENT_CARD_HTTP_PATH,
            log_label="authenticated extended A2A agent card",
        )
    ]


@pytest.mark.asyncio
async def test_get_authenticated_extended_agent_card_requires_public_capability_flag() -> (
    None
):
    a2a_client = A2AClient("http://example-agent.internal:24020")
    a2a_client._agent_card = _build_card()

    with pytest.raises(
        A2AAgentUnavailableError,
        match="does not advertise an authenticated extended agent card",
    ):
        await a2a_client.get_authenticated_extended_agent_card()


@pytest.mark.asyncio
async def test_sdk_http_json_adapter_send_message_uses_sdk_transport_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeFactory:
        def __init__(self, *, config) -> None:
            captured["config"] = config

        def create(self, *_args, **_kwargs):
            class FakeClient:
                async def send_message(self, request):
                    captured["request"] = request
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
        client_module.A2AMessageRequest(
            query="hello",
            context_id="ctx-1",
            metadata={"trace_id": "trace-1"},
        )
    )

    assert result == {"parts": [{"text": "sdk-http-json"}]}
    assert captured["config"].streaming is False
    assert captured["config"].supported_protocol_bindings == [
        TransportProtocol.JSONRPC.value,
        TransportProtocol.HTTP_JSON.value,
    ]
    assert captured["request"].message.context_id == "ctx-1"
    assert list(captured["request"].configuration.accepted_output_modes) == [
        "text/plain"
    ]
    assert captured["request"].metadata["trace_id"] == "trace-1"
    await adapter.close()


@pytest.mark.asyncio
async def test_sdk_http_json_adapter_stream_message_downgrades_when_peer_disables_streaming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeFactory:
        def __init__(self, *, config) -> None:
            captured["config"] = config

        def create(self, *_args, **_kwargs):
            class FakeClient:
                async def send_message(self, _request):
                    yield {"event": "blocking-result"}

                async def close(self) -> None:
                    return None

            return FakeClient()

    monkeypatch.setattr(sdk_module, "ClientFactory", FakeFactory)

    adapter = SDKA2AAdapter(
        SimpleNamespace(
            card=Mock(),
            selected_transport="HTTP+JSON",
            supports_streaming=False,
        ),
        transport_http_client=AsyncMock(),
    )

    events: list[dict[str, str]] = []
    async for payload in adapter.stream_message(
        client_module.A2AMessageRequest(query="hello", context_id="ctx-1")
    ):
        events.append(payload)

    assert events == [{"event": "blocking-result"}]
    assert captured["config"].streaming is False
    await adapter.close()


@pytest.mark.asyncio
async def test_sdk_http_json_adapter_get_task_forwards_history_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeFactory:
        def __init__(self, *, config) -> None:
            captured["config"] = config

        def create(self, *_args, **_kwargs):
            class FakeClient:
                async def get_task(self, request):
                    captured["request"] = request
                    return {"id": request.id, "history_length": request.history_length}

                async def close(self) -> None:
                    return None

            return FakeClient()

    monkeypatch.setattr(sdk_module, "ClientFactory", FakeFactory)

    adapter = SDKA2AAdapter(
        SimpleNamespace(card=Mock(), selected_transport="HTTP+JSON"),
        transport_http_client=AsyncMock(),
    )

    result = await adapter.get_task(
        "task-1",
        history_length=7,
        metadata={"trace_id": "trace-1"},
    )

    assert result == {"id": "task-1", "history_length": 7}
    assert captured["request"].id == "task-1"
    assert captured["request"].history_length == 7
    await adapter.close()


@pytest.mark.asyncio
async def test_sdk_http_json_adapter_cancel_task_forwards_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeFactory:
        def __init__(self, *, config) -> None:
            captured["config"] = config

        def create(self, *_args, **_kwargs):
            class FakeClient:
                async def cancel_task(self, request):
                    captured["request"] = request
                    return {"id": request.id}

                async def close(self) -> None:
                    return None

            return FakeClient()

    monkeypatch.setattr(sdk_module, "ClientFactory", FakeFactory)

    adapter = SDKA2AAdapter(
        SimpleNamespace(card=Mock(), selected_transport="HTTP+JSON"),
        transport_http_client=AsyncMock(),
    )

    result = await adapter.cancel_task(
        "task-1",
        metadata={"trace_id": "trace-1"},
    )

    assert result == {"id": "task-1"}
    assert captured["request"].id == "task-1"
    assert captured["request"].metadata["trace_id"] == "trace-1"
    await adapter.close()


@pytest.mark.asyncio
async def test_sdk_http_json_adapter_stream_message_uses_streaming_client_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeFactory:
        def __init__(self, *, config) -> None:
            captured["config"] = config

        def create(self, *_args, **_kwargs):
            class FakeClient:
                async def send_message(self, _request):
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
    assert captured["config"].supported_protocol_bindings == [
        TransportProtocol.JSONRPC.value,
        TransportProtocol.HTTP_JSON.value,
    ]
    await adapter.close()


@pytest.mark.asyncio
async def test_call_agent_retries_sdk_dialect_after_transport_reset() -> None:
    descriptor = client_module.build_peer_descriptor(
        agent_url="http://example-agent.internal:24020",
        card=_build_card(
            supported_interfaces=[
                _build_interface(
                    "HTTP+JSON",
                    "http://example-agent.internal:24020/v1",
                )
            ]
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
            supported_interfaces=[
                _build_interface(
                    "HTTP+JSON",
                    "http://example-agent.internal:24020/v1",
                )
            ]
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
