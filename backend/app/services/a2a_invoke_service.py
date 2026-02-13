"""Shared helpers for invoking A2A agents across different catalogs.

The hub (admin-managed) and user-managed A2A routes should share streaming
transport logic to keep behavior consistent and reduce drift.
"""

from __future__ import annotations

import inspect
from typing import Any, AsyncIterator, Callable

from a2a.client.client import ClientEvent
from a2a.types import Message
from fastapi import WebSocket
from fastapi.responses import StreamingResponse

from app.utils.json_encoder import json_dumps

StreamEvent = ClientEvent | Message
ValidateMessageFn = Callable[[dict[str, Any]], list[Any]]
StreamCallbackFn = Callable[[str], Any]


class A2AInvokeService:
    """Transport-level helpers for blocking/SSE/WS A2A invocation."""

    # Keep client-facing stream errors generic. Internal errors go to logs.
    _STREAM_ERROR_MESSAGE = "Upstream streaming failed"
    _STREAM_ERROR_CODE = "upstream_stream_error"

    @classmethod
    def build_ws_error_event(
        cls,
        *,
        message: str,
        error_code: str | None = None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {"message": message}
        if error_code:
            data["error_code"] = error_code
        return {"event": "error", "data": data}

    async def send_ws_error(
        self,
        websocket: WebSocket,
        *,
        message: str,
        error_code: str | None = None,
    ) -> None:
        await websocket.send_text(
            json_dumps(
                self.build_ws_error_event(message=message, error_code=error_code),
                ensure_ascii=False,
            )
        )

    @staticmethod
    async def _call_callback(callback: StreamCallbackFn | None, value: str) -> None:
        if callback is None:
            return
        outcome = callback(value)
        if inspect.isawaitable(outcome):
            await outcome

    @staticmethod
    def _extract_stream_text(payload: dict[str, Any]) -> str:
        if payload.get("kind") == "artifact-update":
            artifact = payload.get("artifact")
            parts = artifact.get("parts") if isinstance(artifact, dict) else None
            if isinstance(parts, list):
                collected: list[str] = []
                for part in parts:
                    if not isinstance(part, dict):
                        continue
                    kind = str(part.get("kind") or "")
                    text = part.get("text")
                    if kind == "text" and isinstance(text, str):
                        collected.append(text)
                return "".join(collected)
        content = payload.get("content")
        if isinstance(content, str):
            return content
        message = payload.get("message")
        if isinstance(message, str):
            return message
        return ""

    @staticmethod
    def serialize_stream_event(
        event: StreamEvent, *, validate_message: ValidateMessageFn
    ) -> dict[str, Any]:
        from app.core.config import settings

        if isinstance(event, tuple):
            resolved = event[1] if event[1] else event[0]
        else:
            resolved = event

        payload = resolved.model_dump(exclude_none=True)
        if settings.debug:
            payload["validation_errors"] = validate_message(payload)
        return payload

    def stream_sse(
        self,
        *,
        gateway: Any,
        resolved: Any,
        query: str,
        context_id: str | None,
        metadata: dict[str, Any] | None,
        validate_message: ValidateMessageFn,
        logger: Any,
        log_extra: dict[str, Any],
        on_complete: StreamCallbackFn | None = None,
        on_error: StreamCallbackFn | None = None,
    ) -> StreamingResponse:
        async def event_generator() -> AsyncIterator[str]:
            collected: list[str] = []
            stream_failed = False
            try:
                async for event in gateway.stream(
                    resolved=resolved,
                    query=query,
                    context_id=context_id,
                    metadata=metadata,
                ):
                    serialized = self.serialize_stream_event(
                        event, validate_message=validate_message
                    )
                    text = self._extract_stream_text(serialized)
                    if text:
                        collected.append(text)
                    yield f"data: {json_dumps(serialized, ensure_ascii=False)}\n\n"
            except Exception:
                stream_failed = True
                logger.warning("A2A SSE stream failed", exc_info=True, extra=log_extra)
                await self._call_callback(on_error, self._STREAM_ERROR_MESSAGE)
                yield (
                    "event: error\n"
                    f"data: {json_dumps({'message': self._STREAM_ERROR_MESSAGE}, ensure_ascii=False)}\n\n"
                )
            finally:
                if not stream_failed:
                    await self._call_callback(on_complete, "".join(collected))
                yield "event: stream_end\ndata: {}\n\n"

        # Ensure downstreams do not persist potentially sensitive content.
        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-store, no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    async def stream_ws(
        self,
        *,
        websocket: WebSocket,
        gateway: Any,
        resolved: Any,
        query: str,
        context_id: str | None,
        metadata: dict[str, Any] | None,
        validate_message: ValidateMessageFn,
        logger: Any,
        log_extra: dict[str, Any],
        on_complete: StreamCallbackFn | None = None,
        on_error: StreamCallbackFn | None = None,
    ) -> None:
        collected: list[str] = []
        stream_failed = False
        try:
            async for event in gateway.stream(
                resolved=resolved,
                query=query,
                context_id=context_id,
                metadata=metadata,
            ):
                serialized = self.serialize_stream_event(
                    event, validate_message=validate_message
                )
                text = self._extract_stream_text(serialized)
                if text:
                    collected.append(text)
                await websocket.send_text(json_dumps(serialized, ensure_ascii=False))
        except Exception:
            stream_failed = True
            logger.warning("A2A WS stream failed", exc_info=True, extra=log_extra)
            await self._call_callback(on_error, self._STREAM_ERROR_MESSAGE)
            await self.send_ws_error(
                websocket,
                message=self._STREAM_ERROR_MESSAGE,
                error_code=self._STREAM_ERROR_CODE,
            )
        finally:
            if not stream_failed:
                await self._call_callback(on_complete, "".join(collected))
            await websocket.send_text(json_dumps({"event": "stream_end", "data": {}}))


a2a_invoke_service = A2AInvokeService()

__all__ = ["A2AInvokeService", "a2a_invoke_service"]
