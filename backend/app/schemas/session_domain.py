"""Unified session domain schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.pagination import Pagination

SessionSource = Literal["manual", "scheduled"]
AgentSource = Literal["personal", "shared"]


class SessionQueryRequest(BaseModel):
    page: int = Field(1, ge=1, description="Page number (1-indexed)")
    size: int = Field(50, ge=1, le=200, description="Page size")
    source: Optional[SessionSource] = Field(
        None,
        description="Filter by source (manual/scheduled)",
    )
    agent_id: Optional[UUID] = Field(
        None,
        description="Filter by agent id.",
    )


class SessionViewItem(BaseModel):
    conversation_id: UUID = Field(
        alias="conversationId",
        description="Canonical conversation id.",
    )
    source: SessionSource
    external_provider: Optional[str] = None
    external_session_id: Optional[str] = None
    agent_id: Optional[UUID] = None
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
    created_at: datetime
    status: str
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
    status: Literal["running", "success", "failed", "interrupted", "unknown"]
    call_id: Optional[str] = Field(alias="callId", default=None)
    arguments: Optional[Any] = None
    result: Optional[Any] = None
    error: Optional[Any] = None

    model_config = {"populate_by_name": True}


class SessionMessageBlockItem(BaseModel):
    id: str
    type: str
    content: Optional[str] = None
    is_finished: bool = Field(alias="isFinished")
    tool_call: Optional[ToolCallViewItem] = Field(alias="toolCall", default=None)

    model_config = {"populate_by_name": True}


class SessionMessageBlockDetailItem(BaseModel):
    id: str
    message_id: str = Field(alias="messageId")
    type: str
    content: Optional[str] = None
    is_finished: bool = Field(alias="isFinished")
    tool_call: Optional[ToolCallViewItem] = Field(alias="toolCall", default=None)

    model_config = {"populate_by_name": True}


class SessionMessageBlocksQueryResponse(BaseModel):
    items: list[SessionMessageBlockDetailItem]

    model_config = {"populate_by_name": True}


class SessionContinueResponse(BaseModel):
    conversation_id: str = Field(alias="conversationId")
    source: SessionSource
    metadata: Dict[str, Any] = Field(default_factory=dict)

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


__all__ = [
    "SessionCancelResponse",
    "SessionContinueResponse",
    "SessionListResponse",
    "SessionMessageBlockItem",
    "SessionMessageBlockDetailItem",
    "SessionMessageBlocksQueryRequest",
    "SessionMessageBlocksQueryResponse",
    "ToolCallViewItem",
    "SessionMessageItem",
    "SessionMessagesPageInfo",
    "SessionMessagesQueryRequest",
    "SessionMessagesQueryResponse",
    "SessionQueryRequest",
    "SessionSource",
    "SessionViewItem",
]
