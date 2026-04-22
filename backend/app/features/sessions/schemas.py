"""Session feature schemas for unified conversation APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.features.hub_assistant.shared.constants import (
    HUB_ASSISTANT_PUBLIC_ID,
)
from app.schemas.pagination import Pagination

SessionSource = Literal["manual", "scheduled"]
AgentSource = Literal["personal", "shared", "hub_assistant"]


class SessionQueryRequest(BaseModel):
    page: int = Field(1, ge=1, description="Page number (1-indexed)")
    size: int = Field(50, ge=1, le=200, description="Page size")
    source: Optional[SessionSource] = Field(
        None,
        description="Filter by source (manual/scheduled)",
    )
    agent_id: Optional[str] = Field(
        None,
        description=(
            "Filter by agent id. Accepts a UUID or the Hub Assistant "
            "assistant public id."
        ),
    )

    @field_validator("agent_id")
    @classmethod
    def validate_agent_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value == HUB_ASSISTANT_PUBLIC_ID:
            return value
        try:
            UUID(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "Input should be a valid UUID or the Hub Assistant " "assistant id."
            ) from exc
        return value


class SessionViewItem(BaseModel):
    conversation_id: UUID = Field(
        alias="conversationId",
        description="Canonical conversation id.",
    )
    source: SessionSource
    external_provider: Optional[str] = None
    external_session_id: Optional[str] = None
    agent_id: Optional[str] = None
    agent_source: Optional[AgentSource] = None
    title: str
    last_active_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    model_config = {"populate_by_name": True}


class SessionListResponse(BaseModel):
    items: list[SessionViewItem]
    pagination: Pagination


class SessionMessagesQueryRequest(BaseModel):
    before: Optional[str] = Field(
        None,
        description="Opaque cursor to fetch older messages.",
    )
    limit: int = Field(8, ge=1, le=50, description="Page size for timeline window")


class SessionMessageItem(BaseModel):
    id: str
    role: Literal["user", "agent", "system"]
    kind: str = "message"
    content: str = ""
    created_at: datetime
    status: str
    operation_id: Optional[str] = Field(alias="operationId", default=None)
    blocks: list[SessionMessageBlockItem] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class SessionMessagesPageInfo(BaseModel):
    has_more_before: bool = Field(alias="hasMoreBefore")
    next_before: Optional[str] = Field(alias="nextBefore", default=None)

    model_config = {"populate_by_name": True}


class SessionMessagesQueryResponse(BaseModel):
    items: list[SessionMessageItem]
    page_info: SessionMessagesPageInfo = Field(alias="pageInfo")

    model_config = {"populate_by_name": True}


class SessionControlResultItem(BaseModel):
    intent: Literal["append", "preempt"]
    status: Literal[
        "accepted",
        "completed",
        "no_inflight",
        "unavailable",
        "failed",
    ]
    session_id: Optional[str] = Field(alias="sessionId", default=None)

    model_config = {"populate_by_name": True}


class SessionAppendMessageRequest(BaseModel):
    content: str = Field(..., min_length=1, description="Text to append.")
    user_message_id: UUID | None = Field(alias="userMessageId", default=None)
    operation_id: UUID | None = Field(alias="operationId", default=None)
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Optional extension metadata object forwarded to upstream.",
    )
    working_directory: Optional[str] = Field(
        alias="workingDirectory",
        default=None,
        description="Optional hub-stable working directory for provider adaptation.",
    )

    model_config = {"populate_by_name": True}


class SessionAppendMessageResponse(BaseModel):
    conversation_id: str = Field(alias="conversationId")
    user_message: SessionMessageItem = Field(alias="userMessage")
    session_control: SessionControlResultItem = Field(alias="sessionControl")

    model_config = {"populate_by_name": True}


class SessionCommandRunRequest(BaseModel):
    command: str = Field(..., min_length=1, description="Slash command name.")
    arguments: str = Field(default="", description="Optional command arguments.")
    prompt: str = Field(default="", description="Optional command prompt body.")
    user_message_id: UUID | None = Field(alias="userMessageId", default=None)
    agent_message_id: UUID | None = Field(alias="agentMessageId", default=None)
    operation_id: UUID | None = Field(alias="operationId", default=None)
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Optional extension metadata object forwarded to upstream.",
    )
    working_directory: Optional[str] = Field(
        alias="workingDirectory",
        default=None,
        description="Optional hub-stable working directory for provider adaptation.",
    )

    model_config = {"populate_by_name": True}


class SessionCommandRunResponse(BaseModel):
    conversation_id: str = Field(alias="conversationId")
    user_message: SessionMessageItem = Field(alias="userMessage")
    agent_message: SessionMessageItem = Field(alias="agentMessage")

    model_config = {"populate_by_name": True}


class SessionMessageBlocksQueryRequest(BaseModel):
    block_ids: list[UUID] = Field(
        alias="blockIds",
        min_length=1,
        max_length=50,
        description="Block ids to fetch content details for.",
    )

    model_config = {"populate_by_name": True}


class ToolCallViewItem(BaseModel):
    name: Optional[str] = None
    status: Literal[
        "running", "completed", "success", "failed", "interrupted", "unknown"
    ]
    call_id: Optional[str] = Field(alias="callId", default=None)
    arguments: Optional[Any] = None
    result: Optional[Any] = None
    error: Optional[Any] = None

    model_config = {"populate_by_name": True}


class ToolCallTimelineEntryItem(BaseModel):
    status: str
    title: Optional[str] = None
    input: Optional[Any] = None
    output: Optional[Any] = None
    error: Optional[Any] = None


class ToolCallDetailItem(ToolCallViewItem):
    title: Optional[str] = None
    timeline: list[ToolCallTimelineEntryItem] = Field(default_factory=list)
    raw: Optional[str] = None


class InterruptQuestionOptionItem(BaseModel):
    label: str
    description: Optional[str] = None
    value: Optional[str] = None


class InterruptQuestionItem(BaseModel):
    header: Optional[str] = None
    description: Optional[str] = None
    question: str
    options: list[InterruptQuestionOptionItem] = Field(default_factory=list)


class InterruptDetailsItem(BaseModel):
    permission: Optional[str] = None
    patterns: list[str] = Field(default_factory=list)
    display_message: Optional[str] = Field(alias="displayMessage", default=None)
    questions: list[InterruptQuestionItem] = Field(default_factory=list)
    permissions: Optional[dict[str, Any]] = None
    server_name: Optional[str] = Field(alias="serverName", default=None)
    mode: Optional[str] = None
    requested_schema: Optional[Any] = Field(alias="requestedSchema", default=None)
    url: Optional[str] = None
    elicitation_id: Optional[str] = Field(alias="elicitationId", default=None)
    meta: Optional[dict[str, Any]] = None

    model_config = {"populate_by_name": True}


class InterruptViewItem(BaseModel):
    request_id: str = Field(alias="requestId")
    type: Literal["permission", "question", "permissions", "elicitation"]
    phase: Literal["asked", "resolved"]
    resolution: Optional[Literal["replied", "rejected", "expired"]] = None
    details: Optional[InterruptDetailsItem] = None

    model_config = {"populate_by_name": True}


class SessionMessageBlockItem(BaseModel):
    id: str
    type: str
    content: Optional[str] = None
    is_finished: bool = Field(alias="isFinished")
    block_id: Optional[str] = Field(alias="blockId", default=None)
    lane_id: Optional[str] = Field(alias="laneId", default=None)
    base_seq: Optional[int] = Field(alias="baseSeq", default=None)
    tool_call: Optional[ToolCallViewItem] = Field(alias="toolCall", default=None)
    interrupt: Optional[InterruptViewItem] = None

    model_config = {"populate_by_name": True}


class SessionMessageBlockDetailItem(BaseModel):
    id: str
    message_id: str = Field(alias="messageId")
    type: str
    content: Optional[str] = None
    is_finished: bool = Field(alias="isFinished")
    block_id: Optional[str] = Field(alias="blockId", default=None)
    lane_id: Optional[str] = Field(alias="laneId", default=None)
    base_seq: Optional[int] = Field(alias="baseSeq", default=None)
    tool_call: Optional[ToolCallViewItem] = Field(alias="toolCall", default=None)
    tool_call_detail: Optional[ToolCallDetailItem] = Field(
        alias="toolCallDetail",
        default=None,
    )
    interrupt: Optional[InterruptViewItem] = None

    model_config = {"populate_by_name": True}


class SessionMessageBlocksQueryResponse(BaseModel):
    items: list[SessionMessageBlockDetailItem]

    model_config = {"populate_by_name": True}


class SessionContinueResponse(BaseModel):
    conversation_id: str = Field(alias="conversationId")
    source: SessionSource
    metadata: Dict[str, Any] = Field(default_factory=dict)
    working_directory: Optional[str] = Field(
        alias="workingDirectory",
        default=None,
    )

    model_config = {"populate_by_name": True}


class SessionCancelResponse(BaseModel):
    conversation_id: str = Field(alias="conversationId")
    task_id: Optional[str] = Field(alias="taskId", default=None)
    cancelled: bool
    status: Literal[
        "accepted",
        "pending",
        "no_inflight",
        "already_terminal",
    ]

    model_config = {"populate_by_name": True}


class SessionUpstreamTaskResponse(BaseModel):
    conversation_id: str = Field(alias="conversationId")
    task_id: str = Field(alias="taskId")
    task: Dict[str, Any]

    model_config = {"populate_by_name": True}
