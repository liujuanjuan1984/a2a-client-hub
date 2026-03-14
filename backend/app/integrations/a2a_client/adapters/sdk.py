"""Adapter that delegates to the official Python a2a-sdk implementation."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import httpx
from a2a.client import (
    Client,
    ClientCallInterceptor,
    ClientConfig,
    ClientFactory,
    Consumer,
)
from a2a.client.errors import A2AClientHTTPError, A2AClientJSONRPCError
from a2a.types import (
    Message,
    MessageSendConfiguration,
    MessageSendParams,
    Part,
    Role,
    SendStreamingMessageRequest,
    TaskIdParams,
    TextPart,
    TransportProtocol,
)

from app.integrations.a2a_client.adapters.base import A2AAdapter
from app.integrations.a2a_client.errors import A2APeerProtocolError
from app.integrations.a2a_client.http_clients import (
    SharedSDKTransportLease,
    invalidate_shared_sdk_transport_http_client,
    is_shared_sdk_transport_http_client_stale,
    use_shared_sdk_transport_http_client,
)
from app.integrations.a2a_client.lifecycle import AdapterLifecycleSnapshot
from app.integrations.a2a_client.models import A2AMessageRequest, A2APeerDescriptor
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
    def headers(self):  # pragma: no cover - simple delegation
        return self._http_client.headers

    @property
    def timeout(self):  # pragma: no cover - simple delegation
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
        consumers: list[Consumer] | None = None,
        use_client_preference: bool = False,
        supported_transports: list[TransportProtocol | str] | None = None,
    ) -> None:
        super().__init__(descriptor)
        self._transport_http_client = transport_http_client
        self._shared_transport_lease = shared_transport_lease
        self._sdk_http_client = _NonClosingAsyncClientProxy(self._transport_http_client)
        self._interceptors = list(interceptors or [])
        self._consumers = list(consumers or [])
        self._use_client_preference = use_client_preference
        self._supported_transports = list(
            supported_transports
            if supported_transports is not None
            else [TransportProtocol.jsonrpc, TransportProtocol.http_json]
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
                async for payload in client.send_message(self._build_message(request)):
                    final_payload = payload
                return final_payload
            except A2AClientJSONRPCError as exc:
                raise _map_protocol_error(exc) from exc

    async def stream_message(self, request: A2AMessageRequest) -> AsyncIterator[Any]:
        async with self._operation_usage(), self._transport_usage():
            client = await self._get_client(streaming=True)
            try:
                async for payload in client.send_message(self._build_message(request)):
                    yield payload
            except A2AClientJSONRPCError as exc:
                raise _map_protocol_error(exc) from exc
            except A2AClientHTTPError as exc:
                protocol_error = await self._probe_streaming_protocol_error(
                    request=request,
                    exc=exc,
                )
                if protocol_error is not None:
                    raise protocol_error from exc
                raise

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
                    TaskIdParams(id=task_id),
                    metadata=metadata,
                )
            except A2AClientJSONRPCError as exc:
                raise _map_protocol_error(exc) from exc

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
                    await await_cancel_safe(entry.client.close())
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
                httpx_client=self._sdk_http_client,
                use_client_preference=self._use_client_preference,
                supported_transports=list(self._supported_transports),
            )
            factory = ClientFactory(config=config, consumers=list(self._consumers))
            client = factory.create(
                self.descriptor.card,
                consumers=None,
                interceptors=list(self._interceptors),
            )
            self._clients[streaming] = _SDKClientEntry(config=config, client=client)
            return client

    async def _apply_interceptors(
        self,
        method_name: str,
        request_payload: dict[str, Any],
        http_kwargs: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        final_payload = request_payload
        final_http_kwargs = dict(http_kwargs or {})
        for interceptor in self._interceptors:
            final_payload, final_http_kwargs = await interceptor.intercept(
                method_name,
                final_payload,
                final_http_kwargs,
                self.descriptor.card,
                None,
            )
        return final_payload, final_http_kwargs

    async def _probe_streaming_protocol_error(
        self,
        *,
        request: A2AMessageRequest,
        exc: A2AClientHTTPError,
    ) -> A2APeerProtocolError | None:
        if self.descriptor.selected_transport.upper() != "JSONRPC":
            return None

        message = getattr(exc, "message", str(exc)).lower()
        if "text/event-stream" not in message and "invalid sse response" not in message:
            return None

        params = MessageSendParams(
            message=self._build_message(request),
            configuration=MessageSendConfiguration(
                accepted_output_modes=["text/plain"],
                blocking=True,
            ),
        )
        rpc_request = SendStreamingMessageRequest(
            params=params,
            id=str(uuid4()),
        )
        payload, http_kwargs = await self._apply_interceptors(
            "message/stream",
            rpc_request.model_dump(mode="json", exclude_none=True),
            {
                "headers": {
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                    "Cache-Control": "no-store",
                },
                "timeout": self._transport_http_client.timeout.as_dict().get(
                    "read", None
                ),
            },
        )
        try:
            response = await self._transport_http_client.post(
                self.descriptor.selected_url,
                json=payload,
                **http_kwargs,
            )
        except httpx.RequestError:
            return None
        return _parse_jsonrpc_error_response(
            response=response,
            invalid_stream_error_message=getattr(exc, "message", str(exc)),
        )

    def _transport_usage(self):
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

    def _build_message(self, request: A2AMessageRequest) -> Message:
        raw_role = (
            getattr(Role, "USER", None) or getattr(Role, "user", None) or Role("user")
        )
        resolved_context_id = request.context_id or str(uuid4())
        parts: list[Part] = [TextPart(text=request.query)]
        return Message(
            message_id=str(uuid4()),
            role=raw_role,
            parts=parts,
            context_id=resolved_context_id,
            metadata=request.metadata or None,
        )


def _map_protocol_error(exc: A2AClientJSONRPCError) -> A2APeerProtocolError:
    error = getattr(exc, "error", None)
    code = getattr(error, "code", None)
    message = getattr(error, "message", None) or str(exc)
    data = getattr(error, "data", None)
    return A2APeerProtocolError(
        message=message,
        error_code=_normalize_protocol_error_code(code=code, message=message),
        rpc_code=code if isinstance(code, int) else None,
        data=data,
    )


def _normalize_protocol_error_code(*, code: Any, message: str) -> str:
    if code == -32601:
        return "method_not_found"
    candidate = str(message).strip().replace("-", "_").replace(" ", "_").lower()
    return candidate or "peer_protocol_error"


def _parse_jsonrpc_error_response(
    *,
    response: httpx.Response,
    invalid_stream_error_message: str,
) -> A2APeerProtocolError | None:
    try:
        data = response.json()
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict):
        return None
    error = data.get("error")
    if not isinstance(error, dict):
        return None

    code = error.get("code")
    message = error.get("message") or invalid_stream_error_message
    return A2APeerProtocolError(
        message=str(message),
        error_code=("method_not_found" if code == -32601 else "peer_protocol_error"),
        rpc_code=code if isinstance(code, int) else None,
        data=error.get("data"),
        http_status=response.status_code,
    )
