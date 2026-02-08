"""Schemas for agent audit log APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.pagination import ListResponse, Pagination


class AgentAuditLogItem(BaseModel):
    id: UUID
    run_id: UUID
    trigger_user_id: UUID
    session_id: Optional[UUID] = None
    message_id: Optional[UUID] = None
    agent_name: str
    tool_name: str
    tool_call_id: Optional[str] = None
    operation: Optional[str] = None
    status: str
    error: Optional[str] = None
    duration_ms: Optional[int] = None
    target_entities: Optional[Dict[str, Any]] = None
    before_snapshot: Optional[Dict[str, Any]] = None
    after_snapshot: Optional[Dict[str, Any]] = None
    extra: Optional[Dict[str, Any]] = None
    created_at: datetime


class AgentAuditPagination(Pagination):
    """Pagination metadata for agent audit logs."""


class AgentAuditListMeta(BaseModel):
    user_id: Optional[UUID] = None
    tool_name: Optional[str] = None
    operation: Optional[str] = None
    status_filter: Optional[str] = None
    run_id: Optional[UUID] = None
    created_before: Optional[datetime] = None
    created_after: Optional[datetime] = None


class AgentAuditLogListResponse(ListResponse[AgentAuditLogItem, AgentAuditListMeta]):
    items: List[AgentAuditLogItem]
    pagination: AgentAuditPagination
    meta: AgentAuditListMeta


class AgentAuditRollbackPreview(BaseModel):
    log: AgentAuditLogItem
    suggested_actions: str


class AgentAuditRetentionRequest(BaseModel):
    before_days: int = Field(..., ge=1, le=365)
    dry_run: bool = False


class AgentAuditRetentionResponse(BaseModel):
    deleted_rows: int
    cutoff: datetime


__all__ = [
    "AgentAuditLogItem",
    "AgentAuditLogListResponse",
    "AgentAuditRollbackPreview",
    "AgentAuditRetentionRequest",
    "AgentAuditRetentionResponse",
]
