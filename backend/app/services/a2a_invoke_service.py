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
from app.utils.payload_extract import (
    as_dict,
    extract_context_id,
    extract_provider_and_external_session_id,
)

StreamEvent = ClientEvent | Message
ValidateMessageFn = Callable[[dict[str, Any]], list[Any]]
StreamTextCallbackFn = Callable[[str], Any]
StreamEventPayloadCallbackFn = Callable[[dict[str, Any]], Any]
StreamMetadataCallbackFn = Callable[[dict[str, Any]], Any]


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
        root = as_dict(payload)
        message = as_dict(root.get("message"))
        result = as_dict(root.get("result"))

        context_id: str | None = None
        provider: str | None = None
        external_session_id: str | None = None
        resolved_metadata: dict[str, Any] = {}

        for candidate in (root, message, result):
            if context_id is None:
                context_id = extract_context_id(candidate)
            candidate_metadata = cls._extract_metadata_dict(candidate)
            if candidate_metadata:
                resolved_metadata.update(candidate_metadata)
            if provider is None or external_session_id is None:
                (
                    candidate_provider,
                    candidate_external_session_id,
                ) = extract_provider_and_external_session_id(
                    candidate,
                    include_session_id_aliases=True,
                )
                if provider is None:
                    provider = candidate_provider
                if external_session_id is None:
                    external_session_id = candidate_external_session_id

        if context_id is None:
            context_id = extract_context_id(resolved_metadata)
        if provider is None or external_session_id is None:
            (
                metadata_provider,
                metadata_external_session_id,
            ) = extract_provider_and_external_session_id(
                resolved_metadata,
                include_session_id_aliases=True,
            )
            if provider is None:
                provider = metadata_provider
            if external_session_id is None:
                external_session_id = metadata_external_session_id

        if provider:
            resolved_metadata["provider"] = provider
        if external_session_id:
            resolved_metadata["externalSessionId"] = external_session_id

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

    class _StreamTextAccumulator:
        """Accumulates stream text for persistence.

        For opencode channelized events:
        - persist only `final_answer`
        - collect `reasoning` and `tool_call` into metadata payload
        - respect append/overwrite semantics per artifact
        - treat `source=final_snapshot` as overwrite

        For non-channelized events, keep legacy concatenation behavior.
        """

        _MAX_CHANNEL_METADATA_CHARS = 8_000

        def __init__(self) -> None:
            self._legacy_chunks: list[str] = []
            self._final_answer_by_artifact: dict[str, str] = {}
            self._reasoning_by_artifact: dict[str, str] = {}
            self._tool_call_by_artifact: dict[str, str] = {}
            self._artifact_last_seq: dict[str, int] = {}
            self._seq = 0

        @staticmethod
        def _extract_text_from_parts(parts: Any) -> str:
            if not isinstance(parts, list):
                return ""
            collected: list[str] = []
            for part in parts:
                if not isinstance(part, dict):
                    continue
                kind = str(part.get("kind") or "")
                text = part.get("text")
                if kind == "text" and isinstance(text, str):
                    collected.append(text)
            return "".join(collected)

        @staticmethod
        def _extract_artifact_channel(artifact: dict[str, Any]) -> str | None:
            metadata = artifact.get("metadata")
            if not isinstance(metadata, dict):
                return None
            opencode = metadata.get("opencode")
            if not isinstance(opencode, dict):
                return None
            channel = opencode.get("channel")
            if isinstance(channel, str) and channel.strip():
                return channel.strip().lower()
            return None

        @staticmethod
        def _extract_artifact_source(artifact: dict[str, Any]) -> str | None:
            metadata = artifact.get("metadata")
            if not isinstance(metadata, dict):
                return None
            opencode = metadata.get("opencode")
            if not isinstance(opencode, dict):
                return None
            source = opencode.get("source")
            if isinstance(source, str) and source.strip():
                return source.strip().lower()
            return None

        @staticmethod
        def _extract_artifact_id(artifact: dict[str, Any]) -> str:
            for key in ("artifact_id", "artifactId", "id"):
                value = artifact.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            return "__default_final_answer__"

        @staticmethod
        def _resolve_append(payload: dict[str, Any], artifact: dict[str, Any]) -> bool:
            append = payload.get("append")
            if isinstance(append, bool):
                return append
            artifact_append = artifact.get("append")
            if isinstance(artifact_append, bool):
                return artifact_append
            return True

        def consume(self, payload: dict[str, Any]) -> None:
            if payload.get("kind") == "artifact-update":
                artifact = payload.get("artifact")
                if isinstance(artifact, dict):
                    text = self._extract_text_from_parts(artifact.get("parts"))
                    if not text:
                        return
                    channel = self._extract_artifact_channel(artifact)
                    if channel == "final_answer":
                        artifact_id = self._extract_artifact_id(artifact)
                        append = self._resolve_append(payload, artifact)
                        source = self._extract_artifact_source(artifact)
                        overwrite = (not append) or source == "final_snapshot"
                        current = self._final_answer_by_artifact.get(artifact_id, "")
                        self._final_answer_by_artifact[artifact_id] = (
                            text if overwrite else f"{current}{text}"
                        )
                        self._artifact_last_seq[artifact_id] = self._seq
                        self._seq += 1
                        return
                    if channel in {"reasoning", "tool_call"}:
                        artifact_id = self._extract_artifact_id(artifact)
                        append = self._resolve_append(payload, artifact)
                        source = self._extract_artifact_source(artifact)
                        overwrite = (not append) or source == "final_snapshot"
                        bucket = (
                            self._reasoning_by_artifact
                            if channel == "reasoning"
                            else self._tool_call_by_artifact
                        )
                        current = bucket.get(artifact_id, "")
                        bucket[artifact_id] = text if overwrite else f"{current}{text}"
                        self._artifact_last_seq[artifact_id] = self._seq
                        self._seq += 1
                        return
                    self._legacy_chunks.append(text)
                    return

            content = payload.get("content")
            if isinstance(content, str):
                self._legacy_chunks.append(content)
                return
            message = payload.get("message")
            if isinstance(message, str):
                self._legacy_chunks.append(message)

        def result(self) -> str:
            if self._final_answer_by_artifact:
                latest_artifact_id = max(
                    self._artifact_last_seq.items(), key=lambda item: item[1]
                )[0]
                return self._final_answer_by_artifact.get(latest_artifact_id, "")
            return "".join(self._legacy_chunks)

        def _channel_result(self, channel: str) -> str:
            bucket = (
                self._reasoning_by_artifact
                if channel == "reasoning"
                else self._tool_call_by_artifact
            )
            if not bucket:
                return ""
            ordered = sorted(
                bucket.items(),
                key=lambda item: self._artifact_last_seq.get(item[0], -1),
            )
            return "\n\n".join(text for _, text in ordered if text)

        def result_metadata(self) -> dict[str, Any]:
            reasoning = self._channel_result("reasoning")
            tool_call = self._channel_result("tool_call")
            opencode_stream: dict[str, str] = {}
            if reasoning:
                opencode_stream["reasoning"] = reasoning[
                    : self._MAX_CHANNEL_METADATA_CHARS
                ]
            if tool_call:
                opencode_stream["tool_call"] = tool_call[
                    : self._MAX_CHANNEL_METADATA_CHARS
                ]
            if not opencode_stream:
                return {}
            return {"opencode_stream": opencode_stream}

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
        on_complete_metadata: StreamMetadataCallbackFn | None = None,
        on_error: StreamTextCallbackFn | None = None,
        on_event: StreamEventPayloadCallbackFn | None = None,
    ) -> StreamingResponse:
        async def event_generator() -> AsyncIterator[str]:
            stream_text_accumulator = self._StreamTextAccumulator()
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
                    stream_text_accumulator.consume(serialized)
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
                    await self._call_callback(
                        on_complete, stream_text_accumulator.result()
                    )
                    await self._call_callback(
                        on_complete_metadata,
                        stream_text_accumulator.result_metadata(),
                    )
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
        on_complete_metadata: StreamMetadataCallbackFn | None = None,
        on_error: StreamTextCallbackFn | None = None,
        on_event: StreamEventPayloadCallbackFn | None = None,
    ) -> None:
        stream_text_accumulator = self._StreamTextAccumulator()
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
                stream_text_accumulator.consume(serialized)
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
                await self._call_callback(on_complete, stream_text_accumulator.result())
                await self._call_callback(
                    on_complete_metadata,
                    stream_text_accumulator.result_metadata(),
                )
            await websocket.send_text(json_dumps({"event": "stream_end", "data": {}}))


a2a_invoke_service = A2AInvokeService()

__all__ = ["A2AInvokeService", "a2a_invoke_service"]
