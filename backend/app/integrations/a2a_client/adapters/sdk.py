"""Adapter that delegates to the official Python a2a-sdk implementation."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
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
from a2a.client.errors import A2AClientJSONRPCError
from a2a.types import Message, Part, Role, TaskIdParams, TextPart, TransportProtocol

from app.integrations.a2a_client.adapters.base import A2AAdapter
from app.integrations.a2a_client.errors import A2APeerProtocolError
from app.integrations.a2a_client.models import A2AMessageRequest, A2APeerDescriptor
from app.utils.async_cleanup import await_cancel_safe

SDK_DIALECT = "sdk"


@dataclass(slots=True)
class _SDKClientEntry:
    config: ClientConfig
    client: Client


class SDKA2AAdapter(A2AAdapter):
    """Adapter backed by the upstream `a2a-sdk` client factory."""

    def __init__(
        self,
        descriptor: A2APeerDescriptor,
        *,
        http_client: httpx.AsyncClient,
        interceptors: list[ClientCallInterceptor] | None = None,
        consumers: list[Consumer] | None = None,
        use_client_preference: bool = False,
        supported_transports: list[TransportProtocol | str] | None = None,
    ) -> None:
        super().__init__(descriptor)
        self._http_client = http_client
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

    @property
    def dialect(self) -> str:
        return SDK_DIALECT

    async def send_message(self, request: A2AMessageRequest) -> Any:
        client = await self._get_client(streaming=False)
        try:
            final_payload: Any = None
            async for payload in client.send_message(self._build_message(request)):
                final_payload = payload
            return final_payload
        except A2AClientJSONRPCError as exc:
            raise _map_protocol_error(exc) from exc

    async def stream_message(self, request: A2AMessageRequest) -> AsyncIterator[Any]:
        client = await self._get_client(streaming=True)
        try:
            async for payload in client.send_message(self._build_message(request)):
                yield payload
        except A2AClientJSONRPCError as exc:
            raise _map_protocol_error(exc) from exc

    async def cancel_task(
        self,
        task_id: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        client = await self._get_client(streaming=False)
        try:
            return await client.cancel_task(TaskIdParams(id=task_id), metadata=metadata)
        except A2AClientJSONRPCError as exc:
            raise _map_protocol_error(exc) from exc

    async def close(self) -> None:
        async with self._client_lock:
            entries = list(self._clients.values())
            self._clients.clear()
        for entry in entries:
            try:
                await await_cancel_safe(entry.client.close())
            except Exception:
                continue

    async def _get_client(self, *, streaming: bool) -> Client:
        async with self._client_lock:
            entry = self._clients.get(streaming)
            if entry:
                return entry.client

            config = ClientConfig(
                streaming=streaming,
                polling=False,
                httpx_client=self._http_client,
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
