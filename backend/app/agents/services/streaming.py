"""Streaming helpers for AgentService."""

from __future__ import annotations

import asyncio
import sys
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Tuple, Type
from urllib.parse import urlparse

from app.agents.service_types import (
    AgentServiceResult,
    AgentStreamEvent,
    LlmInvocationOverrides,
)
from app.agents.token_tracker import TokenUsage
from app.core.config import settings
from app.core.logging import get_logger, log_exception
from app.services.incident_alerts import report_llm_failure
from app.utils.debug_utils import debug_manager
from app.utils.timezone_util import utc_now_iso

logger = get_logger(__name__)


@asynccontextmanager
async def litellm_call_context(
    *,
    logger,
    operation_name: str,
    timeout: int,
    error_cls: Type[Exception],
    extra_context: Optional[Dict[str, Any]] = None,
) -> Tuple[float, Dict[str, Any]]:
    """Unified LiteLLM call exception handling context."""

    start_time = time.time()
    context = {"operation": operation_name, "timeout": timeout, **(extra_context or {})}

    try:
        logger.info("Starting %s with timeout=%ss", operation_name, timeout)
        yield start_time, context
    except asyncio.TimeoutError as exc:
        duration = time.time() - start_time
        error_msg = (
            f"{operation_name} timed out after {timeout}s (actual: {duration:.3f}s)"
        )
        logger.error(error_msg)
        log_exception(logger, f"{operation_name} timeout details", sys.exc_info())
        incident_context = dict(context)
        incident_context["duration"] = duration
        await report_llm_failure(operation_name, exc, context=incident_context)
        raise error_cls(error_msg)
    except Exception as exc:  # pragma: no cover - defensive logging
        duration = time.time() - start_time
        error_msg = f"{operation_name} failed after {duration:.3f}s: {type(exc).__name__}: {str(exc)}"
        logger.error(error_msg)
        log_exception(logger, f"{operation_name} error details", sys.exc_info())

        if debug_manager.is_debug_enabled():
            debug_info = {
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "duration": duration,
                **context,
            }
            logger.debug("Debug info: %s", debug_info)

        incident_context = dict(context)
        incident_context["duration"] = duration
        await report_llm_failure(operation_name, exc, context=incident_context)
        raise error_cls(error_msg)
    finally:
        duration = time.time() - start_time
        logger.info("%s completed in %.3fs", operation_name, duration)


