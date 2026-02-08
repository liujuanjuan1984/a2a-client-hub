"""
Agent-related Pydantic schemas
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.pagination import ListResponse, Pagination
from app.utils.timezone_util import utc_now

# Rule: keep API payloads manageable by capping per-message text at 128k chars
MAX_MESSAGE_CONTENT_LENGTH = 128_000

AgentMessageSender = Literal["user", "agent", "system", "automation"]


class AgentMessageBase(BaseModel):
    """Base schema for agent messages."""

    content: str = Field(..., min_length=0, max_length=MAX_MESSAGE_CONTENT_LENGTH)
    sender: AgentMessageSender = Field(
        ...,
        description="Source of the message: user, agent, system, or automation.",
    )
    is_typing: bool = False


class AgentMessageResponse(AgentMessageBase):
    """Schema for agent message responses"""

    id: UUID
    timestamp: datetime
    user_id: Optional[UUID] = None
    session_id: Optional[UUID] = None
    agent_name: Optional[str] = None
    message_type: str = "chat"
    metadata: Optional[Dict[str, Any]] = None
    cardbox_card_id: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None
    tool_status: Optional[str] = None
    tool_message: Optional[str] = None
    tool_arguments: Optional[Dict[str, Any]] = None
    tool_sequence: Optional[int] = None
    tool_started_at: Optional[datetime] = None
    tool_finished_at: Optional[datetime] = None
    tool_duration_ms: Optional[int] = None
    tool_progress: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)

    @staticmethod
    def _parse_datetime(value: Any) -> Optional[datetime]:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:  # pragma: no cover - defensive
                return None
        return None

    @staticmethod
    def _parse_int(value: Any) -> Optional[int]:
        if isinstance(value, int):
            return value
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):  # pragma: no cover - defensive
            return None

    @classmethod
    def from_orm(cls, obj):
        """Create response from ORM object, mapping created_at to timestamp"""

        metadata_source = getattr(obj, "message_metadata", None)
        if not isinstance(metadata_source, Mapping) or metadata_source is None:
            legacy_metadata = getattr(obj, "metadata", None)
            if isinstance(legacy_metadata, Mapping):
                metadata_source = legacy_metadata
            else:
                metadata_source = {}
        metadata: Dict[str, Any] = dict(metadata_source or {})
        message_type = getattr(obj, "message_type", None) or "chat"

        tool_arguments = metadata.get("arguments")
        if not isinstance(tool_arguments, dict):
            tool_arguments = None

        tool_progress = metadata.get("progress")
        if not isinstance(tool_progress, dict):
            tool_progress = None

        tool_started_at = cls._parse_datetime(metadata.get("started_at"))
        tool_finished_at = cls._parse_datetime(metadata.get("finished_at"))
        tool_duration_ms = cls._parse_int(metadata.get("duration_ms"))
        tool_sequence = cls._parse_int(metadata.get("sequence"))
        raw_content = obj.content or ""
        # TODO: Support splitting ultra-long payloads into multiple messages instead of truncating
        if len(raw_content) > MAX_MESSAGE_CONTENT_LENGTH:
            content = raw_content[:MAX_MESSAGE_CONTENT_LENGTH]
        else:
            content = raw_content

        return cls(
            id=obj.id,
            content=content,
            sender=obj.sender,
            is_typing=obj.is_typing or False,
            timestamp=obj.created_at or utc_now(),
            user_id=obj.user_id,
            session_id=getattr(obj, "session_id", None),
            agent_name=getattr(getattr(obj, "session", None), "module_key", None),
            message_type=message_type,
            metadata=metadata or None,
            cardbox_card_id=getattr(obj, "cardbox_card_id", None),
            tool_call_id=metadata.get("tool_call_id"),
            tool_name=metadata.get("tool_name"),
            tool_status=metadata.get("status"),
            tool_message=metadata.get("summary"),
            tool_arguments=tool_arguments,
            tool_sequence=tool_sequence,
            tool_started_at=tool_started_at,
            tool_finished_at=tool_finished_at,
            tool_duration_ms=tool_duration_ms,
            tool_progress=tool_progress,
        )


class SendMessageRequest(BaseModel):
    """Schema for sending messages to agent"""

    content: str = Field(
        ...,
        min_length=1,
        max_length=MAX_MESSAGE_CONTENT_LENGTH,
    )
    session_id: Optional[UUID] = Field(
        None,
        description="Existing session identifier; leave empty to start a new session.",
    )
    agent_name: Optional[str] = Field(
        None,
        description="Target agent name; defaults to root_agent if empty",
    )


class TokenUsageSummary(BaseModel):
    """Normalized token usage snapshot"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: Optional[str] = None
    token_source: Optional[str] = Field(
        default=None, description="system or user when applicable"
    )


class ToolRunSummary(BaseModel):
    tool_call_id: str
    tool_name: str
    status: str
    message: Optional[str] = None
    arguments: Optional[Dict[str, Any]] = None
    sequence: Optional[int] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    progress: Optional[Dict[str, Any]] = None


class SendMessageResponse(BaseModel):
    """Schema for send message response"""

    message: AgentMessageResponse
    agent_response: Optional[AgentMessageResponse] = None
    session_id: Optional[UUID] = None
    usage_delta: Optional[TokenUsageSummary] = None
    usage_total: Optional[TokenUsageSummary] = None
    context_token_usage: Optional[Dict[str, int]] = None
    context_window_tokens: Optional[int] = None
    context_budget_tokens: Optional[int] = None
    context_messages_selected: Optional[int] = None
    context_messages_dropped: Optional[int] = None
    context_box_messages_selected: Optional[int] = None
    context_box_messages_dropped: Optional[int] = None
    tool_runs: Optional[List[ToolRunSummary]] = None


class ChatHistoryPagination(Pagination):
    """Pagination metadata for chat history."""


class ChatHistoryResponse(ListResponse[AgentMessageResponse, Dict[str, Any]]):
    """Schema for chat history response"""

    items: List[AgentMessageResponse]
    pagination: ChatHistoryPagination
    meta: Dict[str, Any] = Field(default_factory=dict)
