"""Adapter for PascalCase JSON-RPC A2A peers such as swival."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
from a2a.client import ClientCallInterceptor
from httpx_sse import aconnect_sse

from app.integrations.a2a_client.adapters.base import A2AAdapter
from app.integrations.a2a_client.adapters.jsonrpc_common import (
    apply_jsonrpc_interceptors,
    build_jsonrpc_payload,
    parse_jsonrpc_error_bytes,
    parse_jsonrpc_error_payload,
)
from app.integrations.a2a_client.errors import (
    A2APeerProtocolError,
    A2AUnsupportedOperationError,
)
from app.integrations.a2a_client.models import A2AMessageRequest, A2APeerDescriptor
from app.integrations.a2a_client.selection import build_pascal_message_payload
from app.integrations.a2a_runtime_status_contract import (
    terminal_runtime_state_values,
)

JSONRPC_PASCAL_DIALECT = "jsonrpc_pascal"

_METHOD_SEND_MESSAGE = "SendMessage"
_METHOD_SEND_STREAMING_MESSAGE = "SendStreamingMessage"
_METHOD_GET_TASK = "GetTask"
_METHOD_CANCEL_TASK = "CancelTask"
_METHOD_GET_AUTHENTICATED_EXTENDED_AGENT_CARD = "GetAuthenticatedExtendedCard"
_FINAL_STATUS_STATES = terminal_runtime_state_values()


class JsonRpcPascalAdapter(A2AAdapter):
    """Minimal PascalCase JSON-RPC adapter for self-implemented A2A peers."""

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
        params = {
            "message": build_pascal_message_payload(request),
            "configuration": {"acceptedOutputModes": ["text/plain"]},
        }
        async for payload in self._send_rpc_stream(
            _METHOD_SEND_STREAMING_MESSAGE,
            params=params,
        ):
            yield payload

    async def get_task(
        self,
        task_id: str,
        *,
        history_length: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        params: dict[str, Any] = {"id": task_id}
        if history_length is not None:
            params["historyLength"] = history_length
        if metadata:
            params["metadata"] = metadata
        try:
            return await self._send_rpc(_METHOD_GET_TASK, params=params)
        except A2APeerProtocolError as exc:
            if exc.code == -32601:
                raise A2AUnsupportedOperationError(str(exc)) from exc
            raise

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
            if exc.code == -32601:
                raise A2AUnsupportedOperationError(str(exc)) from exc
            raise

    async def get_authenticated_extended_agent_card(self) -> Any:
        try:
            return await self._send_rpc(
                _METHOD_GET_AUTHENTICATED_EXTENDED_AGENT_CARD,
                params=None,
            )
        except A2APeerProtocolError as exc:
            if exc.code == -32601:
                raise A2AUnsupportedOperationError(str(exc)) from exc
            raise

    async def close(self) -> None:
        return None

    async def _send_rpc(
        self,
        method: str,
        *,
        params: dict[str, Any] | None,
    ) -> Any:
        payload = build_jsonrpc_payload(method=method, params=params)
        request_headers = {"Content-Type": "application/json"}
        request_headers.update(self._headers)
        payload, http_kwargs = await apply_jsonrpc_interceptors(
            interceptors=self._interceptors,
            method_name=method,
            request_payload=payload,
            http_kwargs={"headers": request_headers, "timeout": self._timeout},
            agent_card=self.descriptor.card,
        )
        try:
            response = await self._http_client.post(
                self.descriptor.selected_url,
                json=payload,
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

        if isinstance(data, dict):
            return data.get("result")
        return data

    async def _send_rpc_stream(
        self,
        method: str,
        *,
        params: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        payload = build_jsonrpc_payload(method=method, params=params)
        request_headers = {"Content-Type": "application/json"}
        request_headers.update(self._headers)
        payload, http_kwargs = await apply_jsonrpc_interceptors(
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
                json=payload,
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
                    protocol_error = await self._parse_non_sse_stream_error(response)
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
                    normalized = self._normalize_stream_event(
                        event_type=sse.event,
                        raw_data=sse.data,
                    )
                    if normalized is not None:
                        yield normalized
        except httpx.RequestError as exc:
            raise A2APeerProtocolError(
                message=str(exc),
                error_code="peer_request_error",
            ) from exc

    async def _parse_non_sse_stream_error(
        self, response: httpx.Response
    ) -> A2APeerProtocolError | None:
        try:
            raw_body = await response.aread()
        except httpx.RequestError:
            return None

        return parse_jsonrpc_error_bytes(
            raw_body,
            fallback_message="Invalid JSON-RPC stream response",
            http_status=response.status_code,
        )

    def _normalize_stream_event(
        self,
        *,
        event_type: str,
        raw_data: str,
    ) -> dict[str, Any] | None:
        try:
            payload = json.loads(raw_data)
        except json.JSONDecodeError as exc:
            raise A2APeerProtocolError(
                message=str(exc),
                error_code="invalid_json_response",
            ) from exc

        if not isinstance(payload, dict):
            raise A2APeerProtocolError(
                message="Invalid Pascal streaming payload",
                error_code="peer_protocol_error",
            )

        if event_type == "TaskArtifactUpdateEvent" or (
            "artifact" in payload and "status" not in payload
        ):
            return self._normalize_artifact_update(payload)
        if event_type == "TaskStatusUpdateEvent" or "status" in payload:
            return self._normalize_status_update(payload)
        return None

    @staticmethod
    def _normalize_artifact_update(payload: dict[str, Any]) -> dict[str, Any]:
        artifact = payload.get("artifact")
        if not isinstance(artifact, dict):
            raise A2APeerProtocolError(
                message="Invalid Pascal artifact-update payload",
                error_code="peer_protocol_error",
            )

        normalized_artifact = dict(artifact)
        parts = artifact.get("parts")
        normalized_parts: list[dict[str, Any]] = []
        if isinstance(parts, list):
            for part in parts:
                if not isinstance(part, dict):
                    continue
                normalized_part = dict(part)
                raw_kind = normalized_part.get("kind") or normalized_part.get("type")
                if isinstance(raw_kind, str) and raw_kind.strip().lower() == "text":
                    normalized_part["kind"] = "text"
                normalized_parts.append(normalized_part)
        normalized_artifact["parts"] = normalized_parts

        metadata = normalized_artifact.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        if metadata.get("block_type") in (None, "") and any(
            isinstance(part, dict)
            and str(part.get("kind") or part.get("type") or "").strip().lower()
            == "text"
            and isinstance(part.get("text"), str)
            and part.get("text")
            for part in normalized_parts
        ):
            metadata["block_type"] = "text"
        if metadata:
            normalized_artifact["metadata"] = metadata

        normalized = {
            "kind": "artifact-update",
            "artifact": normalized_artifact,
        }
        task_id = payload.get("taskId")
        if isinstance(task_id, str) and task_id.strip():
            normalized["taskId"] = task_id
        context_id = payload.get("contextId")
        if isinstance(context_id, str) and context_id.strip():
            normalized["contextId"] = context_id
        return normalized

    @staticmethod
    def _normalize_status_update(payload: dict[str, Any]) -> dict[str, Any]:
        status = payload.get("status")
        if not isinstance(status, dict):
            raise A2APeerProtocolError(
                message="Invalid Pascal status-update payload",
                error_code="peer_protocol_error",
            )

        normalized: dict[str, Any] = {
            "kind": "status-update",
            "status": dict(status),
        }
        task_id = payload.get("taskId")
        if isinstance(task_id, str) and task_id.strip():
            normalized["taskId"] = task_id
        context_id = payload.get("contextId")
        if isinstance(context_id, str) and context_id.strip():
            normalized["contextId"] = context_id
        metadata = payload.get("metadata")
        if isinstance(metadata, dict) and metadata:
            normalized["metadata"] = dict(metadata)
        state = status.get("state")
        if isinstance(state, str) and state.strip().lower() in _FINAL_STATUS_STATES:
            normalized["final"] = True
        return normalized
