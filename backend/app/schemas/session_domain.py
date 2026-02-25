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
    content: str
    created_at: datetime
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SessionMessageBlockItem(BaseModel):
    id: str
    seq: int
    type: str
    content: str
    is_finished: bool = Field(alias="isFinished")

    model_config = {"populate_by_name": True}


class SessionMessageBlocksMeta(BaseModel):
    conversation_id: str = Field(alias="conversationId")
    message_id: str = Field(alias="messageId")
    role: Literal["user", "agent", "system"]
    chunk_count: int = Field(alias="chunkCount")
    has_blocks: bool = Field(alias="hasBlocks")

    model_config = {"populate_by_name": True}


class SessionMessageBlocksResponse(BaseModel):
    items: list[SessionMessageBlockItem]
    meta: SessionMessageBlocksMeta


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
    "SessionListResponse",
    "SessionMessageBlockItem",
    "SessionMessageBlocksMeta",
    "SessionMessageBlocksResponse",
    "SessionMessageItem",
    "SessionMessagesListResponse",
    "SessionMessagesMeta",
    "SessionMessagesQueryRequest",
    "SessionQueryRequest",
    "SessionSource",
    "SessionViewItem",
]
