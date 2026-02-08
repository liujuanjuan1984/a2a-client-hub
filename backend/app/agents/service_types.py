"""Shared dataclasses for AgentService components."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tools.planner import PreparedToolCall
from app.db.models.agent_session import AgentSession
from app.services.token_quota_service import TokenSource


@dataclass
class AgentServiceResult:
    content: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: Optional[Decimal]
    response_time_ms: Optional[int]
    model_name: Optional[str]
    raw_response: Any
    context_token_usage: Optional[Dict[str, int]] = None
    context_budget_tokens: Optional[int] = None
    context_window_tokens: Optional[int] = None
    context_messages_selected: Optional[int] = None
    context_messages_dropped: Optional[int] = None
    context_box_messages_selected: Optional[int] = None
    context_box_messages_dropped: Optional[int] = None
    tool_runs: List[Dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class AgentStreamEvent:
    event: str
    data: Dict[str, Any]


@dataclass
class ExecutableToolCall:
    prepared: PreparedToolCall
    arguments: Dict[str, Any]


@dataclass
class AgentRuntimeContext:
    """Bundle frequently reused runtime metadata for AgentService flows."""

    db: AsyncSession
    user_id: UUID
    agent_name: str
    session_id: Optional[UUID] = None
    message_id: Optional[UUID] = None
    log_context: Dict[str, Any] = field(default_factory=dict)
    cardbox_session: Optional[AgentSession] = None
    start_time: float = field(default_factory=time.time)

    def logging_extra(self, **extra: Any) -> Dict[str, Any]:
        payload = dict(self.log_context)
        payload.update(extra)
        return payload

    def set_session_id(self, session_id: UUID) -> None:
        self.session_id = session_id
        self.log_context["session_id"] = str(session_id)

    def set_cardbox_session(self, session: Optional[AgentSession]) -> None:
        self.cardbox_session = session


@dataclass(frozen=True)
class LlmInvocationOverrides:
    """Per-request overrides for LiteLLM invocation."""

    token_source: TokenSource
    provider: str
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    model_override: Optional[str] = None


__all__ = [
    "AgentServiceResult",
    "AgentStreamEvent",
    "ExecutableToolCall",
    "AgentRuntimeContext",
    "LlmInvocationOverrides",
]
