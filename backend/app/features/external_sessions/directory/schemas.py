"""Schemas for external session directory aggregation."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.pagination import ListResponse


class ExternalSessionDirectoryQueryRequest(BaseModel):
    page: int = Field(1, ge=1, description="Page number (1-indexed)")
    size: int = Field(50, ge=1, le=200, description="Page size")
    refresh: bool = Field(
        False,
        description="Force refresh cached entries before listing (best-effort).",
    )


class ExternalSessionDirectoryItem(BaseModel):
    provider: str = Field(..., description="External session provider key")
    agent_id: UUID = Field(..., description="Agent id that owns the session")
    agent_source: Literal["personal", "shared"] = Field(
        ..., description="Agent source scope"
    )
    agent_name: str = Field(..., description="Agent display name")
    session_id: str = Field(..., description="External provider session id")
    title: str = Field(..., description="External provider session title")
    last_active_at: str | None = Field(
        None, description="ISO timestamp of last activity (best-effort)"
    )


class ExternalSessionDirectoryMeta(BaseModel):
    provider: str
    total_agents: int = 0
    refreshed_agents: int = 0
    cached_agents: int = 0
    partial_failures: int = 0


class ExternalSessionDirectoryListResponse(
    ListResponse[ExternalSessionDirectoryItem, ExternalSessionDirectoryMeta]
):
    pass