async def stream_with_heartbeat(
    source: AsyncIterator[AgentStreamEvent],
    *,
    interval: float,
    context: Dict[str, Any],
) -> AsyncIterator[AgentStreamEvent]:
    """Inject heartbeat events into an async stream."""

    if interval <= 0:
        async for event in source:
            yield event
        return

    iterator = source.__aiter__()
    pending_event = asyncio.create_task(iterator.__anext__())
    heartbeat_task = asyncio.create_task(asyncio.sleep(interval))

    try:
        while True:
            done, _ = await asyncio.wait(
                {pending_event, heartbeat_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            if heartbeat_task in done:
                yield AgentStreamEvent(
                    event="heartbeat",
                    data={
                        **context,
                        "timestamp": utc_now_iso(),
                    },
                )
                heartbeat_task = asyncio.create_task(asyncio.sleep(interval))
                continue

            if pending_event in done:
                try:
                    event = pending_event.result()
                except StopAsyncIteration:
                    break

                yield event
                pending_event = asyncio.create_task(iterator.__anext__())
                heartbeat_task.cancel()
                heartbeat_task = asyncio.create_task(asyncio.sleep(interval))
    finally:
        pending_event.cancel()
        heartbeat_task.cancel()


@dataclass
class StreamingContextSnapshot:
    """Optional metadata collected during context preparation."""

    context_token_usage: Optional[Dict[str, int]] = None
    context_messages_selected: Optional[int] = None
    context_messages_dropped: Optional[int] = None
    context_box_messages_selected: Optional[int] = None
    context_box_messages_dropped: Optional[int] = None
    context_budget_tokens: Optional[int] = None
    context_window_tokens: Optional[int] = None
    tool_runs: Optional[List[Dict[str, Any]]] = None


def serialize_agent_result(result: AgentServiceResult) -> Dict[str, Any]:
    """Convert AgentServiceResult into an event payload."""

    payload: Dict[str, Any] = {
        "content": result.content,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "total_tokens": result.total_tokens,
        "cost_usd": str(result.cost_usd) if result.cost_usd is not None else None,
        "response_time_ms": result.response_time_ms,
        "model_name": result.model_name,
    }

    if result.context_token_usage is not None:
        payload["context_token_usage"] = result.context_token_usage
    if result.context_budget_tokens is not None:
        payload["context_budget_tokens"] = result.context_budget_tokens
    if result.context_window_tokens is not None:
        payload["context_window_tokens"] = result.context_window_tokens
    if result.context_messages_selected is not None:
        payload["context_messages_selected"] = result.context_messages_selected
    if result.context_messages_dropped is not None:
        payload["context_messages_dropped"] = result.context_messages_dropped
    if result.context_box_messages_selected is not None:
        payload["context_box_messages_selected"] = result.context_box_messages_selected
    if result.context_box_messages_dropped is not None:
        payload["context_box_messages_dropped"] = result.context_box_messages_dropped
    if result.tool_runs:
        payload["tool_runs"] = result.tool_runs

    return payload


class StreamingManager:
    """Manage LiteLLM streaming calls and payload assembly."""

    def __init__(
        self,
        *,
        llm_client,
        token_tracker,
        model: str,
        temperature: float,
        max_tokens: int,
        timeout: int,
        error_cls: Type[Exception],
        sanitize_tool_runs: Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]],
    ) -> None:
        self.llm = llm_client
        self.token_tracker = token_tracker
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.error_cls = error_cls
        self._sanitize_tool_runs = sanitize_tool_runs

    def build_litellm_params(
        self,
        *,
        messages: List[Dict[str, Any]],
        metadata: Dict[str, Any],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        stream: bool = False,
        overrides: Optional[LlmInvocationOverrides] = None,
    ) -> Dict[str, Any]:
        """Construct LiteLLM parameter dictionaries with shared configuration."""

        base_overrides: Dict[str, Any] = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
        }

        if tools:
            base_overrides["tools"] = tools
        if tool_choice:
            base_overrides["tool_choice"] = tool_choice
        extra_headers: Dict[str, str] = {}
        if overrides is None:
            overrides_map: Dict[str, Any] = {}
        else:
            overrides_map = {}
            if overrides.model_override:
                overrides_map["model"] = overrides.model_override
            if overrides.api_key:
                overrides_map["api_key"] = overrides.api_key
            if overrides.api_base:
                overrides_map["api_base"] = overrides.api_base
            extra_headers = self._resolve_special_headers(overrides.api_base)
            if extra_headers:
                overrides_map["extra_headers"] = {
                    **extra_headers,
                    **(overrides_map.get("extra_headers") or {}),
                }

        params = self.llm.build_params(
            messages=messages,
            metadata=metadata,
            stream=stream,
            **base_overrides,
        )
        if overrides is not None:
            params.update(overrides_map)
            extra_metadata = {
                "llm_token_source": overrides.token_source,
                "llm_provider": (overrides.provider or "").strip() or None,
            }
            params["metadata"] = {
                **(params.get("metadata") or {}),
                **extra_metadata,
            }

        return params

    @staticmethod
    def _resolve_special_headers(api_base: Optional[str]) -> Dict[str, str]:
        if not api_base:
            return {}
        try:
            hostname = urlparse(api_base).hostname or ""
        except ValueError:
            return {}
        if hostname.endswith("openrouter.ai"):
            return {
                "HTTP-Referer": settings.frontend_base_url,
                "X-Title": settings.app_name,
            }
        return {}

    def attach_context_metadata(
        self,
        result: AgentServiceResult,
        snapshot: Optional[StreamingContextSnapshot],
    ) -> AgentServiceResult:
        """Enrich AgentServiceResult with context metadata."""

        if snapshot is None:
            result.tool_runs = []
            return result

        result.context_token_usage = snapshot.context_token_usage
        result.context_budget_tokens = snapshot.context_budget_tokens
        result.context_window_tokens = snapshot.context_window_tokens
        result.context_messages_selected = snapshot.context_messages_selected
        result.context_messages_dropped = snapshot.context_messages_dropped
        result.context_box_messages_selected = snapshot.context_box_messages_selected
        result.context_box_messages_dropped = snapshot.context_box_messages_dropped
        result.tool_runs = self._sanitize_tool_runs(list(snapshot.tool_runs or []))
        return result

    def build_fallback_result(
        self, *, content: str, snapshot: Optional[StreamingContextSnapshot] = None
    ) -> AgentServiceResult:
        result = AgentServiceResult(
            content=content.strip(),
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            cost_usd=None,
            response_time_ms=None,
            model_name="fallback",
            raw_response=None,
        )
        return self.attach_context_metadata(result, snapshot)

    async def stream_completion(
        self,
        *,
        messages: List[Dict[str, Any]],
        metadata: Dict[str, Any],
        start_time: float,
        snapshot: Optional[StreamingContextSnapshot] = None,
        overrides: Optional[LlmInvocationOverrides] = None,
    ) -> AsyncIterator[AgentStreamEvent]:
        """Stream LiteLLM completion chunks and emit structured events."""

        params = self.build_litellm_params(
            messages=messages,
            metadata=metadata,
            stream=True,
            overrides=overrides,
        )

        content_parts: List[str] = []
        model_name: Optional[str] = None
        usage = TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
        cost_usd: Optional[Decimal] = None

        logger.info(
            "_stream_completion called with %s messages, stream=%s",
            len(messages),
            params.get("stream", False),
        )

        try:
            async with litellm_call_context(
                logger=logger,
                operation_name="LiteLLM streaming",
                timeout=self.timeout,
                error_cls=self.error_cls,
                extra_context={
                    "model": params.get("model"),
                    "messages_count": len(params.get("messages", [])),
                },
            ) as (stream_start_time, _):
                execution_params = dict(params)
                stream = await asyncio.wait_for(
                    self.llm.completion(
                        messages=execution_params.pop("messages"),
                        metadata=execution_params.pop("metadata", None),
                        **execution_params,
                    ),
                    timeout=self.timeout,
                )

                stream_establish_duration = time.time() - stream_start_time
                logger.info(
                    "LiteLLM stream established in %.3fs, processing chunks",
                    stream_establish_duration,
                )

            stream_close = getattr(stream, "aclose", None)
            stream_closed = False

            async def _close_stream() -> None:
                nonlocal stream_closed
                if stream_closed or stream_close is None:
                    return
                try:
                    await stream_close()
                except Exception as close_exc:  # pragma: no cover - defensive logging
                    logger.warning("LiteLLM stream close error: %s", close_exc)
                finally:
                    stream_closed = True

            chunk_count = 0
            try:
                async for chunk in stream:
                    chunk_count += 1
                    if chunk_count % 10 == 0:
                        logger.info("Processed %s LiteLLM chunks", chunk_count)

                    try:
                        if model_name is None:
                            model_name = getattr(chunk, "model", None)
                            if model_name:
                                yield AgentStreamEvent(
                                    event="metadata",
                                    data={"model": model_name},
                                )

                        choice = chunk.choices[0]
                        delta = getattr(choice, "delta", None)

                        if delta and getattr(delta, "content", None):
                            text = delta.content
                            content_parts.append(text)
                            yield AgentStreamEvent(
                                event="delta",
                                data={"content": text},
                            )

                        chunk_usage = getattr(chunk, "usage", None)
                        if chunk_usage:
                            usage = self.token_tracker.extract_usage(chunk)
                            if model_name:
                                fake_response = SimpleNamespace(
                                    model=model_name,
                                    usage=chunk_usage,
                                )
                                cost_usd = self.token_tracker.calculate_cost(
                                    fake_response
                                )
                    except (
                        Exception
                    ) as chunk_error:  # pragma: no cover - defensive logging
                        logger.error(
                            "Error processing chunk %s: %s",
                            chunk_count,
                            chunk_error,
                        )
                        continue

                logger.info("LiteLLM streaming completed: %s chunks total", chunk_count)

            except asyncio.CancelledError:
                logger.warning("LiteLLM stream cancelled by upstream consumer")
                await _close_stream()
                raise
            except Exception as stream_iter_error:
                logger.error(
                    "Stream iteration error after %s chunks: %s",
                    chunk_count,
                    stream_iter_error,
                )
                log_exception(logger, "Stream iteration error details", None)
            finally:
                await _close_stream()

        except self.error_cls as exc:
            # Friendly error for BYOT/LLM故障，避免前端长时间停留在“思考中”
            yield AgentStreamEvent(
                event="error",
                data={
                    "message": (
                        "LLM 调用失败，请在设置 > AI 接入中点击“检测可用性”或更新密钥。" f" 详情: {str(exc)}"
                    )
                },
            )
            return

        final_text = "".join(content_parts)
        elapsed_seconds = max(time.time() - start_time, 0)
        elapsed_ms = int(elapsed_seconds * 1000)

        logger.info(
            "_stream_completion finished: %s chars, %s tokens, %sms",
            len(final_text),
            usage.total_tokens,
            elapsed_ms,
        )

        result = AgentServiceResult(
            content=final_text.strip(),
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            cost_usd=cost_usd,
            response_time_ms=elapsed_ms,
            model_name=model_name,
            raw_response=None,
        )

        result = self.attach_context_metadata(result, snapshot)

        yield AgentStreamEvent(event="final", data=serialize_agent_result(result))


__all__ = [
    "StreamingManager",
    "StreamingContextSnapshot",
    "litellm_call_context",
    "serialize_agent_result",
    "stream_with_heartbeat",
]
