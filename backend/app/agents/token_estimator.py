"""Utility helpers for estimating token usage of conversation messages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.agents.conversation_history import ConversationMessage


@dataclass
class EstimationResult:
    message_tokens: int
    total_tokens: int


class TokenEstimator:
    """Best-effort token estimator with tiktoken fallback."""

    def __init__(self) -> None:
        try:
            import tiktoken  # type: ignore

            self._tiktoken = tiktoken  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - optional dependency
            self._tiktoken = None
        self._encoders: Dict[str, Any] = {}

    def _get_encoder(self, model: str) -> Optional[Any]:
        if self._tiktoken is None:
            return None
        if model in self._encoders:
            return self._encoders[model]
        try:
            encoder = self._tiktoken.encoding_for_model(model)
        except Exception:
            encoder = self._tiktoken.get_encoding("cl100k_base")
        self._encoders[model] = encoder
        return encoder

    def estimate_text_tokens(self, text: str, model: str) -> int:
        encoder = self._get_encoder(model)
        if encoder is not None:
            try:
                return len(encoder.encode(text))
            except Exception:  # pragma: no cover - defensive
                pass
        # Fallback heuristic: 4 chars per token + 1
        length = len(text)
        return max(1, (length // 4) + 1)

    def estimate_message_tokens(
        self, message: ConversationMessage, model: str
    ) -> EstimationResult:
        base_tokens = 4  # openai chat overhead per message approx
        content_tokens = self.estimate_text_tokens(message.content or "", model)

        tool_calls_tokens = 0
        if message.tool_calls:
            for call in message.tool_calls:
                name = call.get("function", {}).get("name", "")
                args = call.get("function", {}).get("arguments", "")
                tool_calls_tokens += self.estimate_text_tokens(name, model)
                tool_calls_tokens += self.estimate_text_tokens(args, model)
                tool_calls_tokens += 2  # braces / separators

        extra_tokens = 0
        metadata = message.metadata or {}
        if metadata.get("type") == "summary":
            # summaries often shorter but important; add minor overhead
            extra_tokens += 2

        total = base_tokens + content_tokens + tool_calls_tokens + extra_tokens
        return EstimationResult(message_tokens=content_tokens, total_tokens=total)


token_estimator = TokenEstimator()

__all__ = ["TokenEstimator", "token_estimator", "EstimationResult"]
