"""Schemas for /me/sessions endpoints consumed by the A2A universal client."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.pagination import ListResponse, Pagination

MeSessionSource = Literal["manual", "scheduled"]
MeSessionMessageRole = Literal["user", "agent", "system"]


class MeSessionItem(BaseModel):
    id: UUID
    agent_id: Optional[UUID] = None
    title: Optional[str] = None
    source: MeSessionSource
    job_id: Optional[UUID] = None
    run_id: Optional[UUID] = None
    last_active_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class MeSessionPagination(Pagination):
    """Pagination metadata for /me/sessions."""


class MeSessionListResponse(ListResponse[MeSessionItem, Dict[str, Any]]):
    items: List[MeSessionItem]
    pagination: MeSessionPagination
    meta: Dict[str, Any] = Field(default_factory=dict)


class MeSessionMessageItem(BaseModel):
    id: UUID
    role: MeSessionMessageRole
    content: str
    created_at: datetime
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(from_attributes=True)


class MeSessionMessagePagination(Pagination):
    """Pagination metadata for /me/sessions/{id}/messages."""


class MeSessionMessageListResponse(ListResponse[MeSessionMessageItem, Dict[str, Any]]):
    items: List[MeSessionMessageItem]
    pagination: MeSessionMessagePagination
    meta: Dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "MeSessionItem",
    "MeSessionListResponse",
    "MeSessionMessageItem",
    "MeSessionMessageListResponse",
    "MeSessionSource",
]
