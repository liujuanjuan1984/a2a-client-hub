"""Adapter for slash-style JSON-RPC A2A peers."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import httpx
from a2a.client import ClientCallInterceptor
from a2a.types import (
    CancelTaskRequest,
    CancelTaskResponse,
    MessageSendConfiguration,
    MessageSendParams,
    SendMessageRequest,
    SendMessageResponse,
    SendStreamingMessageRequest,
    SendStreamingMessageResponse,
    TaskIdParams,
)
from httpx_sse import aconnect_sse
from pydantic import ValidationError

from app.integrations.a2a_client.adapters.base import A2AAdapter
from app.integrations.a2a_client.adapters.jsonrpc_common import (
    apply_jsonrpc_interceptors,
    parse_jsonrpc_error_bytes,
    parse_jsonrpc_error_payload,
)
from app.integrations.a2a_client.errors import (
    A2APeerProtocolError,
    A2AUnsupportedOperationError,
)
from app.integrations.a2a_client.models import A2AMessageRequest, A2APeerDescriptor
from app.integrations.a2a_client.selection import build_a2a_message

JSONRPC_SLASH_DIALECT = "jsonrpc_slash"

_METHOD_SEND_MESSAGE = "message/send"
_METHOD_SEND_STREAMING_MESSAGE = "message/stream"
_METHOD_CANCEL_TASK = "tasks/cancel"


class JsonRpcSlashAdapter(A2AAdapter):
    """Hub-owned slash-style JSON-RPC adapter that preserves single-shot semantics."""

    def __init__(
        self,
        descriptor: A2APeerDescriptor,
        *,
        http_client: httpx.AsyncClient,
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        interceptors: list[ClientCallInterceptor] | None = None,
    ) -> None:
        super().__init__(descriptor)
        self._http_client = http_client
        self._headers = dict(headers or {})
        self._timeout = timeout
        self._interceptors = list(interceptors or [])

    @property
    def dialect(self) -> str:
        return JSONRPC_SLASH_DIALECT

    async def send_message(self, request: A2AMessageRequest) -> Any:
        params = MessageSendParams(
            message=build_a2a_message(request),
            configuration=MessageSendConfiguration(
                accepted_output_modes=["text/plain"],
                blocking=True,
            ),
        )
        rpc_request = SendMessageRequest(params=params, id=str(uuid4()))
        return await self._send_rpc(
            method=_METHOD_SEND_MESSAGE,
            payload=rpc_request.model_dump(mode="json", exclude_none=True),
            response_model=SendMessageResponse,
        )

    async def stream_message(self, request: A2AMessageRequest) -> AsyncIterator[Any]:
        if not self.descriptor.supports_streaming:
            yield await self.send_message(request)
            return
        params = MessageSendParams(
            message=build_a2a_message(request),
            configuration=MessageSendConfiguration(
                accepted_output_modes=["text/plain"],
                blocking=True,
            ),
        )
        rpc_request = SendStreamingMessageRequest(
            params=params,
            id=str(uuid4()),
        )
        async for payload in self._send_rpc_stream(
            method=_METHOD_SEND_STREAMING_MESSAGE,
            payload=rpc_request.model_dump(mode="json", exclude_none=True),
        ):
            yield payload

    async def cancel_task(
        self,
        task_id: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        params = TaskIdParams(id=task_id, metadata=metadata)
        rpc_request = CancelTaskRequest(
            params=params,
            id=str(uuid4()),
        )
        try:
            return await self._send_rpc(
                method=_METHOD_CANCEL_TASK,
                payload=rpc_request.model_dump(mode="json", exclude_none=True),
                response_model=CancelTaskResponse,
            )
        except A2APeerProtocolError as exc:
            if exc.rpc_code == -32601:
                raise A2AUnsupportedOperationError(str(exc)) from exc
            raise

    async def close(self) -> None:
        return None

    async def _send_rpc(
        self, *, method: str, payload: dict[str, Any], response_model
    ) -> Any:
        request_headers = {"Content-Type": "application/json"}
        request_headers.update(self._headers)
        final_payload, http_kwargs = await apply_jsonrpc_interceptors(
            interceptors=self._interceptors,
            method_name=method,
            request_payload=payload,
            http_kwargs={"headers": request_headers, "timeout": self._timeout},
            agent_card=self.descriptor.card,
        )
        try:
            response = await self._http_client.post(
                self.descriptor.selected_url,
                json=final_payload,
                **http_kwargs,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise A2APeerProtocolError(
                message=str(exc),
                error_code=f"http_{exc.response.status_code}",
                http_status=exc.response.status_code,
            ) from exc
        except httpx.RequestError as exc:
            raise A2APeerProtocolError(
                message=str(exc),
                error_code="peer_request_error",
            ) from exc

        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise A2APeerProtocolError(
                message=str(exc),
                error_code="invalid_json_response",
                http_status=response.status_code,
            ) from exc

        protocol_error = parse_jsonrpc_error_payload(
            data,
            fallback_message="Invalid JSON-RPC response",
            http_status=response.status_code,
        )
        if protocol_error is not None:
            raise protocol_error

        try:
            parsed = response_model.model_validate(data)
        except ValidationError as exc:
            raise A2APeerProtocolError(
                message=str(exc),
                error_code="invalid_json_response",
                http_status=response.status_code,
            ) from exc
        return parsed.root.result

    async def _send_rpc_stream(
        self,
        *,
        method: str,
        payload: dict[str, Any],
    ) -> AsyncIterator[Any]:
        request_headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Cache-Control": "no-store",
        }
        request_headers.update(self._headers)
        final_payload, http_kwargs = await apply_jsonrpc_interceptors(
            interceptors=self._interceptors,
            method_name=method,
            request_payload=payload,
            http_kwargs={"headers": request_headers, "timeout": self._timeout},
            agent_card=self.descriptor.card,
        )
        try:
            async with aconnect_sse(
                self._http_client,
                "POST",
                self.descriptor.selected_url,
                json=final_payload,
                **http_kwargs,
            ) as event_source:
                response = event_source.response
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise A2APeerProtocolError(
                        message=str(exc),
                        error_code=f"http_{exc.response.status_code}",
                        http_status=exc.response.status_code,
                    ) from exc

                content_type = response.headers.get("content-type", "").partition(";")[
                    0
                ]
                if "text/event-stream" not in content_type:
                    raw_body = await response.aread()
                    protocol_error = parse_jsonrpc_error_bytes(
                        raw_body,
                        fallback_message=(
                            "Expected response header Content-Type to contain "
                            f"'text/event-stream', got {content_type!r}"
                        ),
                        http_status=response.status_code,
                    )
                    if protocol_error is not None:
                        raise protocol_error
                    raise A2APeerProtocolError(
                        message=(
                            "Expected response header Content-Type to contain "
                            f"'text/event-stream', got {content_type!r}"
                        ),
                        error_code="invalid_stream_response",
                        http_status=response.status_code,
                    )

                async for sse in event_source.aiter_sse():
                    try:
                        data = json.loads(sse.data)
                    except json.JSONDecodeError as exc:
                        raise A2APeerProtocolError(
                            message=str(exc),
                            error_code="invalid_json_response",
                        ) from exc

                    protocol_error = parse_jsonrpc_error_payload(
                        data,
                        fallback_message="Invalid JSON-RPC stream event",
                        http_status=response.status_code,
                    )
                    if protocol_error is not None:
                        raise protocol_error

                    try:
                        parsed = SendStreamingMessageResponse.model_validate(data)
                    except ValidationError as exc:
                        raise A2APeerProtocolError(
                            message=str(exc),
                            error_code="invalid_json_response",
                            http_status=response.status_code,
                        ) from exc
                    yield parsed.root.result
        except httpx.RequestError as exc:
            raise A2APeerProtocolError(
                message=str(exc),
                error_code="peer_request_error",
            ) from exc
