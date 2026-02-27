"""Pydantic schemas for scheduled A2A task APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.pagination import ListResponse, Pagination

A2AScheduleCycleType = Literal[
    "daily",
    "weekly",
    "monthly",
    "interval",
    "sequential",
]
A2AScheduleRunStatus = Literal["idle", "running", "success", "failed"]
A2AScheduleExecutionStatus = Literal["running", "success", "failed"]
A2AScheduleConversationPolicy = Literal["new_each_run", "reuse_single"]


class A2AScheduleTaskBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    agent_id: UUID
    prompt: str = Field(..., min_length=1, max_length=128_000)
    cycle_type: A2AScheduleCycleType
    time_point: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Scheduling parameters by cycle_type. "
            "daily: {time:'HH:MM'}; "
            "weekly: {time:'HH:MM', weekday:1..7 (1=Monday, 7=Sunday)}; "
            "monthly: {time:'HH:MM', day:1..31}; "
            "interval: {minutes:int, start_at_local?: str ('YYYY-MM-DDTHH:MM')}; "
            "sequential: {minutes:int}."
        ),
    )


class A2AScheduleTaskCreate(A2AScheduleTaskBase):
    enabled: bool = True
    conversation_policy: A2AScheduleConversationPolicy = "new_each_run"
    schedule_timezone: str = Field(..., min_length=1, max_length=64)


class A2AScheduleTaskUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    agent_id: Optional[UUID] = None
    prompt: Optional[str] = Field(default=None, min_length=1, max_length=128_000)
    cycle_type: Optional[A2AScheduleCycleType] = None
    time_point: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None
    conversation_policy: Optional[A2AScheduleConversationPolicy] = None
    schedule_timezone: Optional[str] = Field(default=None, min_length=1, max_length=64)


class A2AScheduleTaskResponse(A2AScheduleTaskBase):
    id: UUID
    schedule_timezone: str
    conversation_id: Optional[UUID] = None
    conversation_policy: A2AScheduleConversationPolicy
    enabled: bool
    next_run_at_utc: Optional[datetime] = None
    next_run_at_local: Optional[str] = None
    last_run_at: Optional[datetime] = None
    last_run_status: A2AScheduleRunStatus = "idle"
    consecutive_failures: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class A2AScheduleTaskPagination(Pagination):
    """Pagination metadata for schedule task listings."""


class A2AScheduleTaskListMeta(BaseModel):
    """Additional list metadata for schedule task listings."""


class A2AScheduleTaskListResponse(
    ListResponse[A2AScheduleTaskResponse, A2AScheduleTaskListMeta]
):
    items: List[A2AScheduleTaskResponse]
    pagination: A2AScheduleTaskPagination
    meta: A2AScheduleTaskListMeta


class A2AScheduleExecutionResponse(BaseModel):
    id: UUID
    task_id: UUID
    status: A2AScheduleExecutionStatus
    scheduled_for: datetime
    started_at: datetime
    finished_at: Optional[datetime] = None
    error_message: Optional[str] = None
    response_content: Optional[str] = None
    conversation_id: Optional[UUID] = None
    user_message_id: Optional[UUID] = None
    agent_message_id: Optional[UUID] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class A2AScheduleExecutionPagination(Pagination):
    """Pagination metadata for execution listings."""


class A2AScheduleExecutionListMeta(BaseModel):
    task_id: UUID


class A2AScheduleExecutionListResponse(
    ListResponse[A2AScheduleExecutionResponse, A2AScheduleExecutionListMeta]
):
    items: List[A2AScheduleExecutionResponse]
    pagination: A2AScheduleExecutionPagination
    meta: A2AScheduleExecutionListMeta


class A2AScheduleToggleResponse(BaseModel):
    id: UUID
    schedule_timezone: str
    enabled: bool
    next_run_at_utc: Optional[datetime] = None
    next_run_at_local: Optional[str] = None


class A2AScheduleManualFailRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


__all__ = [
    "A2AScheduleConversationPolicy",
    "A2AScheduleCycleType",
    "A2AScheduleExecutionListMeta",
    "A2AScheduleExecutionListResponse",
    "A2AScheduleExecutionPagination",
    "A2AScheduleExecutionResponse",
    "A2AScheduleManualFailRequest",
    "A2AScheduleTaskCreate",
    "A2AScheduleTaskListMeta",
    "A2AScheduleTaskListResponse",
    "A2AScheduleTaskPagination",
    "A2AScheduleTaskResponse",
    "A2AScheduleTaskUpdate",
    "A2AScheduleToggleResponse",
]
