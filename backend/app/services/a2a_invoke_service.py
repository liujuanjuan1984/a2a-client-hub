"""Shared helpers for invoking A2A agents across different catalogs.

The hub (admin-managed) and user-managed A2A routes should share streaming
transport logic to keep behavior consistent and reduce drift.
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Callable

from a2a.client.client import ClientEvent
from a2a.types import Message
from fastapi import WebSocket
from fastapi.responses import StreamingResponse

from app.utils.json_encoder import json_dumps

StreamEvent = ClientEvent | Message
ValidateMessageFn = Callable[[dict[str, Any]], list[Any]]


class A2AInvokeService:
    """Transport-level helpers for blocking/SSE/WS A2A invocation."""

    # Keep client-facing stream errors generic. Internal errors go to logs.
    _STREAM_ERROR_MESSAGE = "Upstream streaming failed"

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
    ) -> StreamingResponse:
        async def event_generator() -> AsyncIterator[str]:
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
                    yield f"data: {json_dumps(serialized, ensure_ascii=False)}\n\n"
            except Exception:
                logger.warning("A2A SSE stream failed", exc_info=True, extra=log_extra)
                yield (
                    "event: error\n"
                    f"data: {json_dumps({'message': self._STREAM_ERROR_MESSAGE}, ensure_ascii=False)}\n\n"
                )
            finally:
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
    ) -> None:
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
                await websocket.send_text(json_dumps(serialized, ensure_ascii=False))
        except Exception:
            logger.warning("A2A WS stream failed", exc_info=True, extra=log_extra)
            await websocket.send_text(
                json_dumps(
                    {
                        "event": "error",
                        "data": {"message": self._STREAM_ERROR_MESSAGE},
                    },
                    ensure_ascii=False,
                )
            )
        finally:
            await websocket.send_text(json_dumps({"event": "stream_end", "data": {}}))


a2a_invoke_service = A2AInvokeService()

__all__ = ["A2AInvokeService", "a2a_invoke_service"]
