"""Adapter for PascalCase JSON-RPC A2A peers such as swival."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import httpx

from app.integrations.a2a_client.adapters.base import A2AAdapter
from app.integrations.a2a_client.errors import (
    A2APeerProtocolError,
    A2AStreamingNotSupportedError,
    A2AUnsupportedOperationError,
)
from app.integrations.a2a_client.models import A2AMessageRequest, A2APeerDescriptor
from app.integrations.a2a_client.selection import build_pascal_message_payload

JSONRPC_PASCAL_DIALECT = "jsonrpc_pascal"

_METHOD_SEND_MESSAGE = "SendMessage"
_METHOD_CANCEL_TASK = "CancelTask"


class JsonRpcPascalAdapter(A2AAdapter):
    """Minimal PascalCase JSON-RPC adapter for self-implemented A2A peers."""

    def __init__(
        self,
        descriptor: A2APeerDescriptor,
        *,
        http_client: httpx.AsyncClient,
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
    ) -> None:
        super().__init__(descriptor)
        self._http_client = http_client
        self._headers = dict(headers or {})
        self._timeout = timeout

    @property
    def dialect(self) -> str:
        return JSONRPC_PASCAL_DIALECT

    async def send_message(self, request: A2AMessageRequest) -> Any:
        params = {
            "message": build_pascal_message_payload(request),
            "configuration": {"acceptedOutputModes": ["text/plain"]},
        }
        return await self._send_rpc(_METHOD_SEND_MESSAGE, params=params)

    async def stream_message(self, request: A2AMessageRequest) -> AsyncIterator[Any]:
        if not self.descriptor.supports_streaming:
            yield await self.send_message(request)
            return
        raise A2AStreamingNotSupportedError(
            "PascalCase JSON-RPC streaming is not supported by this adapter yet"
        )

    async def cancel_task(
        self,
        task_id: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        params: dict[str, Any] = {"id": task_id}
        if metadata:
            params["metadata"] = metadata
        try:
            return await self._send_rpc(_METHOD_CANCEL_TASK, params=params)
        except A2APeerProtocolError as exc:
            if exc.rpc_code == -32601:
                raise A2AUnsupportedOperationError(str(exc)) from exc
            raise

    async def close(self) -> None:
        return None

    async def _send_rpc(self, method: str, *, params: dict[str, Any]) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid4()),
            "method": method,
            "params": params,
        }
        request_headers = {"Content-Type": "application/json"}
        request_headers.update(self._headers)
        try:
            response = await self._http_client.post(
                self.descriptor.selected_url,
                json=payload,
                headers=request_headers,
                timeout=self._timeout,
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

        if isinstance(data, dict) and isinstance(data.get("error"), dict):
            error = data["error"]
            code = error.get("code")
            message = error.get("message") or f"JSON-RPC Error {error}"
            raise A2APeerProtocolError(
                message=message,
                error_code=(
                    "method_not_found" if code == -32601 else "peer_protocol_error"
                ),
                rpc_code=code if isinstance(code, int) else None,
                data=error.get("data"),
                http_status=response.status_code,
            )

        if isinstance(data, dict):
            return data.get("result")
        return data
