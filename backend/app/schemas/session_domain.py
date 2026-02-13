"""Unified session domain schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.pagination import ListResponse

SessionSource = Literal["manual", "scheduled", "opencode"]
AgentSource = Literal["personal", "shared"]


class SessionQueryRequest(BaseModel):
    page: int = Field(1, ge=1, description="Page number (1-indexed)")
    size: int = Field(50, ge=1, le=200, description="Page size")
    refresh: bool = Field(
        False,
        description="Force refresh remote OpenCode cache before listing.",
    )
    source: Optional[SessionSource] = Field(
        None,
        description="Filter by source (manual/scheduled/opencode)",
    )


class SessionViewItem(BaseModel):
    id: str = Field(..., description="Unified session id")
    conversation_id: Optional[UUID] = Field(
        default=None,
        alias="conversationId",
        description="Canonical conversation id for cross-source dedup.",
    )
    source: SessionSource
    source_session_id: str = Field(..., description="Original source session id")
    agent_id: Optional[UUID] = None
    agent_source: Optional[AgentSource] = None
    title: str
    last_active_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    model_config = {"populate_by_name": True}


class SessionListMeta(BaseModel):
    opencode_total_agents: int = 0
    opencode_refreshed_agents: int = 0
    opencode_cached_agents: int = 0
    opencode_partial_failures: int = 0


class SessionListResponse(ListResponse[SessionViewItem, SessionListMeta]):
    pass


class SessionMessagesQueryRequest(BaseModel):
    page: int = Field(1, ge=1, description="Page number (1-indexed)")
    size: int = Field(100, ge=1, le=200, description="Page size")


class SessionMessageItem(BaseModel):
    id: str
    role: Literal["user", "agent", "system"]
    content: str
    created_at: datetime
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SessionMessagesMeta(BaseModel):
    session_id: str
    conversation_id: Optional[str] = Field(default=None, alias="conversationId")
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
    session_id: str
    conversation_id: Optional[str] = Field(default=None, alias="conversationId")
    source: SessionSource
    context_id: Optional[str] = Field(default=None, alias="contextId")
    provider: Optional[str] = None
    external_session_id: Optional[str] = Field(default=None, alias="externalSessionId")
    binding_metadata: Dict[str, Any] = Field(
        default_factory=dict, alias="bindingMetadata"
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


__all__ = [
    "SessionContinueResponse",
    "SessionListMeta",
    "SessionListResponse",
    "SessionMessageItem",
    "SessionMessagesListResponse",
    "SessionMessagesMeta",
    "SessionMessagesQueryRequest",
    "SessionQueryRequest",
    "SessionSource",
    "SessionViewItem",
]
