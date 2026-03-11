"""Shared helpers for invoking A2A agents across different catalogs.

The hub (admin-managed) and user-managed A2A routes should share streaming
transport logic to keep behavior consistent and reduce drift.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
import time
from contextlib import suppress
from dataclasses import dataclass
from enum import Enum
from typing import Any, AsyncIterator, Callable

from a2a.client.client import ClientEvent
from a2a.types import Message
from fastapi import WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from app.utils.json_encoder import json_dumps
from app.utils.payload_extract import (
    as_dict,
    extract_context_id,
    extract_provider_and_external_session_id,
)

logger = logging.getLogger(__name__)

StreamEvent = ClientEvent | Message
ValidateMessageFn = Callable[[dict[str, Any]], list[Any]]
StreamTextCallbackFn = Callable[[str], Any]
StreamEventPayloadCallbackFn = Callable[[dict[str, Any]], Any]
StreamMetadataCallbackFn = Callable[[dict[str, Any]], Any]
StreamErrorMetadataCallbackFn = Callable[[dict[str, Any]], Any]


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


@dataclass(frozen=True)
class PayloadAnalysis:
    """Unified container for extracted payload metadata."""

    usage: dict[str, Any]
    upstream_message_id: str | None = None
    upstream_event_id: str | None = None
    upstream_event_seq: int | None = None
    upstream_task_id: str | None = None
    context_id: str | None = None
    binding_metadata: dict[str, Any] = None


StreamFinalizedCallbackFn = Callable[[StreamOutcome], Any]


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
        try:
            await websocket.send_text(
                json_dumps(
                    self.build_ws_error_event(message=message, error_code=error_code),
                    ensure_ascii=False,
                )
            )
        except Exception as exc:
            if self._is_client_disconnect_error(exc):
                return
            raise

    async def send_ws_stream_end(self, websocket: WebSocket) -> None:
        try:
            await websocket.send_text(
                json_dumps(self._WS_STREAM_END_EVENT, ensure_ascii=False)
            )
        except Exception as exc:
            if self._is_client_disconnect_error(exc):
                return
            raise

    @staticmethod
    def _is_client_disconnect_error(exc: Exception) -> bool:
        if isinstance(exc, WebSocketDisconnect):
            return True
        class_name = exc.__class__.__name__
        if class_name in {
            "ClientDisconnected",
            "ConnectionClosed",
            "ConnectionClosedOK",
        }:
            return True
        if (
            isinstance(exc, RuntimeError)
            and "close message has been sent" in str(exc).lower()
        ):
            return True
        return False

    @staticmethod
    async def _call_callback(callback: Callable[[Any], Any] | None, value: Any) -> None:
        if callback is None:
            return
        outcome = callback(value)
        if inspect.isawaitable(outcome):
            await outcome

    @staticmethod
    async def _call_callback_safely(
        callback: Callable[[Any], Any] | None,
        value: Any,
        *,
        logger: Any,
        log_extra: dict[str, Any],
        warning_message: str,
    ) -> None:
        try:
            await A2AInvokeService._call_callback(callback, value)
        except Exception:
            log_warning = getattr(logger, "warning", None)
            if callable(log_warning):
                log_warning(warning_message, exc_info=True, extra=log_extra)
                return
            logging.getLogger(__name__).warning(
                warning_message,
                exc_info=True,
                extra=log_extra,
            )

    @classmethod
    def analyze_payload(cls, payload: dict[str, Any]) -> PayloadAnalysis:
        """Analyze a payload to extract all relevant metadata in a single pass."""
        root = as_dict(payload)

        # 1. Identity & Sequence hints (Candidates for identity)
        artifact = as_dict(root.get("artifact"))
        artifact_metadata = as_dict(artifact.get("metadata"))
        artifact_opencode = as_dict(artifact_metadata.get("opencode"))

        message = as_dict(root.get("message"))
        message_metadata = as_dict(message.get("metadata"))
        message_opencode = as_dict(message_metadata.get("opencode"))

        status = as_dict(root.get("status"))
        status_metadata = as_dict(status.get("metadata"))
        status_opencode = as_dict(status_metadata.get("opencode"))

        task = as_dict(root.get("task"))
        task_status = as_dict(task.get("status"))
        task_status_metadata = as_dict(task_status.get("metadata"))
        task_status_opencode = as_dict(task_status_metadata.get("opencode"))

        result = as_dict(root.get("result"))
        result_status = as_dict(result.get("status"))
        result_status_metadata = as_dict(result_status.get("metadata"))
        result_status_opencode = as_dict(result_status_metadata.get("opencode"))

        root_metadata = as_dict(root.get("metadata"))
        root_opencode = as_dict(root_metadata.get("opencode"))

        # Identity extraction
        msg_id = None
        evt_id = None
        for cand in (
            artifact_opencode,
            root_opencode,
            status_opencode,
            message_opencode,
            task_status_opencode,
            result_status_opencode,
        ):
            if msg_id is None:
                msg_id = cls._pick_non_empty_str(cand, ("message_id",))
            if evt_id is None:
                evt_id = cls._pick_non_empty_str(cand, ("event_id",))

        # Task ID extraction
        t_id = cls._pick_non_empty_str(root, ("task_id", "taskId"))
        if t_id is None:
            for cand in (
                task,
                as_dict(result.get("task")),
                as_dict(status.get("task")),
                root_opencode,
            ):
                t_id = cls._pick_non_empty_str(cand, ("task_id", "taskId", "id"))
                if t_id:
                    break

        # Sequence extraction
        seq = cls._pick_int(root, ("seq",))
        if seq is None:
            for cand in (
                root_metadata,
                root_opencode,
                artifact,
                artifact_metadata,
                artifact_opencode,
            ):
                seq = cls._pick_int(cand, ("seq",))
                if seq is not None:
                    break

        # 2. Usage hints
        usage: dict[str, Any] = {}
        for cand in (root, artifact, message, status, task, result):
            cand_usage = cls._extract_usage_from_candidate(cand)
            if cand_usage:
                usage.update(cand_usage)

        # 3. Binding hints
        context_id = None
        provider = None
        ext_session_id = None
        binding_meta: dict[str, Any] = {}

        for cand in (root, message, result):
            if context_id is None:
                context_id = extract_context_id(cand)

            c_meta = cls._extract_metadata_dict(cand)
            if c_meta:
                binding_meta.update(c_meta)

            if provider is None or ext_session_id is None:
                c_prov, c_ext = extract_provider_and_external_session_id(cand)
                if provider is None:
                    provider = c_prov
                if ext_session_id is None:
                    ext_session_id = c_ext

        if context_id is None:
            context_id = extract_context_id(binding_meta)
        if provider is None or ext_session_id is None:
            m_prov, m_ext = extract_provider_and_external_session_id(binding_meta)
            if provider is None:
                provider = m_prov
            if ext_session_id is None:
                ext_session_id = m_ext

        if provider:
            binding_meta["provider"] = provider
        if ext_session_id:
            binding_meta["externalSessionId"] = ext_session_id

        return PayloadAnalysis(
            usage=usage,
            upstream_message_id=msg_id,
            upstream_event_id=evt_id,
            upstream_event_seq=seq,
            upstream_task_id=t_id,
            context_id=context_id,
            binding_metadata=binding_meta,
        )

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
    def extract_binding_hints_from_serialized_event(
        cls, payload: dict[str, Any]
    ) -> tuple[str | None, dict[str, Any]]:
        analysis = cls.analyze_payload(payload)
        return analysis.context_id, analysis.binding_metadata

    @classmethod
    def extract_stream_identity_hints_from_serialized_event(
        cls, payload: dict[str, Any]
    ) -> dict[str, Any]:
        analysis = cls.analyze_payload(payload)
        hints: dict[str, Any] = {}
        if analysis.upstream_message_id:
            hints["upstream_message_id"] = analysis.upstream_message_id
        if analysis.upstream_event_id:
            hints["upstream_event_id"] = analysis.upstream_event_id
        if analysis.upstream_event_seq is not None:
            hints["upstream_event_seq"] = analysis.upstream_event_seq
        if analysis.upstream_task_id:
            hints["upstream_task_id"] = analysis.upstream_task_id
        return hints

    @classmethod
    def extract_usage_hints_from_serialized_event(
        cls, payload: dict[str, Any]
    ) -> dict[str, Any]:
        analysis = cls.analyze_payload(payload)
        return analysis.usage

    @classmethod
    def extract_stream_chunk_from_serialized_event(
        cls, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        # Strict OpenCode stream contract: only typed artifact-update events with
        # opencode metadata identity are eligible for chunk persistence.
        if not isinstance(payload, dict) or payload.get("kind") != "artifact-update":
            return None

        artifact = as_dict(payload.get("artifact"))
        if not artifact:
            return None
        artifact_metadata = as_dict(artifact.get("metadata"))
        opencode_metadata = as_dict(artifact_metadata.get("opencode"))

        block_type = cls._StreamTextAccumulator._extract_artifact_type(
            payload, artifact
        )
        if block_type is None:
            return None

        event_id = cls._pick_non_empty_str(opencode_metadata, ("event_id",))
        message_id = cls._pick_non_empty_str(opencode_metadata, ("message_id",))
        if not event_id or not message_id:
            return None

        delta = cls._StreamTextAccumulator._extract_text_from_parts(
            artifact.get("parts")
        )
        if not delta:
            return None

        append = payload.get("append")
        resolved_append = append if isinstance(append, bool) else True

        seq = cls._pick_int(payload, ("seq",))
        source = cls._StreamTextAccumulator._extract_artifact_source(artifact)
        return {
            "event_id": event_id,
            "seq": seq,
            "message_id": message_id,
            "block_type": block_type,
            "content": delta,
            "append": resolved_append,
            "is_finished": payload.get("lastChunk") is True,
            "source": source,
        }

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
            except Exception as exc:
                logger.error("Failed to dump A2A payload", exc_info=True)
                raise ValueError("Payload serialization failed") from exc
            if isinstance(dumped, dict):
                return dumped
        return {}

    @classmethod
    def extract_binding_hints_from_invoke_result(
        cls, result: dict[str, Any]
    ) -> tuple[str | None, dict[str, Any]]:
        analysis = cls.analyze_payload(result)
        context_id = analysis.context_id
        metadata = analysis.binding_metadata

        raw_payload = cls._coerce_payload_to_dict(result.get("raw"))
        if raw_payload:
            raw_analysis = cls.analyze_payload(raw_payload)
            if raw_analysis.context_id:
                context_id = raw_analysis.context_id
            if raw_analysis.binding_metadata:
                metadata.update(raw_analysis.binding_metadata)
        return context_id, metadata

    @classmethod
    def extract_stream_identity_hints_from_invoke_result(
        cls, result: dict[str, Any]
    ) -> dict[str, Any]:
        analysis = cls.analyze_payload(result)
        hints: dict[str, Any] = {}
        if analysis.upstream_message_id:
            hints["upstream_message_id"] = analysis.upstream_message_id
        if analysis.upstream_event_id:
            hints["upstream_event_id"] = analysis.upstream_event_id
        if analysis.upstream_event_seq is not None:
            hints["upstream_event_seq"] = analysis.upstream_event_seq
        if analysis.upstream_task_id:
            hints["upstream_task_id"] = analysis.upstream_task_id

        raw_payload = cls._coerce_payload_to_dict(result.get("raw"))
        if raw_payload:
            raw_analysis = cls.analyze_payload(raw_payload)
            if raw_analysis.upstream_message_id:
                hints["upstream_message_id"] = raw_analysis.upstream_message_id
            if raw_analysis.upstream_event_id:
                hints["upstream_event_id"] = raw_analysis.upstream_event_id
            if raw_analysis.upstream_event_seq is not None:
                hints["upstream_event_seq"] = raw_analysis.upstream_event_seq
            if raw_analysis.upstream_task_id:
                hints["upstream_task_id"] = raw_analysis.upstream_task_id
        return hints

    @classmethod
    def extract_usage_hints_from_invoke_result(
        cls, result: dict[str, Any]
    ) -> dict[str, Any]:
        analysis = cls.analyze_payload(result)
        usage_hints = analysis.usage

        raw_payload = cls._coerce_payload_to_dict(result.get("raw"))
        if raw_payload:
            raw_analysis = cls.analyze_payload(raw_payload)
            if raw_analysis.usage:
                usage_hints = raw_analysis.usage
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

        """

        def __init__(self) -> None:
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
                last["content"] = (
                    f"{current if isinstance(current, str) else ''}{delta}"
                )
                last["is_finished"] = done
                return

            if isinstance(last, dict) and last.get("is_finished") is False:
                last["is_finished"] = True
            self._push_new_block(block_type, delta, done)

        def consume(self, payload: dict[str, Any]) -> None:
            stream_block = A2AInvokeService.extract_stream_chunk_from_serialized_event(
                payload
            )
            if not stream_block:
                return
            block_type = stream_block.get("block_type")
            delta = stream_block.get("content")
            if not isinstance(block_type, str) or not isinstance(delta, str):
                return
            self._apply_block_update(
                block_type=block_type,
                delta=delta,
                append=bool(stream_block.get("append", True)),
                done=bool(stream_block.get("is_finished", False)),
                source=(
                    str(stream_block.get("source"))
                    if isinstance(stream_block.get("source"), str)
                    else None
                ),
            )

        def result(self) -> str:
            return "".join(
                block.get("content", "")
                for block in self._blocks
                if block.get("type") == "text" and isinstance(block.get("content"), str)
            )

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
            else:
                # Consume terminal StopAsyncIteration from finished tasks so event loop
                # doesn't emit "Task exception was never retrieved" warnings.
                with suppress(StopAsyncIteration, asyncio.CancelledError):
                    _ = next_event_task.result()

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
        on_finalized: StreamFinalizedCallbackFn | None = None,
        resume_from_sequence: int | None = None,
        cache_key: str | None = None,
    ) -> StreamingResponse:
        from app.services.stream_cache.memory_cache import global_stream_cache

        async def event_generator() -> AsyncIterator[str]:
            stream_text_accumulator = self._StreamTextAccumulator()
            stream_failed = False
            client_disconnected = False
            started_at = time.monotonic()
            last_event_at = started_at
            terminal_event_seen = False
            final_outcome: StreamOutcome | None = None
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
                    parsed_sequence = self.analyze_payload(
                        cached_event
                    ).upstream_event_seq
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
                        last_event_at = time.monotonic()
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

                    parsed_sequence = self.analyze_payload(
                        serialized
                    ).upstream_event_seq
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

                    await self._call_callback(on_event, serialized)
                    if cache_key:
                        await global_stream_cache.append_event(
                            cache_key, serialized, seq_counter
                        )
                    stream_text_accumulator.consume(serialized)
                    last_event_at = time.monotonic()
                    yield f"data: {json_dumps(serialized, ensure_ascii=False)}\n\n"
                    if self._is_terminal_status_event(serialized):
                        terminal_event_seen = True
                        break
            except asyncio.CancelledError:
                client_disconnected = True
                final_outcome = StreamOutcome(
                    success=False,
                    finish_reason=StreamFinishReason.CLIENT_DISCONNECT,
                    final_text=stream_text_accumulator.result() or "",
                    error_message=None,
                    error_code=None,
                    elapsed_seconds=time.monotonic() - started_at,
                    idle_seconds=max(time.monotonic() - last_event_at, 0.0),
                    terminal_event_seen=terminal_event_seen,
                )
                raise
            except Exception as exc:
                stream_failed = True
                logger.warning("A2A SSE stream failed", exc_info=True, extra=log_extra)
                error_code = (
                    self._extract_error_code_from_exception(exc)
                    or self._STREAM_ERROR_CODE
                )
                final_outcome = StreamOutcome(
                    success=False,
                    finish_reason=StreamFinishReason.UPSTREAM_ERROR,
                    final_text=stream_text_accumulator.result() or "",
                    error_message=self._STREAM_ERROR_MESSAGE,
                    error_code=error_code,
                    elapsed_seconds=time.monotonic() - started_at,
                    idle_seconds=max(time.monotonic() - last_event_at, 0.0),
                    terminal_event_seen=False,
                )
                await self._call_callback(on_error, self._STREAM_ERROR_MESSAGE)
                error_payload = self.build_ws_error_event(
                    message=self._STREAM_ERROR_MESSAGE,
                    error_code=error_code,
                )
                yield (
                    "event: error\n"
                    f"data: {json_dumps(error_payload['data'], ensure_ascii=False)}\n\n"
                )
            finally:
                if cache_key and self._is_terminal_status_event(serialized):
                    await global_stream_cache.mark_completed(cache_key)
                if not stream_failed and not client_disconnected:
                    final_text = stream_text_accumulator.result()
                    await self._call_callback(
                        on_complete_metadata,
                        {},
                    )
                    await self._call_callback(on_complete, final_text)
                    final_outcome = StreamOutcome(
                        success=True,
                        finish_reason=StreamFinishReason.SUCCESS,
                        final_text=final_text,
                        error_message=None,
                        error_code=None,
                        elapsed_seconds=time.monotonic() - started_at,
                        idle_seconds=max(time.monotonic() - last_event_at, 0.0),
                        terminal_event_seen=terminal_event_seen,
                    )
                if final_outcome is not None:
                    await self._call_callback_safely(
                        on_finalized,
                        final_outcome,
                        logger=logger,
                        log_extra=log_extra,
                        warning_message="A2A SSE finalized callback failed",
                    )
                if not client_disconnected:
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
        on_finalized: StreamFinalizedCallbackFn | None = None,
        send_stream_end: bool = True,
        resume_from_sequence: int | None = None,
        cache_key: str | None = None,
    ) -> None:
        from app.services.stream_cache.memory_cache import global_stream_cache

        stream_text_accumulator = self._StreamTextAccumulator()
        client_disconnected = False
        started_at = time.monotonic()
        last_event_at = started_at
        terminal_event_seen = False
        final_outcome: StreamOutcome | None = None
        heartbeat_interval_seconds = self._stream_heartbeat_interval_seconds()

        # Replay cached events if resuming
        seq_counter = 0
        if resume_from_sequence is not None and cache_key:
            cached_events = await global_stream_cache.get_events_with_sequence_after(
                cache_key, resume_from_sequence
            )
            for cached_sequence, cached_event in cached_events:
                parsed_sequence = self.analyze_payload(cached_event).upstream_event_seq
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
                    last_event_at = time.monotonic()
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

                parsed_sequence = self.analyze_payload(serialized).upstream_event_seq
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

                await self._call_callback(on_event, serialized)
                if cache_key:
                    await global_stream_cache.append_event(
                        cache_key, serialized, seq_counter
                    )
                stream_text_accumulator.consume(serialized)
                last_event_at = time.monotonic()
                await websocket.send_text(json_dumps(serialized, ensure_ascii=False))
                if self._is_terminal_status_event(serialized):
                    terminal_event_seen = True
                    break
            final_text = stream_text_accumulator.result()
            await self._call_callback(on_complete_metadata, {})
            await self._call_callback(on_complete, final_text)
            final_outcome = StreamOutcome(
                success=True,
                finish_reason=StreamFinishReason.SUCCESS,
                final_text=final_text,
                error_message=None,
                error_code=None,
                elapsed_seconds=time.monotonic() - started_at,
                idle_seconds=max(time.monotonic() - last_event_at, 0.0),
                terminal_event_seen=terminal_event_seen,
            )
        except asyncio.CancelledError:
            client_disconnected = True
            final_outcome = StreamOutcome(
                success=False,
                finish_reason=StreamFinishReason.CLIENT_DISCONNECT,
                final_text=stream_text_accumulator.result() or "",
                error_message=None,
                error_code=None,
                elapsed_seconds=time.monotonic() - started_at,
                idle_seconds=max(time.monotonic() - last_event_at, 0.0),
                terminal_event_seen=terminal_event_seen,
            )
            raise
        except Exception as exc:
            if self._is_client_disconnect_error(exc):
                client_disconnected = True
                logger.info("A2A WS client disconnected", extra=log_extra)
                final_outcome = StreamOutcome(
                    success=False,
                    finish_reason=StreamFinishReason.CLIENT_DISCONNECT,
                    final_text=stream_text_accumulator.result() or "",
                    error_message=None,
                    error_code=None,
                    elapsed_seconds=time.monotonic() - started_at,
                    idle_seconds=max(time.monotonic() - last_event_at, 0.0),
                    terminal_event_seen=terminal_event_seen,
                )
                return
            logger.warning("A2A WS stream failed", exc_info=True, extra=log_extra)
            error_code = (
                self._extract_error_code_from_exception(exc) or self._STREAM_ERROR_CODE
            )
            error_payload = {
                "message": self._STREAM_ERROR_MESSAGE,
                "error_code": error_code,
            }
            final_outcome = StreamOutcome(
                success=False,
                finish_reason=StreamFinishReason.UPSTREAM_ERROR,
                final_text=stream_text_accumulator.result() or "",
                error_message=self._STREAM_ERROR_MESSAGE,
                error_code=error_code,
                elapsed_seconds=time.monotonic() - started_at,
                idle_seconds=max(time.monotonic() - last_event_at, 0.0),
                terminal_event_seen=False,
            )
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
            if final_outcome is not None:
                await self._call_callback_safely(
                    on_finalized,
                    final_outcome,
                    logger=logger,
                    log_extra=log_extra,
                    warning_message="A2A WS finalized callback failed",
                )
            if send_stream_end and not client_disconnected:
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
        on_finalized: StreamFinalizedCallbackFn | None = None,
        idle_timeout_seconds: float | None = None,
        total_timeout_seconds: float | None = None,
    ) -> StreamOutcome:
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
                    return 0.0
                wait_timeout = (
                    min(wait_timeout, remaining_total)
                    if wait_timeout is not None
                    else remaining_total
                )
            return wait_timeout

        try:
            while True:
                now = time.monotonic()
                if total_timeout is not None and (now - started_at) >= (
                    total_timeout - 1e-9
                ):
                    timeout_message = (
                        f"A2A stream total timeout after {total_timeout:.1f}s"
                    )
                    outcome = StreamOutcome(
                        success=False,
                        finish_reason=StreamFinishReason.TIMEOUT_TOTAL,
                        final_text=stream_text_accumulator.result() or "",
                        error_message=timeout_message,
                        error_code="timeout",
                        elapsed_seconds=time.monotonic() - started_at,
                        idle_seconds=max(time.monotonic() - last_event_at, 0.0),
                        terminal_event_seen=False,
                    )
                    await self._call_callback(on_error, timeout_message)
                    await self._call_callback(
                        on_error_metadata,
                        {"message": timeout_message, "error_code": "timeout"},
                    )
                    await self._call_callback_safely(
                        on_finalized,
                        outcome,
                        logger=logger,
                        log_extra=log_extra,
                        warning_message="A2A consume stream finalized callback failed",
                    )
                    return outcome
                wait_timeout = _resolve_wait_timeout(now)
                try:
                    if wait_timeout is None:
                        event = await anext(stream_iter)
                    else:
                        event = await asyncio.wait_for(anext(stream_iter), wait_timeout)
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError:
                    is_total_timeout = total_timeout is not None and (
                        time.monotonic() - started_at
                    ) >= (total_timeout - 1e-9)
                    if is_total_timeout:
                        timeout_message = (
                            f"A2A stream total timeout after {total_timeout:.1f}s"
                        )
                        finish_reason = StreamFinishReason.TIMEOUT_TOTAL
                    else:
                        idle_value = idle_timeout if idle_timeout is not None else 0.0
                        timeout_message = (
                            f"A2A stream idle timeout after {idle_value:.1f}s"
                        )
                        finish_reason = StreamFinishReason.TIMEOUT_IDLE
                    partial_content = stream_text_accumulator.result()
                    outcome = StreamOutcome(
                        success=False,
                        finish_reason=finish_reason,
                        final_text=partial_content or "",
                        error_message=timeout_message,
                        error_code="timeout",
                        elapsed_seconds=time.monotonic() - started_at,
                        idle_seconds=max(time.monotonic() - last_event_at, 0.0),
                        terminal_event_seen=False,
                    )
                    await self._call_callback(on_error, timeout_message)
                    await self._call_callback(
                        on_error_metadata,
                        {"message": timeout_message, "error_code": "timeout"},
                    )
                    await self._call_callback_safely(
                        on_finalized,
                        outcome,
                        logger=logger,
                        log_extra=log_extra,
                        warning_message="A2A consume stream finalized callback failed",
                    )
                    return outcome
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
                {},
            )
            final_text = stream_text_accumulator.result()
            await self._call_callback(on_complete, final_text)
            outcome = StreamOutcome(
                success=True,
                finish_reason=StreamFinishReason.SUCCESS,
                final_text=final_text,
                error_message=None,
                error_code=None,
                elapsed_seconds=time.monotonic() - started_at,
                idle_seconds=max(time.monotonic() - last_event_at, 0.0),
                terminal_event_seen=terminal_event_seen,
            )
            await self._call_callback_safely(
                on_finalized,
                outcome,
                logger=logger,
                log_extra=log_extra,
                warning_message="A2A consume stream finalized callback failed",
            )
            return outcome
        except asyncio.CancelledError:
            partial_content = stream_text_accumulator.result()
            outcome = StreamOutcome(
                success=False,
                finish_reason=StreamFinishReason.CLIENT_DISCONNECT,
                final_text=partial_content or "",
                error_message=None,
                error_code=None,
                elapsed_seconds=time.monotonic() - started_at,
                idle_seconds=max(time.monotonic() - last_event_at, 0.0),
                terminal_event_seen=terminal_event_seen,
            )
            await self._call_callback_safely(
                on_finalized,
                outcome,
                logger=logger,
                log_extra=log_extra,
                warning_message="A2A consume stream finalized callback failed",
            )
            raise
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
            error_code = (
                self._extract_error_code_from_exception(exc) or self._STREAM_ERROR_CODE
            )
            partial_content = stream_text_accumulator.result()
            outcome = StreamOutcome(
                success=False,
                finish_reason=StreamFinishReason.UPSTREAM_ERROR,
                final_text=partial_content or "",
                error_message=self._STREAM_ERROR_MESSAGE,
                error_code=error_code,
                elapsed_seconds=time.monotonic() - started_at,
                idle_seconds=max(time.monotonic() - last_event_at, 0.0),
                terminal_event_seen=False,
            )
            await self._call_callback(on_error, self._STREAM_ERROR_MESSAGE)
            await self._call_callback(
                on_error_metadata,
                {"message": self._STREAM_ERROR_MESSAGE, "error_code": error_code},
            )
            await self._call_callback_safely(
                on_finalized,
                outcome,
                logger=logger,
                log_extra=log_extra,
                warning_message="A2A consume stream finalized callback failed",
            )
            return outcome


a2a_invoke_service = A2AInvokeService()

__all__ = [
    "A2AInvokeService",
    "StreamFinishReason",
    "StreamOutcome",
    "a2a_invoke_service",
]
