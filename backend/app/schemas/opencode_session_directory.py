"""Schemas for the OpenCode sessions directory (global list across agents)."""

from __future__ import annotations

from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.pagination import ListResponse


class OpencodeSessionDirectoryQueryRequest(BaseModel):
    page: int = Field(1, ge=1, description="Page number (1-indexed)")
    size: int = Field(50, ge=1, le=200, description="Page size")
    refresh: bool = Field(
        False,
        description="Force refresh cached entries before listing (best-effort).",
    )


class OpencodeSessionDirectoryItem(BaseModel):
    agent_id: UUID = Field(..., description="Agent id that owns the session")
    agent_source: Literal["personal", "shared"] = Field(
        ..., description="Agent source scope"
    )
    agent_name: str = Field(..., description="Agent display name")
    session_id: str = Field(..., description="OpenCode session id")
    title: str = Field(..., description="OpenCode session title")
    last_active_at: Optional[str] = Field(
        None, description="ISO timestamp of last activity (best-effort)"
    )


class OpencodeSessionDirectoryMeta(BaseModel):
    total_agents: int = 0
    refreshed_agents: int = 0
    cached_agents: int = 0
    partial_failures: int = 0


class OpencodeSessionDirectoryListResponse(
    ListResponse[OpencodeSessionDirectoryItem, OpencodeSessionDirectoryMeta]
):
    pass


__all__ = [
    "OpencodeSessionDirectoryItem",
    "OpencodeSessionDirectoryListResponse",
    "OpencodeSessionDirectoryMeta",
    "OpencodeSessionDirectoryQueryRequest",
]
