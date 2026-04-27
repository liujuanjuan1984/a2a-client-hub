"""Shared types for invoke transport helpers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from a2a.types import StreamResponse

StreamEvent = StreamResponse | dict[str, Any]
ValidateMessageFn = Callable[[dict[str, Any]], list[Any]]
StreamTextCallbackFn = Callable[[str], Any]
StreamEventPayloadCallbackFn = Callable[[dict[str, Any]], Any]
StreamMetadataCallbackFn = Callable[[dict[str, Any]], Any]
StreamErrorMetadataCallbackFn = Callable[[dict[str, Any]], Any]
StreamSessionStartedCallbackFn = Callable[[Any], Any]


class StreamFinishReason(str, Enum):
    SUCCESS = "success"
    TIMEOUT_TOTAL = "timeout_total"
    TIMEOUT_IDLE = "timeout_idle"
    UPSTREAM_ERROR = "upstream_error"
    CLIENT_DISCONNECT = "client_disconnect"


@dataclass(frozen=True)
class StreamOutcome:
    success: bool
    finish_reason: StreamFinishReason
    final_text: str
    error_message: str | None
    error_code: str | None
    elapsed_seconds: float
    idle_seconds: float
    terminal_event_seen: bool
    internal_error_message: str | None = None
    source: str | None = None
    jsonrpc_code: int | None = None
    missing_params: tuple[dict[str, Any], ...] | None = None
    upstream_error: dict[str, Any] | None = None


@dataclass(frozen=True)
class StreamErrorPayload:
    message: str
    error_code: str | None
    source: str | None = None
    jsonrpc_code: int | None = None
    missing_params: tuple[dict[str, Any], ...] | None = None
    upstream_error: dict[str, Any] | None = None

    def as_event_data(self) -> dict[str, Any]:
        data: dict[str, Any] = {"message": self.message}
        if self.error_code:
            data["error_code"] = self.error_code
        if self.source:
            data["source"] = self.source
        if self.jsonrpc_code is not None:
            data["jsonrpc_code"] = self.jsonrpc_code
        if self.missing_params:
            data["missing_params"] = [dict(item) for item in self.missing_params]
        if self.upstream_error:
            data["upstream_error"] = dict(self.upstream_error)
        return data


StreamFinalizedCallbackFn = Callable[[StreamOutcome], Any]
