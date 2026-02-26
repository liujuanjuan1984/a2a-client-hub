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


class SessionMessageBlockItem(BaseModel):
    id: str
    message_id: str = Field(alias="messageId")
    seq: int
    type: str
    content: Optional[str] = None
    content_length: int = Field(alias="contentLength")
    is_finished: bool = Field(alias="isFinished")

    model_config = {"populate_by_name": True}


class SessionMessagesMeta(BaseModel):
    conversation_id: str = Field(alias="conversationId")
    source: SessionSource
    agent_id: Optional[str] = None
    agent_source: Optional[AgentSource] = None
    upstream_session_id: Optional[str] = None

    model_config = {"populate_by_name": True}


class SessionMessageItem(BaseModel):
    id: str
    role: Literal["user", "agent", "system"]
    created_at: datetime
    status: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    blocks: list[SessionMessageBlockItem] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class SessionMessagesPageInfo(BaseModel):
    has_more_before: bool = Field(alias="hasMoreBefore")
    next_before: Optional[str] = Field(alias="nextBefore", default=None)

    model_config = {"populate_by_name": True}


class SessionMessagesQueryResponse(BaseModel):
    items: list[SessionMessageItem]
    page_info: SessionMessagesPageInfo = Field(alias="pageInfo")
    meta: SessionMessagesMeta

    model_config = {"populate_by_name": True}


class SessionContinueResponse(BaseModel):
    conversation_id: str = Field(alias="conversationId")
    source: SessionSource
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


__all__ = [
    "SessionContinueResponse",
    "SessionListResponse",
    "SessionMessageBlockItem",
    "SessionMessagesMeta",
    "SessionMessageItem",
    "SessionMessagesPageInfo",
    "SessionMessagesQueryRequest",
    "SessionMessagesQueryResponse",
    "SessionQueryRequest",
    "SessionSource",
    "SessionViewItem",
]
