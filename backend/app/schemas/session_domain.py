"""Unified session domain schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.pagination import ListResponse, Pagination

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
    page: int = Field(1, ge=1, description="Page number (1-indexed)")
    size: int = Field(100, ge=1, le=200, description="Page size")


class SessionMessageItem(BaseModel):
    id: str
    role: Literal["user", "agent", "system"]
    created_at: datetime
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SessionMessageBlockItem(BaseModel):
    id: str
    message_id: str = Field(alias="messageId")
    seq: int
    type: str
    content: Optional[str] = None
    content_length: int = Field(alias="contentLength")
    is_finished: bool = Field(alias="isFinished")

    model_config = {"populate_by_name": True}


SessionBlocksMode = Literal["full", "text_with_placeholders", "outline"]


class SessionMessageBlocksQueryRequest(BaseModel):
    message_ids: list[str] = Field(alias="messageIds", min_length=1, max_length=200)
    mode: SessionBlocksMode = "full"

    model_config = {"populate_by_name": True}


class SessionMessageBlocksItem(BaseModel):
    message_id: str = Field(alias="messageId")
    role: Literal["user", "agent", "system"]
    block_count: int = Field(alias="blockCount")
    has_blocks: bool = Field(alias="hasBlocks")
    blocks: list[SessionMessageBlockItem]

    model_config = {"populate_by_name": True}


class SessionMessageBlocksQueryMeta(BaseModel):
    conversation_id: str = Field(alias="conversationId")
    mode: SessionBlocksMode

    model_config = {"populate_by_name": True}


class SessionMessageBlocksQueryResponse(BaseModel):
    items: list[SessionMessageBlocksItem]
    meta: SessionMessageBlocksQueryMeta


class SessionMessageBlockDetailResponse(BaseModel):
    message_id: str = Field(alias="messageId")
    block: SessionMessageBlockItem

    model_config = {"populate_by_name": True}


class SessionMessagesMeta(BaseModel):
    conversation_id: str = Field(alias="conversationId")
    source: SessionSource
    agent_id: Optional[str] = None
    agent_source: Optional[AgentSource] = None
    upstream_session_id: Optional[str] = None

    model_config = {"populate_by_name": True}


class SessionMessagesListResponse(
    ListResponse[SessionMessageItem, SessionMessagesMeta]
):
    pass


class SessionContinueResponse(BaseModel):
    conversation_id: str = Field(alias="conversationId")
    source: SessionSource
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


__all__ = [
    "SessionContinueResponse",
    "SessionBlocksMode",
    "SessionListResponse",
    "SessionMessageBlockDetailResponse",
    "SessionMessageBlockItem",
    "SessionMessageBlocksItem",
    "SessionMessageBlocksQueryMeta",
    "SessionMessageBlocksQueryRequest",
    "SessionMessageBlocksQueryResponse",
    "SessionMessageItem",
    "SessionMessagesListResponse",
    "SessionMessagesMeta",
    "SessionMessagesQueryRequest",
    "SessionQueryRequest",
    "SessionSource",
    "SessionViewItem",
]
