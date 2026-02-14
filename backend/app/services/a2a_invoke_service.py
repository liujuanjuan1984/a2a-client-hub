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

        For typed artifact updates:
        - aggregate ordered message blocks by `content_type`
        - same type appends; switched type starts a new block
        - preserve append/overwrite semantics per update
        - map `final_answer` to `text`

        For non-typed events, keep legacy concatenation behavior.
        """

        def __init__(self) -> None:
            self._legacy_chunks: list[str] = []
            self._blocks: list[dict[str, Any]] = []
            self._block_seq = 0

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
        def _extract_artifact_type(
            payload: dict[str, Any], artifact: dict[str, Any]
        ) -> str | None:
            def _pick(source: Any, keys: tuple[str, ...]) -> str | None:
                if not isinstance(source, dict):
                    return None
                for key in keys:
                    value = source.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip().lower()
                return None

            metadata = artifact.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
            opencode = metadata.get("opencode") if isinstance(metadata, dict) else None
            opencode = opencode if isinstance(opencode, dict) else {}
            raw = (
                _pick(
                    opencode, ("content_type", "contentType", "block_type", "blockType")
                )
                or _pick(
                    artifact,
                    ("content_type", "contentType", "block_type", "blockType"),
                )
                or _pick(
                    payload,
                    ("content_type", "contentType", "block_type", "blockType"),
                )
                or _pick(opencode, ("channel", "stream_channel"))
            )
            if raw == "final_answer":
                return "text"
            return raw

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
        def _resolve_append(payload: dict[str, Any], artifact: dict[str, Any]) -> bool:
            append = payload.get("append")
            if isinstance(append, bool):
                return append
            artifact_append = artifact.get("append")
            if isinstance(artifact_append, bool):
                return artifact_append
            return True

        @staticmethod
        def _resolve_done(payload: dict[str, Any], artifact: dict[str, Any]) -> bool:
            return bool(
                payload.get("lastChunk") is True
                or payload.get("last_chunk") is True
                or artifact.get("lastChunk") is True
                or artifact.get("last_chunk") is True
            )

        @staticmethod
        def _extract_delta(payload: dict[str, Any], artifact: dict[str, Any]) -> str:
            text = A2AInvokeService._StreamTextAccumulator._extract_text_from_parts(
                artifact.get("parts")
            )
            if text:
                return text
            for source in (payload, artifact):
                delta = source.get("delta")
                if isinstance(delta, str):
                    return delta
                content = source.get("content")
                if isinstance(content, str):
                    return content
                raw_text = source.get("text")
                if isinstance(raw_text, str):
                    return raw_text
            return ""

        def _push_new_block(self, content_type: str, delta: str, done: bool) -> None:
            now = self._block_seq
            self._block_seq += 1
            self._blocks.append(
                {
                    "id": f"block-{now + 1}",
                    "type": content_type,
                    "content": delta,
                    "is_finished": done,
                    "seq": now,
                }
            )

        def _apply_block_update(
            self,
            *,
            content_type: str,
            delta: str,
            append: bool,
            done: bool,
            source: str | None,
        ) -> None:
            if not delta:
                return
            overwrite = (not append) or source == "final_snapshot"
            last = self._blocks[-1] if self._blocks else None

            if overwrite:
                if (
                    isinstance(last, dict)
                    and last.get("type") == content_type
                    and last.get("is_finished") is False
                ):
                    last["content"] = delta
                    last["is_finished"] = done
                    return
                if isinstance(last, dict) and last.get("is_finished") is False:
                    last["is_finished"] = True
                self._push_new_block(content_type, delta, done)
                return

            if (
                isinstance(last, dict)
                and last.get("type") == content_type
                and last.get("is_finished") is False
            ):
                current = last.get("content")
                last[
                    "content"
                ] = f"{current if isinstance(current, str) else ''}{delta}"
                last["is_finished"] = done
                return

            if isinstance(last, dict) and last.get("is_finished") is False:
                last["is_finished"] = True
            self._push_new_block(content_type, delta, done)

        def consume(self, payload: dict[str, Any]) -> None:
            if payload.get("kind") == "artifact-update":
                artifact = payload.get("artifact")
                if isinstance(artifact, dict):
                    content_type = self._extract_artifact_type(payload, artifact)
                    if content_type:
                        delta = self._extract_delta(payload, artifact)
                        if not delta:
                            return
                        append = self._resolve_append(payload, artifact)
                        done = self._resolve_done(payload, artifact)
                        source = self._extract_artifact_source(artifact)
                        self._apply_block_update(
                            content_type=content_type,
                            delta=delta,
                            append=append,
                            done=done,
                            source=source,
                        )
                        return
                    text = self._extract_delta(payload, artifact)
                    if text:
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
            if self._blocks:
                return "".join(
                    block.get("content", "")
                    for block in self._blocks
                    if block.get("type") == "text"
                    and isinstance(block.get("content"), str)
                )
            return "".join(self._legacy_chunks)

        def result_metadata(self) -> dict[str, Any]:
            from app.core.config import settings

            max_chars = int(settings.opencode_stream_metadata_max_chars)
            if not self._blocks:
                return {}
            blocks_payload: list[dict[str, Any]] = []
            for block in self._blocks:
                content = block.get("content")
                if not isinstance(content, str) or not content:
                    continue
                blocks_payload.append(
                    {
                        "id": block.get("id"),
                        "type": block.get("type"),
                        "content": content[:max_chars],
                        "is_finished": bool(block.get("is_finished")),
                    }
                )
            if not blocks_payload:
                return {}
            return {"message_blocks": blocks_payload}

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
                        on_complete_metadata,
                        stream_text_accumulator.result_metadata(),
                    )
                    await self._call_callback(
                        on_complete, stream_text_accumulator.result()
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
                await self._call_callback(
                    on_complete_metadata,
                    stream_text_accumulator.result_metadata(),
                )
                await self._call_callback(on_complete, stream_text_accumulator.result())
            await websocket.send_text(json_dumps({"event": "stream_end", "data": {}}))


a2a_invoke_service = A2AInvokeService()

__all__ = ["A2AInvokeService", "a2a_invoke_service"]
