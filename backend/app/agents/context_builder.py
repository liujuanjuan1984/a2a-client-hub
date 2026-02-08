"""Context preparation helpers with token-aware budgeting."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.agents.conversation_history import ConversationMessage
from app.agents.token_estimator import EstimationResult, token_estimator
from app.core.config import settings


@dataclass
class ContextBudget:
    """Configuration for prompt assembly token budgeting."""

    max_context_tokens: int
    buffer_tokens: int

    @classmethod
    def from_settings(cls) -> "ContextBudget":
        hard_window = max(0, settings.litellm_context_window_tokens)
        buffer = max(0, settings.conversation_context_buffer)
        hard_limit = max(0, hard_window - buffer)
        soft_limit = max(0, settings.conversation_context_budget)

        if hard_limit and soft_limit:
            max_tokens = min(hard_limit, soft_limit)
        elif hard_limit:
            max_tokens = hard_limit
        else:
            max_tokens = soft_limit

        return cls(max_context_tokens=max_tokens, buffer_tokens=buffer)


@dataclass
class ContextBuildResult:
    """Return value describing how the context was assembled."""

    messages: List[Dict[str, Any]]
    selected_history: List[ConversationMessage]
    dropped_history: List[ConversationMessage]
    token_usage: Dict[str, int]
    summary_candidates: List[ConversationMessage] = field(default_factory=list)


class ContextBuilder:
    """Constructs chat prompts while respecting token budgets."""

    def __init__(self) -> None:
        self._estimator = token_estimator

    def _estimate_history_tokens(
        self,
        history: List[ConversationMessage],
        model: str,
        budget: ContextBudget,
    ) -> tuple[List[ConversationMessage], List[ConversationMessage], int]:
        if not history:
            return [], [], 0

        remaining_budget = max(0, budget.max_context_tokens - budget.buffer_tokens)
        selected_stack: List[tuple[ConversationMessage, EstimationResult]] = []
        dropped_stack: List[ConversationMessage] = []

        for message in reversed(history):
            estimate = self._estimator.estimate_message_tokens(message, model)
            if estimate.total_tokens <= remaining_budget or not selected_stack:
                selected_stack.append((message, estimate))
                remaining_budget = max(0, remaining_budget - estimate.total_tokens)
            else:
                dropped_stack.append(message)

        selected_stack.reverse()
        selected_history = [msg for msg, _ in selected_stack]
        history_tokens = sum(est.total_tokens for _, est in selected_stack)
        dropped_history = list(reversed(dropped_stack))
        return selected_history, dropped_history, history_tokens

    def _serialize_message(self, message: ConversationMessage) -> Dict[str, Any]:
        if message.role == "tool":
            payload: Dict[str, Any] = {
                "role": "tool",
                "content": message.content,
            }
            if message.tool_call_id:
                payload["tool_call_id"] = message.tool_call_id
            return payload

        # Normalize role names to ensure compatibility with LLM APIs
        normalized_role = message.role
        if message.role not in ["system", "user", "assistant", "tool"]:
            # Handle any unexpected role values
            if message.role == "agent":
                normalized_role = "assistant"
            else:
                # Default to assistant for unknown roles
                normalized_role = "assistant"

        result: Dict[str, Any] = {
            "role": normalized_role,
            "content": message.content,
        }
        if message.tool_calls:
            result["tool_calls"] = message.tool_calls
        if message.name:
            result["name"] = message.name
        return result

    def build_context(
        self,
        *,
        user_id: UUID,
        user_message: str,
        history: List[ConversationMessage],
        model: str,
        system_prompt: str,
        budget: Optional[ContextBudget] = None,
    ) -> ContextBuildResult:
        budget = budget or ContextBudget.from_settings()

        system_tokens = self._estimator.estimate_text_tokens(system_prompt, model)
        user_tokens = self._estimator.estimate_text_tokens(user_message, model)
        base_tokens = system_tokens + user_tokens + budget.buffer_tokens

        if base_tokens >= budget.max_context_tokens:
            # not enough room, fall back to system + user only
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ]
            token_usage = {
                "system_tokens": system_tokens,
                "user_tokens": user_tokens,
                "history_tokens": 0,
                "total_tokens": system_tokens + user_tokens,
            }
            return ContextBuildResult(
                messages=messages,
                selected_history=[],
                dropped_history=history,
                token_usage=token_usage,
                summary_candidates=history,
            )

        remaining_history_budget = budget.max_context_tokens - base_tokens
        ratio = max(0.0, min(1.0, settings.conversation_summary_reserve_ratio))
        summary_reserve = 0
        effective_budget = max(0, remaining_history_budget)
        if len(history) >= settings.conversation_summary_min_messages:
            summary_reserve = int(budget.max_context_tokens * ratio)
            summary_reserve = min(summary_reserve, max(0, remaining_history_budget))
            effective_budget = max(0, remaining_history_budget - summary_reserve)

        (
            trimmed_history,
            dropped_history,
            history_tokens,
        ) = self._estimate_history_tokens(
            history,
            model,
            ContextBudget(max_context_tokens=effective_budget, buffer_tokens=0),
        )

        serialized_history = [self._serialize_message(msg) for msg in trimmed_history]
        messages = [
            {"role": "system", "content": system_prompt},
            *serialized_history,
            {"role": "user", "content": user_message},
        ]

        token_usage = {
            "system_tokens": system_tokens,
            "user_tokens": user_tokens,
            "history_tokens": history_tokens,
            "total_tokens": system_tokens + user_tokens + history_tokens,
            "summary_reserve_tokens": (
                summary_reserve
                if len(history) >= settings.conversation_summary_min_messages
                else 0
            ),
            "max_context_tokens": budget.max_context_tokens,
        }

        summary_candidates = (
            dropped_history
            if len(dropped_history) >= settings.conversation_summary_min_messages
            else []
        )

        return ContextBuildResult(
            messages=messages,
            selected_history=trimmed_history,
            dropped_history=dropped_history,
            token_usage=token_usage,
            summary_candidates=summary_candidates,
        )


context_builder = ContextBuilder()

__all__ = [
    "ContextBuilder",
    "ContextBudget",
    "ContextBuildResult",
    "context_builder",
]
