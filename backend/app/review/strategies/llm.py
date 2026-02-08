"""Lightweight LLM client helpers for review strategies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.agents.llm import llm_client
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class CompletionResult:
    """Container for LLM completion responses."""

    content: str
    raw_response: Any


class DailyReviewLLMClient:
    """Thin wrapper around litellm for daily review strategies."""

    def __init__(
        self,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> None:
        self.model = model or settings.litellm_model
        self.temperature = (
            temperature if temperature is not None else settings.litellm_temperature
        )
        self.max_tokens = max_tokens or settings.litellm_completion_max_tokens
        self.api_key = api_key or settings.litellm_api_key
        self.base_url = base_url or settings.litellm_base_url
        self.timeout = timeout or settings.litellm_timeout

    async def complete(
        self,
        messages: List[Dict[str, str]],
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CompletionResult:
        """Invoke litellm completion with compass defaults."""

        overrides: Dict[str, Any] = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
        }
        if self.api_key:
            overrides["api_key"] = self.api_key
        if self.base_url:
            overrides["api_base"] = self.base_url
        if metadata:
            overrides["metadata"] = metadata

        logger.info(
            "DailyReviewLLMClient.complete called", extra={"metadata": metadata}
        )
        response = await llm_client.completion(
            messages=messages,
            **overrides,
        )
        content = response.choices[0].message.content if response.choices else ""
        return CompletionResult(content=content or "", raw_response=response)
