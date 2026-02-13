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
StreamTextCallbackFn = Callable[[str], Any]
StreamEventPayloadCallbackFn = Callable[[dict[str, Any]], Any]


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
    async def _call_callback(callback: Callable[[Any], Any] | None, value: Any) -> None:
        if callback is None:
            return
        outcome = callback(value)
        if inspect.isawaitable(outcome):
            await outcome

    @staticmethod
    def _as_dict(value: Any) -> dict[str, Any]:
        return dict(value) if isinstance(value, dict) else {}

    @staticmethod
    def _pick_first_str(payload: dict[str, Any], keys: tuple[str, ...]) -> str | None:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str):
                trimmed = value.strip()
                if trimmed:
                    return trimmed
        return None

    @classmethod
    def _extract_metadata_dict(cls, payload: dict[str, Any]) -> dict[str, Any]:
        resolved: dict[str, Any] = {}
        for key in ("metadata", "bindingMetadata", "binding_metadata"):
            value = payload.get(key)
            if isinstance(value, dict):
                resolved.update(value)
        return resolved

    @classmethod
    def _extract_binding_hints_from_payload(
        cls, payload: dict[str, Any]
    ) -> tuple[str | None, dict[str, Any]]:
        root = cls._as_dict(payload)
        message = cls._as_dict(root.get("message"))
        result = cls._as_dict(root.get("result"))

        context_id: str | None = None
        provider: str | None = None
        external_session_id: str | None = None
        resolved_metadata: dict[str, Any] = {}

        provider_keys = ("provider", "session_provider", "external_provider")
        external_id_keys = (
            "externalSessionId",
            "external_session_id",
            "upstream_session_id",
            "opencode_session_id",
        )

        for candidate in (root, message, result):
            if context_id is None:
                context_id = cls._pick_first_str(candidate, ("contextId", "context_id"))
            candidate_metadata = cls._extract_metadata_dict(candidate)
            if candidate_metadata:
                resolved_metadata.update(candidate_metadata)
            if provider is None:
                provider = cls._pick_first_str(candidate, provider_keys)
            if external_session_id is None:
                external_session_id = cls._pick_first_str(candidate, external_id_keys)

        if context_id is None:
            context_id = cls._pick_first_str(
                resolved_metadata, ("contextId", "context_id")
            )
        if provider is None:
            provider = cls._pick_first_str(resolved_metadata, provider_keys)
        if external_session_id is None:
            external_session_id = cls._pick_first_str(
                resolved_metadata, external_id_keys
            )

        if provider:
            resolved_metadata.setdefault("provider", provider)
        if external_session_id:
            resolved_metadata.setdefault("externalSessionId", external_session_id)

        return context_id, resolved_metadata

    @classmethod
    def extract_binding_hints_from_serialized_event(
        cls, payload: dict[str, Any]
    ) -> tuple[str | None, dict[str, Any]]:
        return cls._extract_binding_hints_from_payload(payload)

    @classmethod
    def _coerce_payload_to_dict(cls, payload: Any) -> dict[str, Any]:
        resolved_payload = payload
        if isinstance(resolved_payload, tuple):
            if len(resolved_payload) >= 2 and resolved_payload[1]:
                resolved_payload = resolved_payload[1]
            elif resolved_payload:
                resolved_payload = resolved_payload[0]
            else:
                return {}
        if isinstance(resolved_payload, dict):
            return dict(resolved_payload)
        if hasattr(resolved_payload, "model_dump"):
            try:
                dumped = resolved_payload.model_dump(exclude_none=True)
            except Exception:
                return {}
            if isinstance(dumped, dict):
                return dumped
        return {}

    @classmethod
    def extract_binding_hints_from_invoke_result(
        cls, result: dict[str, Any]
    ) -> tuple[str | None, dict[str, Any]]:
        context_id, metadata = cls._extract_binding_hints_from_payload(result)
        raw_payload = cls._coerce_payload_to_dict(result.get("raw"))
        if raw_payload:
            raw_context_id, raw_metadata = cls._extract_binding_hints_from_payload(
                raw_payload
            )
            if raw_context_id:
                context_id = raw_context_id
            if raw_metadata:
                metadata.update(raw_metadata)
        return context_id, metadata

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
        on_complete: StreamTextCallbackFn | None = None,
        on_error: StreamTextCallbackFn | None = None,
        on_event: StreamEventPayloadCallbackFn | None = None,
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
                    await self._call_callback(on_event, serialized)
                    text = self._extract_stream_text(serialized)
                    if text:
                        collected.append(text)
                    yield f"data: {json_dumps(serialized, ensure_ascii=False)}\n\n"
            except Exception:
                stream_failed = True
                logger.warning("A2A SSE stream failed", exc_info=True, extra=log_extra)
                await self._call_callback(on_error, self._STREAM_ERROR_MESSAGE)
                error_payload = self.build_ws_error_event(
                    message=self._STREAM_ERROR_MESSAGE,
                    error_code=self._STREAM_ERROR_CODE,
                )
                yield (
                    "event: error\n"
                    f"data: {json_dumps(error_payload['data'], ensure_ascii=False)}\n\n"
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
        on_complete: StreamTextCallbackFn | None = None,
        on_error: StreamTextCallbackFn | None = None,
        on_event: StreamEventPayloadCallbackFn | None = None,
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
                await self._call_callback(on_event, serialized)
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
