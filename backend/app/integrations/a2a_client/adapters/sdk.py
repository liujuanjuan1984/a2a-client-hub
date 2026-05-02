"""Adapter that delegates to the official Python a2a-sdk implementation."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncContextManager, cast

import httpx
from a2a.client import (
    Client,
    ClientCallInterceptor,
    ClientConfig,
    ClientFactory,
)
from a2a.client.client import ClientCallContext
from a2a.client.errors import A2AClientError, A2AClientTimeoutError
from a2a.types import (
    CancelTaskRequest,
    GetExtendedAgentCardRequest,
    GetTaskRequest,
    SendMessageConfiguration,
    SendMessageRequest,
)
from a2a.utils.constants import TransportProtocol
from a2a.utils.errors import (
    A2AError,
    ExtendedAgentCardNotConfiguredError,
    InvalidParamsError,
    InvalidRequestError,
    MethodNotFoundError,
    TaskNotCancelableError,
    TaskNotFoundError,
    UnsupportedOperationError,
)

from app.integrations.a2a_client.adapters.base import A2AAdapter
from app.integrations.a2a_client.errors import (
    A2APeerProtocolError,
    A2AUnsupportedOperationError,
    A2AUpstreamTimeoutError,
)
from app.integrations.a2a_client.http_clients import (
    SharedSDKTransportLease,
    invalidate_shared_sdk_transport_http_client,
    is_shared_sdk_transport_http_client_stale,
    use_shared_sdk_transport_http_client,
)
from app.integrations.a2a_client.lifecycle import AdapterLifecycleSnapshot
from app.integrations.a2a_client.models import A2AMessageRequest, A2APeerDescriptor
from app.integrations.a2a_client.selection import build_a2a_message
from app.integrations.a2a_extensions.negotiation import (
    build_extension_request_headers,
)
from app.utils.async_cleanup import await_cancel_safe

SDK_DIALECT = "sdk"


@dataclass(slots=True)
class _SDKClientEntry:
    config: ClientConfig
    client: Client


class SDKA2AAdapterRetiredError(RuntimeError):
    """Raised when an adapter has been retired and can no longer accept work."""


class _NonClosingAsyncClientProxy:
    """Adapter-local proxy that borrows an AsyncClient without owning it."""

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._http_client = http_client

    @property
    def headers(self) -> httpx.Headers:  # pragma: no cover - simple delegation
        return self._http_client.headers

    @property
    def timeout(self) -> httpx.Timeout:  # pragma: no cover - simple delegation
        return self._http_client.timeout

    @property
    def is_closed(self) -> bool:  # pragma: no cover - simple delegation
        return self._http_client.is_closed

    async def aclose(self) -> None:
        """No-op so SDK-managed close() cannot tear down shared transport state."""

        return None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._http_client, name)


class SDKA2AAdapter(A2AAdapter):
    """Adapter backed by the upstream `a2a-sdk` client factory."""

    def __init__(
        self,
        descriptor: A2APeerDescriptor,
        *,
        transport_http_client: httpx.AsyncClient,
        shared_transport_lease: SharedSDKTransportLease | None = None,
        interceptors: list[ClientCallInterceptor] | None = None,
        use_client_preference: bool = False,
        supported_transports: list[TransportProtocol | str] | None = None,
    ) -> None:
        super().__init__(descriptor)
        self._transport_http_client = transport_http_client
        self._shared_transport_lease = shared_transport_lease
        self._sdk_http_client = _NonClosingAsyncClientProxy(self._transport_http_client)
        self._interceptors = list(interceptors or [])
        self._use_client_preference = use_client_preference
        self._supported_transports = list(
            supported_transports
            if supported_transports is not None
            else [TransportProtocol.JSONRPC, TransportProtocol.HTTP_JSON]
        )
        self._client_lock = asyncio.Lock()
        self._clients: dict[bool, _SDKClientEntry] = {}
        self._lifecycle_lock = asyncio.Lock()
        self._active_operations = 0
        self._retired = False
        self._closed = False
        self._closed_event = asyncio.Event()

    @property
    def dialect(self) -> str:
        return SDK_DIALECT

    async def send_message(self, request: A2AMessageRequest) -> Any:
        async with self._operation_usage(), self._transport_usage():
            client = await self._get_client(streaming=False)
            try:
                final_payload: Any = None
                service_parameters = build_extension_request_headers(
                    base_headers=None,
                    requested_extensions=request.requested_extensions,
                )
                context = (
                    ClientCallContext(service_parameters=service_parameters)
                    if service_parameters
                    else None
                )
                sdk_request = SendMessageRequest(
                    message=build_a2a_message(request),
                    configuration=SendMessageConfiguration(
                        accepted_output_modes=["text/plain"]
                    ),
                    metadata=request.metadata,
                )
                if context is None:
                    message_stream = client.send_message(sdk_request)
                else:
                    message_stream = client.send_message(
                        sdk_request,
                        context=context,
                    )
                async for payload in message_stream:
                    final_payload = payload
                return final_payload
            except (A2AClientError, A2AError) as exc:
                raise _map_sdk_exception(exc) from exc

    async def stream_message(self, request: A2AMessageRequest) -> AsyncIterator[Any]:
        if not bool(getattr(self.descriptor, "supports_streaming", True)):
            yield await self.send_message(request)
            return
        async with self._operation_usage(), self._transport_usage():
            client = await self._get_client(streaming=True)
            try:
                service_parameters = build_extension_request_headers(
                    base_headers=None,
                    requested_extensions=request.requested_extensions,
                )
                context = (
                    ClientCallContext(service_parameters=service_parameters)
                    if service_parameters
                    else None
                )
                sdk_request = SendMessageRequest(
                    message=build_a2a_message(request),
                    configuration=SendMessageConfiguration(
                        accepted_output_modes=["text/plain"]
                    ),
                    metadata=request.metadata,
                )
                if context is None:
                    message_stream = client.send_message(sdk_request)
                else:
                    message_stream = client.send_message(
                        sdk_request,
                        context=context,
                    )
                async for payload in message_stream:
                    yield payload
            except (A2AClientError, A2AError) as exc:
                raise _map_sdk_exception(exc) from exc

    async def get_task(
        self,
        task_id: str,
        *,
        history_length: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        async with self._operation_usage(), self._transport_usage():
            client = await self._get_client(streaming=False)
            try:
                request_kwargs: dict[str, Any] = {"id": task_id}
                if history_length is not None:
                    request_kwargs["history_length"] = history_length
                return await client.get_task(GetTaskRequest(**request_kwargs))
            except (A2AClientError, A2AError) as exc:
                raise _map_sdk_exception(exc) from exc

    async def cancel_task(
        self,
        task_id: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        async with self._operation_usage(), self._transport_usage():
            client = await self._get_client(streaming=False)
            try:
                return await client.cancel_task(
                    CancelTaskRequest(id=task_id, metadata=metadata),
                )
            except (A2AClientError, A2AError) as exc:
                raise _map_sdk_exception(exc) from exc

    async def get_authenticated_extended_agent_card(self) -> Any:
        async with self._operation_usage(), self._transport_usage():
            client = await self._get_client(streaming=False)
            try:
                return await client.get_extended_agent_card(
                    GetExtendedAgentCardRequest()
                )
            except (A2AClientError, A2AError) as exc:
                raise _map_sdk_exception(exc) from exc

    async def close(self) -> None:
        await self.retire()
        await self._closed_event.wait()

    async def retire(self) -> None:
        should_finalize = False
        async with self._lifecycle_lock:
            if self._closed:
                return
            self._retired = True
            if self._active_operations == 0:
                self._closed = True
                should_finalize = True
        if should_finalize:
            await self._finalize_clients()

    async def _finalize_clients(self) -> None:
        async with self._client_lock:
            entries = list(self._clients.values())
            self._clients.clear()
        try:
            for entry in entries:
                try:
                    close_result = getattr(entry.client, "close", None)
                    if callable(close_result):
                        await await_cancel_safe(close_result())
                        continue
                    aclose_result = getattr(entry.client, "aclose", None)
                    if callable(aclose_result):
                        await await_cancel_safe(aclose_result())
                except Exception:
                    continue
        finally:
            self._closed_event.set()

    async def invalidate_borrowed_transport(self) -> bool:
        """Invalidate the borrowed shared transport generation, if any."""

        if self._shared_transport_lease is None:
            return False
        return await invalidate_shared_sdk_transport_http_client(
            self._shared_transport_lease
        )

    def is_transport_stale(self) -> bool:
        """Check whether the borrowed shared transport lease has been invalidated."""

        if self._shared_transport_lease is None:
            return False
        return is_shared_sdk_transport_http_client_stale(self._shared_transport_lease)

    def get_lifecycle_snapshot(self) -> AdapterLifecycleSnapshot:
        return AdapterLifecycleSnapshot(
            dialect=self.dialect,
            active_operations=self._active_operations,
            retired=self._retired,
            closed=self._closed,
            transport_stale=self.is_transport_stale(),
        )

    async def _get_client(self, *, streaming: bool) -> Client:
        async with self._client_lock:
            entry = self._clients.get(streaming)
            if entry:
                return entry.client

            config = ClientConfig(
                streaming=streaming,
                polling=False,
                httpx_client=cast(httpx.AsyncClient, self._sdk_http_client),
                use_client_preference=self._use_client_preference,
                supported_protocol_bindings=_normalize_supported_transports(
                    self._supported_transports
                ),
            )
            factory = ClientFactory(config=config)
            client = factory.create(
                self.descriptor.card,
                interceptors=list(self._interceptors),
            )
            self._clients[streaming] = _SDKClientEntry(config=config, client=client)
            return client

    def _transport_usage(self) -> AsyncContextManager[None]:
        return use_shared_sdk_transport_http_client(self._shared_transport_lease)

    @asynccontextmanager
    async def _operation_usage(self) -> AsyncIterator[None]:
        await self._acquire_operation()
        try:
            yield
        finally:
            await self._release_operation()

    async def _acquire_operation(self) -> None:
        async with self._lifecycle_lock:
            if self._retired or self._closed:
                raise SDKA2AAdapterRetiredError("A2A SDK adapter has been retired.")
            self._active_operations += 1

    async def _release_operation(self) -> None:
        should_finalize = False
        async with self._lifecycle_lock:
            if self._active_operations > 0:
                self._active_operations -= 1
            if self._active_operations == 0 and self._retired and not self._closed:
                self._closed = True
                should_finalize = True
        if should_finalize:
            await self._finalize_clients()


def _normalize_supported_transports(
    supported_transports: list[TransportProtocol | str],
) -> list[str]:
    normalized: list[str] = []
    for item in supported_transports:
        candidate = item.value if isinstance(item, TransportProtocol) else str(item)
        stripped = candidate.strip()
        if stripped and stripped not in normalized:
            normalized.append(stripped)
    return normalized or [TransportProtocol.JSONRPC.value]


def _map_sdk_exception(
    exc: A2AClientError | A2AError,
) -> A2AUpstreamTimeoutError | A2AUnsupportedOperationError | A2APeerProtocolError:
    if isinstance(exc, A2AClientTimeoutError):
        return A2AUpstreamTimeoutError(str(exc))

    if isinstance(
        exc,
        (
            UnsupportedOperationError,
            MethodNotFoundError,
            ExtendedAgentCardNotConfiguredError,
        ),
    ):
        error_code = "unsupported_operation"
        if isinstance(exc, MethodNotFoundError):
            error_code = "method_not_found"
        elif isinstance(exc, ExtendedAgentCardNotConfiguredError):
            error_code = "extended_agent_card_not_configured"
        mapped = A2AUnsupportedOperationError(str(exc))
        mapped.error_code = error_code
        return mapped

    if isinstance(exc, TaskNotFoundError):
        return A2APeerProtocolError(str(exc), error_code="task_not_found")

    if isinstance(exc, TaskNotCancelableError):
        return A2APeerProtocolError(str(exc), error_code="task_not_cancelable")

    if isinstance(exc, InvalidParamsError):
        return A2APeerProtocolError(str(exc), error_code="invalid_params")

    if isinstance(exc, InvalidRequestError):
        return A2APeerProtocolError(str(exc), error_code="invalid_request")

    return A2APeerProtocolError(
        str(exc),
        error_code="peer_protocol_error",
        data=getattr(exc, "data", None),
    )
