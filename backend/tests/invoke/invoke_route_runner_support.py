from __future__ import annotations

import asyncio
import inspect
import json
from types import SimpleNamespace
from typing import Literal
from uuid import UUID, uuid4

import pytest
from a2a.types import AgentCard
from fastapi import HTTPException, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.retry_after import DB_BUSY_RETRY_AFTER_SECONDS
from app.db.locking import (
    DbLockFailureKind,
    RetryableDbLockError,
    RetryableDbQueryTimeoutError,
)
from app.features.invoke import route_runner as invoke_route_runner
from app.features.invoke import route_runner_state, route_runner_streaming
from app.features.invoke.service import StreamFinishReason, StreamOutcome
from app.features.invoke.stream_persistence import InvokePersistenceRequest
from app.features.sessions.common import (
    BindInflightTaskReport,
    PreemptedInvokeReport,
    deserialize_interrupt_event_block_content,
)
from app.integrations.a2a_extensions.errors import (
    A2AExtensionNotSupportedError,
    A2AExtensionUpstreamError,
)
from app.schemas.a2a_invoke import A2AAgentInvokeRequest, A2AAgentInvokeResponse

# ruff: noqa: F401





async def _consume_stream(response: StreamingResponse) -> None:
    async for _ in response.body_iterator:
        pass


class _NoopWebSocket:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_text(self, payload: str) -> None:
        self.sent.append(payload)


class _CancelableCloseWebSocket:
    def __init__(
        self,
        *,
        receive_payload: object | None = None,
        receive_exc: Exception | None = None,
    ) -> None:
        self.state = SimpleNamespace(selected_subprotocol=None)
        self._receive_payload = receive_payload if receive_payload is not None else {}
        self._receive_exc = receive_exc
        self.close_started = asyncio.Event()
        self.close_released = asyncio.Event()
        self.close_finished = asyncio.Event()
        self.close_codes: list[int | None] = []

    async def accept(self, _subprotocol: str | None = None) -> None:
        return None

    async def receive_json(self) -> object:
        if self._receive_exc is not None:
            raise self._receive_exc
        return self._receive_payload

    async def close(self, code: int | None = None) -> None:
        self.close_codes.append(code)
        self.close_started.set()
        await self.close_released.wait()
        self.close_finished.set()


def _build_persistence_request(
    *,
    user_id: UUID | None = None,
    agent_id: UUID | None = None,
    agent_source: Literal["personal", "shared"] = "shared",
    query: str = "hello",
    transport: Literal["http_json", "http_sse", "scheduled", "ws"] = "http_json",
    stream_enabled: bool = True,
    user_sender: Literal["user", "automation"] = "user",
    extra_persisted_metadata: dict[str, object] | None = None,
) -> InvokePersistenceRequest:
    return InvokePersistenceRequest(
        user_id=user_id or uuid4(),
        agent_id=agent_id or uuid4(),
        agent_source=agent_source,
        query=query,
        transport=transport,
        stream_enabled=stream_enabled,
        user_sender=user_sender,
        extra_persisted_metadata=dict(extra_persisted_metadata or {}),
    )


__all__ = [
    "A2AAgentInvokeRequest",
    "A2AAgentInvokeResponse",
    "A2AExtensionNotSupportedError",
    "A2AExtensionUpstreamError",
    "AgentCard",
    "BindInflightTaskReport",
    "DB_BUSY_RETRY_AFTER_SECONDS",
    "DbLockFailureKind",
    "HTTPException",
    "JSONResponse",
    "PreemptedInvokeReport",
    "RetryableDbLockError",
    "RetryableDbQueryTimeoutError",
    "SimpleNamespace",
    "StreamFinishReason",
    "StreamOutcome",
    "StreamingResponse",
    "UUID",
    "WebSocketDisconnect",
    "_CancelableCloseWebSocket",
    "_NoopWebSocket",
    "_build_persistence_request",
    "_consume_stream",
    "asyncio",
    "deserialize_interrupt_event_block_content",
    "inspect",
    "invoke_route_runner",
    "json",
    "pytest",
    "route_runner_state",
    "route_runner_streaming",
    "uuid4",
]
