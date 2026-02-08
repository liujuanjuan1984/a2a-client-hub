"""Unified LiteLLM client for backend agent workflows."""

from __future__ import annotations

import asyncio
import warnings
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

import litellm

from app.core.config import settings
from app.core.logging import get_logger


@dataclass(frozen=True)
class LLMDefaults:
    model: str
    temperature: float
    max_tokens: int
    timeout: int
    api_key: Optional[str]
    api_base: Optional[str]


class LLMClient:
    """Centralised helper for building and executing LiteLLM calls."""

    def __init__(self) -> None:
        self._defaults = LLMDefaults(
            model=settings.litellm_model,
            temperature=settings.litellm_temperature,
            max_tokens=settings.litellm_completion_max_tokens,
            timeout=settings.litellm_timeout,
            api_key=settings.litellm_api_key or None,
            api_base=settings.litellm_base_url or None,
        )
        self._logger = get_logger(__name__)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @property
    def default_model(self) -> str:
        return self._defaults.model

    @property
    def default_temperature(self) -> float:
        return self._defaults.temperature

    @property
    def default_completion_max_tokens(self) -> int:
        return self._defaults.max_tokens

    @property
    def default_timeout(self) -> int:
        return self._defaults.timeout

    @property
    def default_api_key(self) -> Optional[str]:
        return self._defaults.api_key

    @property
    def default_api_base(self) -> Optional[str]:
        return self._defaults.api_base

    def build_params(
        self,
        *,
        messages: Iterable[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None,
        stream: bool = False,
        **overrides: Any,
    ) -> Dict[str, Any]:
        """Construct a parameter dictionary with defaults applied."""

        message_list = list(messages)

        params: Dict[str, Any] = {
            "model": overrides.pop("model", self.default_model),
            "messages": message_list,
            "temperature": overrides.pop("temperature", self.default_temperature),
            "max_tokens": overrides.pop(
                "max_tokens", self.default_completion_max_tokens
            ),
            "timeout": overrides.pop("timeout", self.default_timeout),
        }

        if metadata:
            params["metadata"] = metadata

        if stream:
            params["stream"] = True
            params.setdefault("stream_options", {"include_usage": True})

        params.update(overrides)

        if "api_key" not in params and self.default_api_key:
            params["api_key"] = self.default_api_key
        if "api_base" not in params and self.default_api_base:
            params["api_base"] = self.default_api_base

        return params

    @staticmethod
    def _payload_metrics(message_list: Iterable[Dict[str, Any]]) -> tuple[int, int]:
        count = 0
        total_chars = 0
        for message in message_list:
            count += 1
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, str):
                total_chars += len(content)
            elif isinstance(content, list):
                total_chars += sum(len(str(chunk)) for chunk in content)
            elif content is not None:
                total_chars += len(str(content))
        return count, total_chars

    async def completion(
        self,
        *,
        messages: Iterable[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None,
        stream: bool = False,
        **overrides: Any,
    ) -> Any:
        """Execute a LiteLLM completion with shared defaults."""

        params = self.build_params(
            messages=messages,
            metadata=metadata,
            stream=stream,
            **overrides,
        )

        message_count, char_count = self._payload_metrics(params["messages"])
        self._logger.info(
            "LiteLLM input stats: messages=%s chars=%s",
            message_count,
            char_count,
        )

        attempt = 0
        while True:
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore", message=".*is not mapped in model cost map.*"
                )
                response = await litellm.acompletion(**params)

            if stream or not self._should_retry_tool_calls(response):
                return response

            attempt += 1
            if attempt >= settings.agent_tool_name_retry_attempts:
                self._logger.warning(
                    "LLM returned invalid tool calls after %s attempts; falling back",
                    attempt,
                )
                return response

            delay = max(settings.agent_tool_name_retry_delay_seconds, 0.0)
            if delay:
                await asyncio.sleep(delay)

    def _should_retry_tool_calls(self, response: Any) -> bool:
        """Return True if the completion response contains invalid tool calls."""

        choices = getattr(response, "choices", None)
        if not choices:
            return False

        for choice in choices:
            message = getattr(choice, "message", None) or {}
            tool_calls = getattr(message, "tool_calls", None)
            if tool_calls is None and isinstance(message, dict):
                tool_calls = message.get("tool_calls")
            if not tool_calls:
                continue
            for tool_call in tool_calls:
                function = getattr(tool_call, "function", None)
                if function is None and isinstance(tool_call, dict):
                    function = tool_call.get("function")
                if function is None:
                    return True
                name = getattr(function, "name", None) or (
                    function.get("name") if isinstance(function, dict) else None
                )
                if not self._is_valid_tool_name(name):
                    return True
        return False

    @staticmethod
    def _is_valid_tool_name(candidate: Any) -> bool:
        return isinstance(candidate, str) and candidate.strip() != ""


llm_client = LLMClient()

__all__ = ["LLMClient", "llm_client"]
