"""Tests for A2A client lifecycle behaviors."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from a2a.client.errors import A2AClientHTTPError
from a2a.types import Message, Role, TextPart

from app.core import http_client as http_client_module
from app.integrations.a2a_client import client as client_module
from app.integrations.a2a_client import config as config_module
from app.integrations.a2a_client import gateway as gateway_module
from app.integrations.a2a_client import http_clients as shared_http_clients_module
from app.integrations.a2a_client import lifecycle as lifecycle_module
from app.integrations.a2a_client import registry as registry_module
from app.integrations.a2a_client.adapters import sdk as sdk_module
from app.integrations.a2a_client.adapters.sdk import SDKA2AAdapter
from app.integrations.a2a_client.client import A2AClient, ClientCacheEntry
from app.integrations.a2a_client.config import A2ASettings
from app.integrations.a2a_client.errors import A2AClientResetRequiredError
from app.integrations.a2a_client.http_clients import (
    SharedSDKTransportInvalidatedError,
    SharedSDKTransportLease,
)
from app.integrations.a2a_client.invoke_session import (
    AgentResolutionPolicy,
    InvokeSessionOwnership,
)


@pytest.mark.asyncio
async def test_a2a_client_close_releases_adapters_without_owned_http_client() -> None:
    a2a_client = A2AClient("http://example-agent.internal:24020")
    close_mock = AsyncMock()
    a2a_client._agent_card = Mock()
    a2a_client._clients["sdk"] = ClientCacheEntry(
        client=SimpleNamespace(close=close_mock)
    )

    await a2a_client.close()

    close_mock.assert_awaited_once()
    assert a2a_client._agent_card is None
    assert a2a_client._clients == {}


@pytest.mark.asyncio
async def test_a2a_client_close_releases_owned_http_client_resources() -> None:
    http_client = AsyncMock()
    transport_close = AsyncMock()
    a2a_client = A2AClient(
        "http://example-agent.internal:24020",
        owned_http_client=http_client,
    )
    a2a_client._agent_card = Mock()
    a2a_client._clients["sdk"] = ClientCacheEntry(
        client=SimpleNamespace(close=transport_close),
    )

    await a2a_client.close()

    transport_close.assert_awaited_once()
    http_client.aclose.assert_awaited_once()
    assert a2a_client._agent_card is None
    assert a2a_client._clients == {}


@pytest.mark.asyncio
async def test_a2a_client_does_not_close_injected_http_client_by_default() -> None:
    http_client = AsyncMock()
    a2a_client = A2AClient(
        "http://example-agent.internal:24020",
        borrowed_http_client=http_client,
    )

    await a2a_client.close()

    http_client.aclose.assert_not_awaited()


def test_a2a_client_rejects_multiple_http_client_dependency_modes() -> None:
    with pytest.raises(ValueError, match="Use only one"):
        A2AClient(
            "http://example-agent.internal:24020",
            borrowed_http_client=AsyncMock(),
            owned_http_client=AsyncMock(),
        )


def test_load_settings_defaults_maintenance_interval_to_idle_timeout_derivation() -> (
    None
):
    settings = config_module.load_settings(SimpleNamespace())

    assert settings.client_idle_timeout == 600.0
    assert settings.client_maintenance_interval == 0.0


def test_gateway_resolve_maintenance_interval_derives_from_idle_timeout() -> None:
    gateway = gateway_module.A2AGateway(
        A2ASettings(
            default_timeout=10.0,
            use_client_preference=False,
            client_idle_timeout=20.0,
            client_maintenance_interval=0.0,
        )
    )

    assert gateway._resolve_maintenance_interval() == 10.0


@pytest.mark.asyncio
async def test_get_global_http_client_recreates_closed_instance() -> None:
    await http_client_module.close_global_http_client()

    original = http_client_module.get_global_http_client()
    await original.aclose()

    recreated = http_client_module.get_global_http_client()

    assert recreated is not original
    assert recreated.is_closed is False

    await http_client_module.close_global_http_client()


@pytest.mark.asyncio
async def test_sdk_adapter_close_preserves_borrowed_http_client() -> None:
    shared_http_client = AsyncMock()
    shared_http_client.is_closed = False
    shared_http_client.aclose = AsyncMock()

    captured_config: dict[str, object] = {}

    class FakeFactory:
        def __init__(self, *, config, consumers) -> None:
            captured_config["config"] = config

        def create(self, *_args, **_kwargs):
            async def _close() -> None:
                await captured_config["config"].httpx_client.aclose()

            return SimpleNamespace(close=_close)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(sdk_module, "ClientFactory", FakeFactory)
    adapter = SDKA2AAdapter(
        SimpleNamespace(card=Mock()),
        transport_http_client=shared_http_client,
    )

    await adapter._get_client(streaming=False)

    await adapter.close()
    monkeypatch.undo()

    shared_http_client.aclose.assert_not_awaited()


@pytest.mark.asyncio
async def test_sdk_adapter_retire_drains_inflight_operations_before_closing() -> None:
    shared_http_client = AsyncMock()
    shared_http_client.is_closed = False

    operation_started = asyncio.Event()
    release_operation = asyncio.Event()
    closed = AsyncMock()

    class FakeFactory:
        def __init__(self, *, config, consumers) -> None:
            self._config = config

        def create(self, *_args, **_kwargs):
            class FakeClient:
                async def send_message(self, _message):
                    operation_started.set()
                    await release_operation.wait()
                    yield "done"

                async def close(self) -> None:
                    await closed()

            return FakeClient()

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(sdk_module, "ClientFactory", FakeFactory)

    adapter = SDKA2AAdapter(
        SimpleNamespace(card=Mock()),
        transport_http_client=shared_http_client,
    )

    task = asyncio.create_task(
        adapter.send_message(
            client_module.A2AMessageRequest(query="hello", context_id="ctx-1")
        )
    )
    await operation_started.wait()

    await adapter.retire()

    closed.assert_not_awaited()

    release_operation.set()
    assert await task == "done"

    closed.assert_awaited_once()
    monkeypatch.undo()


@pytest.mark.asyncio
async def test_get_adapter_uses_shared_sdk_http_client_for_borrowed_http_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    descriptor = SimpleNamespace()
    shared_http_client = AsyncMock()
    shared_lease = SharedSDKTransportLease(
        timeout_key=(10.0, 10.0, 10.0, 10.0),
        generation=1,
        client=AsyncMock(),
    )
    captured: dict[str, object] = {}

    class FakeSdkAdapter:
        def __init__(self, _descriptor, **kwargs) -> None:
            captured.update(kwargs)

    a2a_client = A2AClient("http://example-agent.internal:24020")
    a2a_client._get_peer_descriptor = AsyncMock(return_value=descriptor)
    a2a_client._get_http_client = AsyncMock(return_value=shared_http_client)

    monkeypatch.setattr(
        client_module,
        "borrow_shared_sdk_transport_http_client",
        Mock(return_value=shared_lease),
    )
    monkeypatch.setattr(client_module, "SDKA2AAdapter", FakeSdkAdapter)

    await a2a_client._get_adapter(client_module.SDK_DIALECT)

    assert captured["transport_http_client"] is shared_lease.client
    assert captured["shared_transport_lease"] is shared_lease


@pytest.mark.asyncio
async def test_get_adapter_recreates_stale_cached_sdk_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    descriptor = SimpleNamespace()
    shared_http_client = AsyncMock()

    class FakeSdkAdapter:
        def __init__(self, _descriptor, **kwargs) -> None:
            self.kwargs = kwargs
            self.retire = AsyncMock()
            self._stale = kwargs.get("shared_transport_lease") is not None

        def is_transport_stale(self) -> bool:
            return self._stale

    stale_adapter = FakeSdkAdapter(
        descriptor,
        transport_http_client=AsyncMock(),
        shared_transport_lease=SharedSDKTransportLease(
            timeout_key=(10.0, 10.0, 10.0, 10.0),
            generation=1,
            client=AsyncMock(),
        ),
    )

    fresh_lease = SharedSDKTransportLease(
        timeout_key=(10.0, 10.0, 10.0, 10.0),
        generation=2,
        client=AsyncMock(),
    )

    a2a_client = A2AClient("http://example-agent.internal:24020")
    a2a_client._get_peer_descriptor = AsyncMock(return_value=descriptor)
    a2a_client._get_http_client = AsyncMock(return_value=shared_http_client)
    a2a_client._clients[client_module.SDK_DIALECT] = ClientCacheEntry(
        client=stale_adapter
    )

    monkeypatch.setattr(
        client_module,
        "borrow_shared_sdk_transport_http_client",
        Mock(return_value=fresh_lease),
    )
    monkeypatch.setattr(client_module, "SDKA2AAdapter", FakeSdkAdapter)

    adapter = await a2a_client._get_adapter(client_module.SDK_DIALECT)

    stale_adapter.retire.assert_awaited_once()
    assert adapter is not stale_adapter
    assert adapter.kwargs["shared_transport_lease"] is fresh_lease


@pytest.mark.asyncio
async def test_shared_sdk_transport_http_client_reuses_timeout_bucket() -> None:
    await shared_http_clients_module.close_shared_sdk_transport_http_clients()

    original = shared_http_clients_module.borrow_shared_sdk_transport_http_client()
    reused = shared_http_clients_module.borrow_shared_sdk_transport_http_client()

    assert reused.client is original.client
    assert reused.generation == original.generation

    await shared_http_clients_module.close_shared_sdk_transport_http_clients()

    recreated = shared_http_clients_module.borrow_shared_sdk_transport_http_client()

    assert recreated.client is not original.client
    assert recreated.client.is_closed is False
    assert recreated.generation > original.generation

    await shared_http_clients_module.close_shared_sdk_transport_http_clients()


@pytest.mark.asyncio
async def test_invalidate_shared_sdk_transport_http_client_recreates_generation() -> (
    None
):
    await shared_http_clients_module.close_shared_sdk_transport_http_clients()

    original = shared_http_clients_module.borrow_shared_sdk_transport_http_client()
    invalidated = (
        await shared_http_clients_module.invalidate_shared_sdk_transport_http_client(
            original
        )
    )
    recreated = shared_http_clients_module.borrow_shared_sdk_transport_http_client()

    assert invalidated is True
    assert recreated.client is not original.client
    assert recreated.generation > original.generation

    await shared_http_clients_module.close_shared_sdk_transport_http_clients()


@pytest.mark.asyncio
async def test_invalidate_shared_sdk_transport_http_client_ignores_stale_generation() -> (
    None
):
    await shared_http_clients_module.close_shared_sdk_transport_http_clients()

    original = shared_http_clients_module.borrow_shared_sdk_transport_http_client()
    await shared_http_clients_module.invalidate_shared_sdk_transport_http_client(
        original
    )
    recreated = shared_http_clients_module.borrow_shared_sdk_transport_http_client()
    stale_result = (
        await shared_http_clients_module.invalidate_shared_sdk_transport_http_client(
            original
        )
    )

    assert stale_result is False
    assert recreated.client.is_closed is False

    await shared_http_clients_module.close_shared_sdk_transport_http_clients()


@pytest.mark.asyncio
async def test_invalidate_shared_sdk_transport_http_client_drains_inflight_usage() -> (
    None
):
    await shared_http_clients_module.close_shared_sdk_transport_http_clients()

    lease = shared_http_clients_module.borrow_shared_sdk_transport_http_client()
    acquired = (
        shared_http_clients_module.acquire_shared_sdk_transport_http_client_usage(lease)
    )
    invalidated = (
        await shared_http_clients_module.invalidate_shared_sdk_transport_http_client(
            lease
        )
    )

    assert acquired is True
    assert invalidated is True
    assert shared_http_clients_module.is_shared_sdk_transport_http_client_stale(lease)
    assert lease.client.is_closed is False

    await shared_http_clients_module.release_shared_sdk_transport_http_client_usage(
        lease
    )

    assert lease.client.is_closed is True

    await shared_http_clients_module.close_shared_sdk_transport_http_clients()


@pytest.mark.asyncio
async def test_shared_sdk_transport_usage_rejects_invalidated_lease() -> None:
    await shared_http_clients_module.close_shared_sdk_transport_http_clients()

    lease = shared_http_clients_module.borrow_shared_sdk_transport_http_client()
    await shared_http_clients_module.invalidate_shared_sdk_transport_http_client(lease)

    with pytest.raises(SharedSDKTransportInvalidatedError):
        async with shared_http_clients_module.use_shared_sdk_transport_http_client(
            lease
        ):
            pass

    await shared_http_clients_module.close_shared_sdk_transport_http_clients()


@pytest.mark.asyncio
async def test_a2a_client_lifecycle_snapshot_reports_shared_transport_state() -> None:
    await shared_http_clients_module.close_shared_sdk_transport_http_clients()

    a2a_client = A2AClient("http://example-agent.internal:24020")
    lease = shared_http_clients_module.borrow_shared_sdk_transport_http_client(
        timeout=a2a_client._timeout
    )
    a2a_client._active_requests = 1

    snapshot = a2a_client.get_lifecycle_snapshot()

    assert snapshot.busy is True
    assert snapshot.active_requests == 1
    assert snapshot.shared_transport is not None
    assert snapshot.shared_transport.current_generation == lease.generation
    assert snapshot.shared_transport.tracked_generations == 1

    await shared_http_clients_module.close_shared_sdk_transport_http_clients()


@pytest.mark.asyncio
async def test_gateway_cleanup_idle_clients_skips_busy_clients() -> None:
    gateway = gateway_module.A2AGateway(
        A2ASettings(
            default_timeout=10.0,
            use_client_preference=False,
            client_idle_timeout=1.0,
        )
    )
    busy_client = SimpleNamespace(
        is_busy=Mock(return_value=True),
        close=AsyncMock(),
        get_lifecycle_snapshot=Mock(
            return_value=lifecycle_module.A2AClientLifecycleSnapshot(
                active_requests=1,
                busy=True,
                cached_adapter_count=0,
                adapter_snapshots=(),
                shared_transport=None,
            )
        ),
    )
    cache_key = ("http://example-agent.internal:24020", ())
    gateway._client_registry.clients[cache_key] = registry_module.CachedClientEntry(
        client=busy_client,
        last_used=time.monotonic() - 30.0,
    )

    await gateway._cleanup_idle_clients()

    assert cache_key in gateway._client_registry.clients
    busy_client.close.assert_not_awaited()
    assert (
        gateway._client_registry.clients[cache_key].last_used > time.monotonic() - 2.0
    )


@pytest.mark.asyncio
async def test_gateway_get_client_does_not_run_cleanup_inline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = gateway_module.A2AGateway(
        A2ASettings(
            default_timeout=10.0,
            use_client_preference=False,
            client_idle_timeout=1.0,
            client_maintenance_interval=60.0,
        )
    )
    cleanup_mock = AsyncMock()
    monkeypatch.setattr(gateway, "_cleanup_idle_clients", cleanup_mock)

    resolved = SimpleNamespace(
        url="http://example-agent.internal:24020",
        headers={},
        name="TestAgent",
    )

    client = await asyncio.wait_for(gateway._get_client(resolved), timeout=0.1)

    assert isinstance(client, A2AClient)
    cleanup_mock.assert_not_awaited()

    await gateway.shutdown()


@pytest.mark.asyncio
async def test_gateway_fetch_agent_card_detail_uses_fresh_probe_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = gateway_module.A2AGateway(
        A2ASettings(
            default_timeout=10.0,
            use_client_preference=False,
            client_idle_timeout=1.0,
        )
    )
    fake_card = SimpleNamespace(name="Probe Card")
    fake_peer_descriptor = SimpleNamespace(selected_url="http://example-agent.internal")
    temporary_client = SimpleNamespace(
        get_agent_resolution=AsyncMock(return_value=(fake_card, fake_peer_descriptor)),
        close=AsyncMock(),
    )
    create_client_mock = Mock(return_value=temporary_client)
    monkeypatch.setattr(gateway, "_create_client", create_client_mock)

    resolved = SimpleNamespace(
        url="http://example-agent.internal:24020",
        headers={},
        name="TestAgent",
    )

    result = await gateway.fetch_agent_card_detail(
        resolved=resolved,
        raise_on_failure=True,
        policy=AgentResolutionPolicy.FRESH_PROBE,
        card_fetch_timeout=5.0,
    )

    assert result is fake_card
    create_client_mock.assert_called_once_with(resolved, card_fetch_timeout=5.0)
    temporary_client.get_agent_resolution.assert_awaited_once()
    temporary_client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_gateway_fetch_agent_card_detail_invalidates_shared_client_on_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = gateway_module.A2AGateway(
        A2ASettings(
            default_timeout=10.0,
            use_client_preference=False,
            client_idle_timeout=1.0,
        )
    )
    resolved = SimpleNamespace(
        url="http://example-agent.internal:24020",
        headers={},
        name="TestAgent",
    )
    shared_client = SimpleNamespace(
        get_agent_resolution=AsyncMock(
            side_effect=A2AClientResetRequiredError("reset required")
        )
    )
    get_client_mock = AsyncMock(return_value=shared_client)
    invalidate_mock = AsyncMock()
    monkeypatch.setattr(gateway, "_get_client", get_client_mock)
    monkeypatch.setattr(gateway, "_invalidate_client", invalidate_mock)

    result = await gateway.fetch_agent_card_detail(resolved=resolved)

    assert result is None
    get_client_mock.assert_awaited_once_with(resolved)
    invalidate_mock.assert_awaited_once_with(resolved)


@pytest.mark.asyncio
async def test_gateway_fetch_agent_card_detail_does_not_invalidate_fresh_probe_on_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = gateway_module.A2AGateway(
        A2ASettings(
            default_timeout=10.0,
            use_client_preference=False,
            client_idle_timeout=1.0,
        )
    )
    resolved = SimpleNamespace(
        url="http://example-agent.internal:24020",
        headers={},
        name="TestAgent",
    )
    temporary_client = SimpleNamespace(
        get_agent_resolution=AsyncMock(
            side_effect=A2AClientResetRequiredError("reset required")
        ),
        close=AsyncMock(),
    )
    invalidate_mock = AsyncMock()
    create_client_mock = Mock(return_value=temporary_client)
    monkeypatch.setattr(gateway, "_invalidate_client", invalidate_mock)
    monkeypatch.setattr(gateway, "_create_client", create_client_mock)

    result = await gateway.fetch_agent_card_detail(
        resolved=resolved,
        policy=AgentResolutionPolicy.FRESH_PROBE,
    )

    assert result is None
    temporary_client.get_agent_resolution.assert_awaited_once()
    temporary_client.close.assert_awaited_once()
    invalidate_mock.assert_not_awaited()
    create_client_mock.assert_called_once_with(resolved, card_fetch_timeout=None)


@pytest.mark.asyncio
async def test_gateway_open_invoke_session_reuses_shared_client_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = gateway_module.A2AGateway(
        A2ASettings(
            default_timeout=10.0,
            use_client_preference=False,
            client_idle_timeout=1.0,
        )
    )
    resolved = SimpleNamespace(
        url="http://example-agent.internal:24020",
        headers={},
        name="TestAgent",
    )

    fake_peer_descriptor = SimpleNamespace(selected_url="http://example-agent.internal")
    shared_client = SimpleNamespace(
        get_agent_resolution=AsyncMock(
            return_value=(SimpleNamespace(name="Shared Card"), fake_peer_descriptor)
        )
    )
    get_client_mock = AsyncMock(return_value=shared_client)
    monkeypatch.setattr(gateway, "_get_client", get_client_mock)

    async with gateway.open_invoke_session(
        resolved=resolved,
        policy=AgentResolutionPolicy.CACHED_SHARED,
    ) as session:
        assert session.client is shared_client
        assert session.ownership == InvokeSessionOwnership.SHARED
        assert session.policy == AgentResolutionPolicy.CACHED_SHARED
        assert session.snapshot.peer_descriptor is fake_peer_descriptor

    get_client_mock.assert_awaited_once_with(resolved)
    shared_client.get_agent_resolution.assert_awaited_once()


@pytest.mark.asyncio
async def test_gateway_open_invoke_session_uses_fresh_snapshot_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = gateway_module.A2AGateway(
        A2ASettings(
            default_timeout=10.0,
            use_client_preference=False,
            client_idle_timeout=1.0,
        )
    )
    resolved = SimpleNamespace(
        url="http://example-agent.internal:24020",
        headers={},
        name="TestAgent",
    )
    fake_peer_descriptor = SimpleNamespace(selected_url="http://example-agent.internal")
    temporary_client = SimpleNamespace(
        get_agent_resolution=AsyncMock(
            return_value=(SimpleNamespace(name="Fresh Card"), fake_peer_descriptor)
        ),
        close=AsyncMock(),
    )
    create_client_mock = Mock(return_value=temporary_client)
    get_client_mock = AsyncMock(
        side_effect=AssertionError("shared client not expected")
    )
    monkeypatch.setattr(gateway, "_create_client", create_client_mock)
    monkeypatch.setattr(gateway, "_get_client", get_client_mock)

    async with gateway.open_invoke_session(
        resolved=resolved,
        policy=AgentResolutionPolicy.FRESH_SNAPSHOT,
        card_fetch_timeout=5.0,
    ) as session:
        assert session.client is temporary_client
        assert session.ownership == InvokeSessionOwnership.EPHEMERAL
        assert session.policy == AgentResolutionPolicy.FRESH_SNAPSHOT
        assert session.snapshot.card_fetch_timeout == 5.0
        assert session.snapshot.peer_descriptor is fake_peer_descriptor

    create_client_mock.assert_called_once_with(resolved, card_fetch_timeout=5.0)
    temporary_client.get_agent_resolution.assert_awaited_once()
    temporary_client.close.assert_awaited_once()
    get_client_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_gateway_maintenance_loop_runs_cleanup() -> None:
    gateway = gateway_module.A2AGateway(
        A2ASettings(
            default_timeout=10.0,
            use_client_preference=False,
            client_idle_timeout=1.0,
            client_maintenance_interval=0.01,
        )
    )
    cleanup_mock = AsyncMock()
    gateway._cleanup_idle_clients = cleanup_mock

    await gateway.start_maintenance()
    await asyncio.sleep(0.03)
    await gateway.stop_maintenance()

    assert cleanup_mock.await_count >= 1


@pytest.mark.asyncio
async def test_gateway_invalidate_client_schedules_background_close() -> None:
    gateway = gateway_module.A2AGateway(
        A2ASettings(
            default_timeout=10.0,
            use_client_preference=False,
            client_idle_timeout=1.0,
        )
    )
    close_started = asyncio.Event()
    release_close = asyncio.Event()

    async def _close() -> None:
        close_started.set()
        await release_close.wait()

    fake_client = SimpleNamespace(
        close=AsyncMock(side_effect=_close),
        is_busy=Mock(return_value=False),
    )
    resolved = SimpleNamespace(
        url="http://example-agent.internal:24020",
        headers={},
        name="TestAgent",
    )
    cache_key = registry_module.A2AClientRegistry.build_cache_key(resolved)
    gateway._client_registry.clients[cache_key] = registry_module.CachedClientEntry(
        client=fake_client,
        last_used=time.monotonic(),
    )

    await asyncio.wait_for(gateway._invalidate_client(resolved), timeout=0.1)

    assert cache_key not in gateway._client_registry.clients
    await asyncio.wait_for(close_started.wait(), timeout=0.1)
    assert gateway.get_lifecycle_snapshot().reaper.pending_tasks == 1

    release_close.set()
    await gateway.shutdown()
    fake_client.close.assert_awaited_once()


def test_extract_text_from_payload_can_handle_task_like_payload() -> None:
    fake_task_payload = SimpleNamespace(
        artifacts=[
            SimpleNamespace(
                parts=[TextPart(text="Task completed")],
            )
        ]
    )
    text = A2AClient._extract_text_from_payload(fake_task_payload)

    assert text == "Task completed"


def test_extract_text_from_payload_can_handle_history_message() -> None:
    user_message = Message(
        message_id="m1",
        role=Role("user"),
        parts=[TextPart(text="Previous prompt")],
    )
    agent_payload = SimpleNamespace(history=[user_message])

    text = A2AClient._extract_text_from_payload(agent_payload)

    assert text == "Previous prompt"


def test_extract_text_from_payload_can_handle_dict_shape_payload() -> None:
    payload = {
        "status": {
            "message": {
                "parts": [
                    {"text": "Mapping based response"},
                ]
            }
        }
    }

    text = A2AClient._extract_text_from_payload(payload)

    assert text == "Mapping based response"


@pytest.mark.asyncio
async def test_call_agent_falls_back_to_plain_string_without_json_wrapping() -> None:
    class LegacyResponse:
        def __str__(self) -> str:
            return "Task(artifacts=[...])"

    a2a_client = A2AClient("http://example-agent.internal:24020")
    a2a_client._send_with_fallback = AsyncMock(return_value=LegacyResponse())

    result = await a2a_client.call_agent("hello")

    assert result["success"] is True
    assert result["content"] == "Task(artifacts=[...])"


@pytest.mark.asyncio
async def test_cancel_task_returns_success_for_valid_request() -> None:
    a2a_client = A2AClient("http://example-agent.internal:24020")
    a2a_client._cancel_with_fallback = AsyncMock(return_value={"id": "task-1"})

    result = await a2a_client.cancel_task(" task-1 ")

    assert result["success"] is True
    assert result["task_id"] == "task-1"
    assert result["task"] == {"id": "task-1"}


@pytest.mark.asyncio
async def test_cancel_task_maps_http_status_error_codes() -> None:
    a2a_client = A2AClient("http://example-agent.internal:24020")
    a2a_client._cancel_with_fallback = AsyncMock(
        side_effect=A2AClientHTTPError(404, "Task not found")
    )

    result = await a2a_client.cancel_task("task-missing")

    assert result["success"] is False
    assert result["error_code"] == "task_not_found"


@pytest.mark.asyncio
async def test_cancel_task_rejects_blank_task_id() -> None:
    a2a_client = A2AClient("http://example-agent.internal:24020")

    result = await a2a_client.cancel_task("  ")

    assert result["success"] is False
    assert result["error_code"] == "invalid_task_id"
