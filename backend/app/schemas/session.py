"""
Session management Pydantic schemas
"""

from datetime import datetime
from typing import List, Literal, Optional, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.pagination import ListResponse, Pagination

SessionTypeLiteral = Literal["chat", "system", "scheduled"]


class SessionBase(BaseModel):
    """Base schema for agent sessions."""

    name: str = Field(..., min_length=1, max_length=255)


class CreateSessionRequest(SessionBase):
    """Schema for creating a new session."""

    sync_cardbox: bool = Field(
        False,
        description="Whether to trigger an immediate Cardbox data sync when the session is created.",
    )
    agent_name: Optional[str] = Field(
        None, description="Optional agent name to associate with the session"
    )


class UpdateSessionRequest(BaseModel):
    """Schema for updating a session."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    agent_name: Optional[str] = Field(
        None, description="Optional agent assignment for the session"
    )


class SessionResponse(SessionBase):
    """Schema for session responses."""

    id: UUID
    created_at: datetime
    updated_at: datetime
    last_activity_at: datetime
    message_count: int = 0
    is_favorite: bool = False
    cardbox_name: Optional[str] = None
    summary: Optional[str] = None
    agent_name: Optional[str] = None
    module_key: Optional[str] = None
    session_type: SessionTypeLiteral = "chat"
    unread_count: int = 0
    prompt_tokens_total: int = 0
    completion_tokens_total: int = 0
    total_tokens_total: int = 0
    cost_usd_total: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_orm(cls, obj):
        """Create response from ORM object."""
        module_key = getattr(obj, "module_key", None)
        raw_session_type = getattr(obj, "session_type", None)
        session_type: SessionTypeLiteral = (
            cast(SessionTypeLiteral, raw_session_type)
            if raw_session_type in {"chat", "system", "scheduled"}
            else "chat"
        )

        return cls(
            id=obj.id,
            name=obj.name,
            created_at=obj.created_at,
            updated_at=obj.updated_at,
            last_activity_at=obj.last_activity_at,
            message_count=getattr(obj, "message_count", 0),
            is_favorite=obj.is_favorite,
            cardbox_name=obj.cardbox_name,
            summary=getattr(obj, "summary", None),
            agent_name=module_key,
            module_key=module_key,
            session_type=session_type,
            unread_count=int(getattr(obj, "unread_count", 0) or 0),
            prompt_tokens_total=int(getattr(obj, "prompt_tokens_total", 0) or 0),
            completion_tokens_total=int(
                getattr(obj, "completion_tokens_total", 0) or 0
            ),
            total_tokens_total=int(getattr(obj, "total_tokens_total", 0) or 0),
            cost_usd_total=(
                str(getattr(obj, "cost_usd_total"))
                if getattr(obj, "cost_usd_total", None) is not None
                else None
            ),
        )


class SessionPagination(Pagination):
    """Pagination metadata for session lists."""


class SessionListMeta(BaseModel):
    """Additional list metadata for sessions."""

    session_type: Optional[SessionTypeLiteral] = Field(
        None, description="Optional session type filter"
    )


class SessionListResponse(ListResponse[SessionResponse, SessionListMeta]):
    """Schema for session list response."""

    items: List[SessionResponse]
    pagination: SessionPagination
    meta: SessionListMeta
