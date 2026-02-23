"""Shared helpers for invoking A2A agents across different catalogs.

The hub (admin-managed) and user-managed A2A routes should share streaming
transport logic to keep behavior consistent and reduce drift.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import time
from contextlib import suppress
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
StreamErrorMetadataCallbackFn = Callable[[dict[str, Any]], Any]


class A2AInvokeService:
    """Transport-level helpers for blocking/SSE/WS A2A invocation."""

    # Keep client-facing stream errors generic. Internal errors go to logs.
    _STREAM_ERROR_MESSAGE = "Upstream streaming failed"
    _STREAM_ERROR_CODE = "upstream_stream_error"
    _SSE_HEARTBEAT_FRAME = ": keep-alive\n\n"
    _WS_HEARTBEAT_EVENT = {"event": "heartbeat", "data": {}}
    _WS_STREAM_END_EVENT = {"event": "stream_end", "data": {}}
    _ERROR_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,64}$")

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

    async def send_ws_stream_end(self, websocket: WebSocket) -> None:
        await websocket.send_text(
            json_dumps(self._WS_STREAM_END_EVENT, ensure_ascii=False)
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

    @staticmethod
    def _pick_non_empty_str(
        payload: dict[str, Any],
        keys: tuple[str, ...],
    ) -> str | None:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _pick_int(payload: dict[str, Any], keys: tuple[str, ...]) -> int | None:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, int):
                return value
            if isinstance(value, float) and value.is_integer():
                return int(value)
            if isinstance(value, str) and value.strip().lstrip("-").isdigit():
                return int(value.strip())
        return None

    @classmethod
    def _extract_event_sequence(cls, payload: dict[str, Any]) -> int | None:
        direct_sequence = cls._pick_int(
            payload, ("seq", "event_seq", "sequence", "eventSeq")
        )
        if direct_sequence is not None:
            return direct_sequence

        metadata = as_dict(payload.get("metadata"))
        artifact = as_dict(payload.get("artifact"))

        candidates = (
            metadata,
            as_dict(metadata.get("opencode")),
            as_dict(artifact),
            as_dict(artifact.get("metadata")),
            as_dict(as_dict(artifact.get("metadata")).get("opencode")),
            as_dict(metadata.get("a2a")),
        )
        for candidate in candidates:
            if not candidate:
                continue
            candidate_sequence = cls._pick_int(
                candidate, ("seq", "event_seq", "sequence", "eventSeq")
            )
            if candidate_sequence is not None:
                return candidate_sequence

        return None

    @staticmethod
    def _pick_number(payload: dict[str, Any], keys: tuple[str, ...]) -> float | None:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                raw = value.strip()
                if not raw:
                    continue
                try:
                    return float(raw)
                except ValueError:
                    continue
        return None

    @classmethod
    def _extract_usage_from_candidate(cls, payload: dict[str, Any]) -> dict[str, Any]:
        if not payload:
            return {}

        direct_usage = as_dict(payload.get("usage"))
        metadata = as_dict(payload.get("metadata"))
        opencode = as_dict(metadata.get("opencode"))
        nested_usage = as_dict(opencode.get("usage"))

        usage_payload: dict[str, Any] = {}
        if direct_usage:
            usage_payload.update(direct_usage)
        if nested_usage:
            usage_payload.update(nested_usage)
        if not usage_payload:
            return {}

        normalized: dict[str, Any] = {}
        token_field_map: dict[str, tuple[str, ...]] = {
            "input_tokens": ("input_tokens", "inputTokens"),
            "output_tokens": ("output_tokens", "outputTokens"),
            "total_tokens": ("total_tokens", "totalTokens"),
            "reasoning_tokens": ("reasoning_tokens", "reasoningTokens"),
            "cache_tokens": ("cache_tokens", "cacheTokens"),
        }
        for field_name, keys in token_field_map.items():
            value = cls._pick_int(usage_payload, keys)
            if value is not None and value >= 0:
                normalized[field_name] = value

        cost = cls._pick_number(usage_payload, ("cost",))
        if cost is not None and cost >= 0:
            normalized["cost"] = cost
        return normalized

    @classmethod
    def _extract_usage_hints_from_payload(
        cls, payload: dict[str, Any]
    ) -> dict[str, Any]:
        root = as_dict(payload)
        artifact = as_dict(root.get("artifact"))
        message = as_dict(root.get("message"))
        status = as_dict(root.get("status"))
        status_message = as_dict(status.get("message"))
        task = as_dict(root.get("task"))
        task_status = as_dict(task.get("status"))
        task_status_message = as_dict(task_status.get("message"))
        result = as_dict(root.get("result"))
        result_status = as_dict(result.get("status"))
        result_status_message = as_dict(result_status.get("message"))

        usage: dict[str, Any] = {}
        for candidate in (
            root,
            artifact,
            message,
            status,
            status_message,
            task,
            task_status,
            task_status_message,
            result,
            result_status,
            result_status_message,
        ):
            candidate_usage = cls._extract_usage_from_candidate(candidate)
            if candidate_usage:
                for k, v in candidate_usage.items():
                    if v is not None:
                        usage[k] = v
        return usage

    @classmethod
    def _extract_stream_identity_hints_from_payload(
        cls, payload: dict[str, Any]
    ) -> dict[str, Any]:
        root = as_dict(payload)
        artifact = as_dict(root.get("artifact"))
        artifact_metadata = as_dict(artifact.get("metadata"))
        opencode_metadata = as_dict(artifact_metadata.get("opencode"))
        message = as_dict(root.get("message"))
        status = as_dict(root.get("status"))
        status_message = as_dict(status.get("message"))
        task = as_dict(root.get("task"))
        task_status = as_dict(task.get("status"))
        task_status_message = as_dict(task_status.get("message"))
        result = as_dict(root.get("result"))
        result_status = as_dict(result.get("status"))
        result_status_message = as_dict(result_status.get("message"))

        message_id = None
        event_id = None
        event_seq = None
        for candidate in (
            root,
            artifact,
            opencode_metadata,
            message,
            status_message,
            task_status_message,
            result,
            result_status_message,
        ):
            if message_id is None:
                message_id = cls._pick_non_empty_str(
                    candidate, ("message_id", "messageId")
                )
            if event_id is None:
                event_id = cls._pick_non_empty_str(candidate, ("event_id", "eventId"))
            if event_seq is None:
                event_seq = cls._pick_int(
                    candidate,
                    ("seq", "event_seq", "sequence", "eventSeq"),
                )

        hints: dict[str, Any] = {}
        if message_id:
            hints["upstream_message_id"] = message_id
        if event_id:
            hints["upstream_event_id"] = event_id
        if event_seq is not None:
            hints["upstream_event_seq"] = event_seq
        return hints

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
                ) = extract_provider_and_external_session_id(candidate)
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
            ) = extract_provider_and_external_session_id(resolved_metadata)
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
    def extract_stream_identity_hints_from_serialized_event(
        cls, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return cls._extract_stream_identity_hints_from_payload(payload)

    @classmethod
    def extract_usage_hints_from_serialized_event(
        cls, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return cls._extract_usage_hints_from_payload(payload)

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

    @classmethod
    def extract_stream_identity_hints_from_invoke_result(
        cls, result: dict[str, Any]
    ) -> dict[str, Any]:
        hints = cls._extract_stream_identity_hints_from_payload(result)
        raw_payload = cls._coerce_payload_to_dict(result.get("raw"))
        if raw_payload:
            hints.update(cls._extract_stream_identity_hints_from_payload(raw_payload))
        return hints

    @classmethod
    def extract_usage_hints_from_invoke_result(
        cls, result: dict[str, Any]
    ) -> dict[str, Any]:
        usage_hints = cls._extract_usage_hints_from_payload(result)
        raw_payload = cls._coerce_payload_to_dict(result.get("raw"))
        if raw_payload:
            raw_usage_hints = cls._extract_usage_hints_from_payload(raw_payload)
            if raw_usage_hints:
                usage_hints = raw_usage_hints
        return usage_hints

    @staticmethod
    def _extract_text_from_parts(parts: Any) -> str | None:
        if not isinstance(parts, list):
            return None
        collected: list[str] = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                collected.append(text)
                continue
            content = part.get("content")
            if isinstance(content, str) and content.strip():
                collected.append(content)
        if collected:
            return "".join(collected)
        return None

    @classmethod
    def _extract_preferred_text_from_payload(cls, payload: Any) -> str | None:
        root = as_dict(payload)
        if not root:
            return None

        direct_text = cls._pick_non_empty_str(root, ("text", "content", "message"))
        if direct_text:
            return direct_text

        parts_text = cls._extract_text_from_parts(root.get("parts"))
        if parts_text:
            return parts_text

        artifact = as_dict(root.get("artifact"))
        if artifact:
            artifact_text = cls._extract_text_from_parts(artifact.get("parts"))
            if artifact_text:
                return artifact_text

        artifacts = root.get("artifacts")
        if isinstance(artifacts, list):
            for artifact_item in reversed(artifacts):
                artifact_text = cls._extract_preferred_text_from_payload(artifact_item)
                if artifact_text:
                    return artifact_text

        history = root.get("history")
        if isinstance(history, list):
            for entry in reversed(history):
                entry_root = as_dict(entry)
                if not entry_root:
                    continue
                role = cls._pick_non_empty_str(entry_root, ("role",))
                if role and role.lower() in {"agent", "assistant", "model"}:
                    history_text = cls._extract_preferred_text_from_payload(entry_root)
                    if history_text:
                        return history_text
            for entry in reversed(history):
                history_text = cls._extract_preferred_text_from_payload(entry)
                if history_text:
                    return history_text

        for key in ("status", "result", "message"):
            nested = as_dict(root.get(key))
            if nested:
                nested_text = cls._extract_preferred_text_from_payload(nested)
                if nested_text:
                    return nested_text

        return None

    @classmethod
    def extract_readable_content_from_invoke_result(
        cls, result: dict[str, Any]
    ) -> str | None:
        raw_payload = cls._coerce_payload_to_dict(result.get("raw"))
        if raw_payload:
            raw_text = cls._extract_preferred_text_from_payload(raw_payload)
            if raw_text:
                return raw_text

        content = result.get("content")
        if isinstance(content, str) and content.strip():
            stripped = content.strip()
            if stripped[:1] in {"{", "["}:
                try:
                    parsed = json.loads(stripped)
                except Exception:
                    return stripped
                parsed_text = cls._extract_preferred_text_from_payload(parsed)
                if parsed_text:
                    return parsed_text
            return stripped
        return None

    class _StreamTextAccumulator:
        """Accumulates stream text for persistence.

        For typed artifact updates:
        - aggregate ordered message blocks by `block_type`
        - same type appends; switched type starts a new block
        - preserve append/overwrite semantics per update
        - accepted values: `text`, `reasoning`, `tool_call`

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
            _payload: dict[str, Any], artifact: dict[str, Any]
        ) -> str | None:
            metadata = artifact.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
            opencode = metadata.get("opencode") if isinstance(metadata, dict) else None
            opencode = opencode if isinstance(opencode, dict) else {}
            raw = opencode.get("block_type")
            if not isinstance(raw, str) or not raw.strip():
                return None
            normalized = raw.strip().lower()
            if normalized in {"text", "reasoning", "tool_call"}:
                return normalized
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

        def _push_new_block(self, block_type: str, delta: str, done: bool) -> None:
            now = self._block_seq
            self._block_seq += 1
            self._blocks.append(
                {
                    "id": f"block-{now + 1}",
                    "type": block_type,
                    "content": delta,
                    "is_finished": done,
                    "seq": now,
                }
            )

        def _apply_block_update(
            self,
            *,
            block_type: str,
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
                    and last.get("type") == block_type
                    and last.get("is_finished") is False
                ):
                    last["content"] = delta
                    last["is_finished"] = done
                    return
                if isinstance(last, dict) and last.get("is_finished") is False:
                    last["is_finished"] = True
                self._push_new_block(block_type, delta, done)
                return

            if (
                isinstance(last, dict)
                and last.get("type") == block_type
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
            self._push_new_block(block_type, delta, done)

        def consume(self, payload: dict[str, Any]) -> None:
            if payload.get("kind") == "artifact-update":
                artifact = payload.get("artifact")
                if isinstance(artifact, dict):
                    block_type = self._extract_artifact_type(payload, artifact)
                    if block_type:
                        delta = self._extract_delta(payload, artifact)
                        if not delta:
                            return
                        append = self._resolve_append(payload, artifact)
                        done = self._resolve_done(payload, artifact)
                        source = self._extract_artifact_source(artifact)
                        self._apply_block_update(
                            block_type=block_type,
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

        if isinstance(resolved, dict):
            payload = dict(resolved)
        else:
            payload = resolved.model_dump(exclude_none=True)
        if settings.debug:
            payload["validation_errors"] = validate_message(payload)
        return payload

    @staticmethod
    def _extract_artifact_validation_errors(
        payload: dict[str, Any], *, validate_message: ValidateMessageFn
    ) -> list[str]:
        if payload.get("kind") != "artifact-update":
            return []
        return [str(item) for item in validate_message(payload)]

    @staticmethod
    def _is_terminal_status_event(payload: dict[str, Any]) -> bool:
        return payload.get("kind") == "status-update" and payload.get("final") is True

    @staticmethod
    def _stream_heartbeat_interval_seconds() -> float:
        from app.core.config import settings

        interval = float(settings.a2a_stream_heartbeat_interval)
        if interval <= 0:
            return 0.0
        return interval

    @classmethod
    def _extract_error_code_from_exception(cls, exc: BaseException) -> str | None:
        candidate = getattr(exc, "error_code", None)
        normalized = cls._normalize_error_code(candidate)
        if normalized is not None:
            return normalized

        detail = getattr(exc, "detail", None)
        normalized = cls._normalize_error_code(detail)
        if normalized is not None:
            return normalized

        candidate = getattr(exc, "code", None)
        normalized = cls._normalize_error_code(candidate)
        if normalized is not None:
            return normalized

        for arg in getattr(exc, "args", ()):
            if isinstance(arg, dict):
                mapped = arg.get("error_code") or arg.get("code")
                normalized = cls._normalize_error_code(mapped)
                if normalized is not None:
                    return normalized
                if isinstance(mapped, int):
                    return str(mapped)
            normalized = cls._normalize_error_code(arg)
            if normalized is not None:
                return normalized

        return None

    @classmethod
    def _normalize_error_code(cls, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        candidate = value.strip().replace("-", "_").lower()
        if not cls._ERROR_CODE_PATTERN.fullmatch(candidate):
            return None
        return candidate

    async def _iter_stream_events_with_heartbeat(
        self,
        stream: AsyncIterator[StreamEvent],
        *,
        heartbeat_interval_seconds: float,
    ) -> AsyncIterator[StreamEvent | None]:
        stream_iter = stream.__aiter__()
        next_event_task: asyncio.Task[StreamEvent] = asyncio.create_task(
            anext(stream_iter)
        )
        try:
            while True:
                if heartbeat_interval_seconds > 0:
                    done, _ = await asyncio.wait(
                        {next_event_task},
                        timeout=heartbeat_interval_seconds,
                    )
                    if not done:
                        yield None
                        continue
                else:
                    await next_event_task

                try:
                    event = next_event_task.result()
                except StopAsyncIteration:
                    return

                next_event_task = asyncio.create_task(anext(stream_iter))
                yield event
        finally:
            if not next_event_task.done():
                next_event_task.cancel()
                with suppress(asyncio.CancelledError):
                    await next_event_task

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
        resume_from_sequence: int | None = None,
        cache_key: str | None = None,
    ) -> StreamingResponse:
        from app.services.stream_cache.memory_cache import global_stream_cache

        async def event_generator() -> AsyncIterator[str]:
            stream_text_accumulator = self._StreamTextAccumulator()
            stream_failed = False
            heartbeat_interval_seconds = self._stream_heartbeat_interval_seconds()

            # Replay cached events if resuming
            seq_counter = 0
            if resume_from_sequence is not None and cache_key:
                cached_events = (
                    await global_stream_cache.get_events_with_sequence_after(
                        cache_key, resume_from_sequence
                    )
                )
                for cached_sequence, cached_event in cached_events:
                    parsed_sequence = self._extract_event_sequence(cached_event)
                    if parsed_sequence is not None:
                        seq_counter = max(seq_counter, parsed_sequence)
                    else:
                        seq_counter = max(seq_counter, cached_sequence)
                    stream_text_accumulator.consume(cached_event)
                    yield f"data: {json_dumps(cached_event, ensure_ascii=False)}\n\n"

                # Continue generating sequence from max of cached or resumed
                seq_counter = max(seq_counter, resume_from_sequence)
            serialized = {}

            try:
                async for event in self._iter_stream_events_with_heartbeat(
                    gateway.stream(
                        resolved=resolved,
                        query=query,
                        context_id=context_id,
                        metadata=metadata,
                    ),
                    heartbeat_interval_seconds=heartbeat_interval_seconds,
                ):
                    if event is None:
                        yield self._SSE_HEARTBEAT_FRAME
                        continue
                    serialized = self.serialize_stream_event(
                        event, validate_message=validate_message
                    )
                    validation_errors = self._extract_artifact_validation_errors(
                        serialized,
                        validate_message=validate_message,
                    )
                    if validation_errors:
                        logger.warning(
                            "Dropped invalid artifact-update event",
                            extra={
                                **log_extra,
                                "validation_error_count": len(validation_errors),
                            },
                        )
                        continue

                    parsed_sequence = self._extract_event_sequence(serialized)
                    event_sequence = (
                        parsed_sequence
                        if parsed_sequence is not None
                        else seq_counter + 1
                    )
                    if event_sequence <= seq_counter:
                        event_sequence = seq_counter + 1

                    # If this event sequence was already replayed from cache, skip yielding it again
                    # This happens if upstream didn't support resume and gave us everything from start
                    if (
                        resume_from_sequence is not None
                        and event_sequence <= resume_from_sequence
                    ):
                        continue
                    seq_counter = max(seq_counter, event_sequence)

                    if cache_key:
                        await global_stream_cache.append_event(
                            cache_key, serialized, seq_counter
                        )

                    await self._call_callback(on_event, serialized)
                    stream_text_accumulator.consume(serialized)
                    yield f"data: {json_dumps(serialized, ensure_ascii=False)}\n\n"
                    if self._is_terminal_status_event(serialized):
                        break
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
                if cache_key and self._is_terminal_status_event(serialized):
                    await global_stream_cache.mark_completed(cache_key)
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
        on_error_metadata: StreamErrorMetadataCallbackFn | None = None,
        send_stream_end: bool = True,
        resume_from_sequence: int | None = None,
        cache_key: str | None = None,
    ) -> None:
        from app.services.stream_cache.memory_cache import global_stream_cache

        stream_text_accumulator = self._StreamTextAccumulator()
        stream_failed = False
        heartbeat_interval_seconds = self._stream_heartbeat_interval_seconds()

        # Replay cached events if resuming
        seq_counter = 0
        if resume_from_sequence is not None and cache_key:
            cached_events = await global_stream_cache.get_events_with_sequence_after(
                cache_key, resume_from_sequence
            )
            for cached_sequence, cached_event in cached_events:
                parsed_sequence = self._extract_event_sequence(cached_event)
                if parsed_sequence is not None:
                    seq_counter = max(seq_counter, parsed_sequence)
                else:
                    seq_counter = max(seq_counter, cached_sequence)
                stream_text_accumulator.consume(cached_event)
                await websocket.send_text(json_dumps(cached_event, ensure_ascii=False))

            # Continue generating sequence from max of cached or resumed
            seq_counter = max(seq_counter, resume_from_sequence)

        serialized = {}
        try:
            async for event in self._iter_stream_events_with_heartbeat(
                gateway.stream(
                    resolved=resolved,
                    query=query,
                    context_id=context_id,
                    metadata=metadata,
                ),
                heartbeat_interval_seconds=heartbeat_interval_seconds,
            ):
                if event is None:
                    await websocket.send_text(
                        json_dumps(self._WS_HEARTBEAT_EVENT, ensure_ascii=False)
                    )
                    continue
                serialized = self.serialize_stream_event(
                    event, validate_message=validate_message
                )
                validation_errors = self._extract_artifact_validation_errors(
                    serialized,
                    validate_message=validate_message,
                )
                if validation_errors:
                    logger.warning(
                        "Dropped invalid artifact-update event",
                        extra={
                            **log_extra,
                            "validation_error_count": len(validation_errors),
                        },
                    )
                    continue

                parsed_sequence = self._extract_event_sequence(serialized)
                event_sequence = (
                    parsed_sequence if parsed_sequence is not None else seq_counter + 1
                )
                if event_sequence <= seq_counter:
                    event_sequence = seq_counter + 1
                if (
                    resume_from_sequence is not None
                    and event_sequence <= resume_from_sequence
                ):
                    continue
                seq_counter = max(seq_counter, event_sequence)

                if cache_key:
                    await global_stream_cache.append_event(
                        cache_key, serialized, seq_counter
                    )

                await self._call_callback(on_event, serialized)
                stream_text_accumulator.consume(serialized)
                await websocket.send_text(json_dumps(serialized, ensure_ascii=False))
                if self._is_terminal_status_event(serialized):
                    break
        except Exception as exc:
            stream_failed = True
            logger.warning("A2A WS stream failed", exc_info=True, extra=log_extra)
            error_code = (
                self._extract_error_code_from_exception(exc) or self._STREAM_ERROR_CODE
            )
            error_payload = {
                "message": self._STREAM_ERROR_MESSAGE,
                "error_code": error_code,
            }
            await self._call_callback(on_error, self._STREAM_ERROR_MESSAGE)
            await self._call_callback(on_error_metadata, error_payload)
            await self.send_ws_error(
                websocket,
                message=self._STREAM_ERROR_MESSAGE,
                error_code=error_code,
            )
        finally:
            if cache_key and self._is_terminal_status_event(serialized):
                await global_stream_cache.mark_completed(cache_key)
            if not stream_failed:
                await self._call_callback(
                    on_complete_metadata,
                    stream_text_accumulator.result_metadata(),
                )
                await self._call_callback(on_complete, stream_text_accumulator.result())
            if send_stream_end:
                await self.send_ws_stream_end(websocket)

    async def consume_stream(
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
        on_error_metadata: StreamErrorMetadataCallbackFn | None = None,
        idle_timeout_seconds: float | None = None,
        total_timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        stream_text_accumulator = self._StreamTextAccumulator()
        log_warning = getattr(logger, "warning", None)
        log_info = getattr(logger, "info", None)
        started_at = time.monotonic()
        last_event_at = started_at
        heartbeat_interval_seconds = self._stream_heartbeat_interval_seconds()
        stream_iter = self._iter_stream_events_with_heartbeat(
            gateway.stream(
                resolved=resolved,
                query=query,
                context_id=context_id,
                metadata=metadata,
            ),
            heartbeat_interval_seconds=heartbeat_interval_seconds,
        ).__aiter__()
        terminal_event_seen = False
        serialized: dict[str, Any] = {}
        idle_timeout = (
            float(idle_timeout_seconds)
            if idle_timeout_seconds is not None and idle_timeout_seconds > 0
            else None
        )
        total_timeout = (
            float(total_timeout_seconds)
            if total_timeout_seconds is not None and total_timeout_seconds > 0
            else None
        )

        def _resolve_wait_timeout(now: float) -> float | None:
            wait_timeout = idle_timeout
            if total_timeout is not None:
                remaining_total = total_timeout - (now - started_at)
                if remaining_total <= 0:
                    raise asyncio.TimeoutError("total_timeout")
                wait_timeout = (
                    min(wait_timeout, remaining_total)
                    if wait_timeout is not None
                    else remaining_total
                )
            return wait_timeout

        try:
            while True:
                now = time.monotonic()
                wait_timeout = _resolve_wait_timeout(now)
                try:
                    if wait_timeout is None:
                        event = await anext(stream_iter)
                    else:
                        event = await asyncio.wait_for(anext(stream_iter), wait_timeout)
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError:
                    if total_timeout is not None and (
                        time.monotonic() - started_at
                    ) >= (total_timeout - 1e-9):
                        timeout_message = (
                            f"A2A stream total timeout after {total_timeout:.1f}s"
                        )
                    else:
                        idle_value = idle_timeout if idle_timeout is not None else 0.0
                        timeout_message = (
                            f"A2A stream idle timeout after {idle_value:.1f}s"
                        )
                    await self._call_callback(on_error, timeout_message)
                    await self._call_callback(
                        on_error_metadata,
                        {"message": timeout_message, "error_code": "timeout"},
                    )
                    return {
                        "success": False,
                        "content": None,
                        "error": timeout_message,
                        "error_code": "timeout",
                    }
                if event is None:
                    # Align with realtime stream semantics:
                    # heartbeat frames indicate the upstream connection is still alive
                    # and should refresh the idle timer.
                    last_event_at = time.monotonic()
                    continue

                serialized = self.serialize_stream_event(
                    event, validate_message=validate_message
                )
                validation_errors = self._extract_artifact_validation_errors(
                    serialized, validate_message=validate_message
                )
                if validation_errors:
                    warning_payload = {
                        **log_extra,
                        "validation_error_count": len(validation_errors),
                    }
                    if callable(log_warning):
                        log_warning(
                            "Dropped invalid artifact-update event",
                            extra=warning_payload,
                        )
                    elif callable(log_info):
                        log_info(
                            "Dropped invalid artifact-update event",
                            extra=warning_payload,
                        )
                    continue

                last_event_at = time.monotonic()
                await self._call_callback(on_event, serialized)
                stream_text_accumulator.consume(serialized)
                if self._is_terminal_status_event(serialized):
                    terminal_event_seen = True
                    break

            await self._call_callback(
                on_complete_metadata,
                stream_text_accumulator.result_metadata(),
            )
            await self._call_callback(on_complete, stream_text_accumulator.result())
            return {
                "success": True,
                "content": stream_text_accumulator.result(),
                "error": None,
                "error_code": None,
                "finished_with_terminal_event": terminal_event_seen,
                "elapsed_seconds": time.monotonic() - started_at,
                "idle_seconds": max(time.monotonic() - last_event_at, 0.0),
            }
        except Exception as exc:
            if callable(log_warning):
                log_warning(
                    "A2A consume stream failed",
                    exc_info=True,
                    extra=log_extra,
                )
            elif callable(log_info):
                log_info(
                    "A2A consume stream failed",
                    exc_info=True,
                    extra=log_extra,
                )
            error_code = self._extract_error_code_from_exception(exc)
            await self._call_callback(on_error, self._STREAM_ERROR_MESSAGE)
            await self._call_callback(
                on_error_metadata,
                {"message": self._STREAM_ERROR_MESSAGE, "error_code": error_code},
            )
            return {
                "success": False,
                "content": None,
                "error": self._STREAM_ERROR_MESSAGE,
                "error_code": error_code or self._STREAM_ERROR_CODE,
            }


a2a_invoke_service = A2AInvokeService()

__all__ = ["A2AInvokeService", "a2a_invoke_service"]
