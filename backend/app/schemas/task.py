"""
Task Pydantic schemas

This module contains all Pydantic schemas for task-related operations.
"""

from datetime import date, datetime
from typing import TYPE_CHECKING, Any, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.constants import (
    PLANNING_CYCLE_DAYS_BY_CALENDAR,
    PLANNING_CYCLE_TYPES,
    TASK_ALLOWED_STATUSES,
)
from app.schemas.pagination import ListResponse, Pagination

if TYPE_CHECKING:
    from app.schemas.person import PersonSummaryResponse
    from app.schemas.vision import VisionSummaryResponse

else:
    # Avoid circular import at runtime
    from app.schemas.vision import VisionSummaryResponse


class TaskBase(BaseModel):
    """Base schema for task data"""

    content: str = Field(
        ..., min_length=1, max_length=500, description="Task description or title"
    )
    priority: int = Field(
        0, description="Task priority (higher numbers = higher priority)"
    )
    estimated_effort: Optional[int] = Field(
        None, ge=0, description="Estimated effort in minutes"
    )
    planning_cycle_type: Optional[str] = Field(
        None, description="Planning cycle type: year, month, week, day"
    )
    planning_cycle_days: Optional[int] = Field(
        None, ge=1, description="Cycle duration in days"
    )
    planning_cycle_start_date: Optional[date] = Field(
        None, description="Cycle start date"
    )

    @field_validator("content")
    @classmethod
    def validate_content(cls, v):
        """Validate task content"""
        if not v or not v.strip():
            raise ValueError("Task content cannot be empty")
        return v.strip()

    @field_validator("planning_cycle_type")
    @classmethod
    def validate_planning_cycle_type(cls, v):
        """Validate planning cycle type"""
        if v is not None and v not in PLANNING_CYCLE_TYPES:
            raise ValueError(
                f"Planning cycle type must be one of: {', '.join(sorted(PLANNING_CYCLE_TYPES))}"
            )
        return v

    @field_validator("planning_cycle_days")
    @classmethod
    def validate_planning_cycle_days(cls, v):
        """Validate planning cycle days"""
        if v is not None and v <= 0:
            raise ValueError("Planning cycle days must be positive")
        return v

    @model_validator(mode="after")
    def validate_planning_cycle_completeness(self) -> "TaskBase":
        """Validate that all planning cycle fields are set together or all are empty"""
        cycle_fields = [
            self.planning_cycle_type,
            self.planning_cycle_days,
            self.planning_cycle_start_date,
        ]

        # Check if any field is set
        any_set = any(field is not None for field in cycle_fields)
        # Check if all fields are set
        all_set = all(field is not None for field in cycle_fields)

        if any_set and not all_set:
            raise ValueError(
                "Planning cycle fields must be set together: planning_cycle_type, "
                "planning_cycle_days, and planning_cycle_start_date must all be provided "
                "or all be empty"
            )

        return self


class TaskCreate(TaskBase):
    """Schema for creating a new task"""

    vision_id: UUID = Field(..., description="UUID of the vision this task belongs to")
    parent_task_id: Optional[UUID] = Field(
        None, description="ID of the parent task (for hierarchical tasks)"
    )
    display_order: int = Field(
        0, ge=0, description="Display order within the same parent/vision"
    )
    person_ids: Optional[List[str]] = Field(
        None, description="List of person IDs to associate with this task"
    )


class TaskUpdate(TaskBase):
    """Schema for updating an existing task"""

    content: Optional[str] = Field(
        None, min_length=1, max_length=500, description="Task description or title"
    )
    notes: Optional[str] = Field(
        None, description="Additional notes or details about the task"
    )
    status: Optional[str] = Field(None, description="Task status")
    priority: Optional[int] = Field(
        None, description="Task priority (higher numbers = higher priority)"
    )
    estimated_effort: Optional[int] = Field(
        None, ge=0, description="Estimated effort in minutes"
    )
    planning_cycle_type: Optional[str] = Field(
        None, description="Planning cycle type: year, month, week, day"
    )
    planning_cycle_days: Optional[int] = Field(
        None, ge=1, description="Cycle duration in days"
    )
    planning_cycle_start_date: Optional[date] = Field(
        None, description="Cycle start date"
    )
    display_order: Optional[int] = Field(
        None, ge=0, description="Display order within the same parent/vision"
    )
    parent_task_id: Optional[UUID] = Field(
        None, description="ID of the parent task (for hierarchical tasks)"
    )
    person_ids: Optional[List[str]] = Field(
        None, description="List of person IDs to associate with this task"
    )

    @field_validator("content")
    @classmethod
    def validate_content(cls, v):
        """Validate task content for updates - allows None but validates non-empty strings"""
        if v is not None:
            if not v or not v.strip():
                raise ValueError("Task content cannot be empty")
            return v.strip()
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v):
        """Validate task status"""
        if v is not None:
            if v not in TASK_ALLOWED_STATUSES:
                raise ValueError(
                    f"Status must be one of: {', '.join(sorted(TASK_ALLOWED_STATUSES))}"
                )
        return v

    @model_validator(mode="after")
    def validate_planning_cycle_completeness(self) -> "TaskUpdate":
        """
        Validate planning cycle fields for TaskUpdate.
        planning_cycle_type and planning_cycle_start_date are required when any planning cycle field is set.
        planning_cycle_days is optional and will be auto-completed if missing.
        """
        cycle_fields = [
            self.planning_cycle_type,
            self.planning_cycle_days,
            self.planning_cycle_start_date,
        ]

        # Check if any field is set
        any_set = any(field is not None for field in cycle_fields)

        if not any_set:
            # All fields are empty - this is valid (clearing planning cycle)
            return self

        # If any planning cycle field is set, planning_cycle_type and planning_cycle_start_date are required
        if self.planning_cycle_type is None:
            raise ValueError(
                "planning_cycle_type is required when updating planning cycle fields"
            )

        if self.planning_cycle_start_date is None:
            raise ValueError(
                "planning_cycle_start_date is required when updating planning cycle fields"
            )

        # Auto-complete planning_cycle_days if missing
        if self.planning_cycle_days is None:
            cycle_days_map = PLANNING_CYCLE_DAYS_BY_CALENDAR.get("gregorian", {})
            self.planning_cycle_days = cycle_days_map.get(self.planning_cycle_type, 1)

        return self


class TaskParentSummary(BaseModel):
    """Compact parent task summary for embedding在其它响应"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(..., description="Parent task UUID")
    content: str = Field(..., description="Parent task title/content")
    status: Optional[str] = Field(
        None, description="Parent task status (optional for quick display)"
    )


class TaskSummaryResponse(BaseModel):
    """Schema for task summary responses (minimal task info)"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(..., description="Task UUID")
    content: str = Field(..., description="Task description or title")
    status: str = Field(..., description="Task status")
    vision_id: UUID = Field(..., description="UUID of the vision this task belongs to")
    parent_task_id: Optional[UUID] = Field(None, description="UUID of the parent task")
    priority: int = Field(..., description="Task priority")
    estimated_effort: Optional[int] = Field(
        None, ge=0, description="Estimated effort in minutes"
    )
    notes_count: int = Field(
        0, ge=0, description="Number of notes associated with this task"
    )
    actual_effort_total: int = Field(
        0, ge=0, description="Total actual effort in minutes"
    )
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    vision_summary: Optional["VisionSummaryResponse"] = Field(
        None,
        description="Optional embedded vision summary for quick display",
    )
    parent_summary: Optional["TaskParentSummary"] = Field(
        None,
        description="Optional embedded summary of the parent task",
    )


class TaskResponse(TaskBase):
    """Schema for task responses"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(..., description="Task UUID")
    vision_id: UUID = Field(..., description="UUID of the vision this task belongs to")
    parent_task_id: Optional[UUID] = Field(None, description="UUID of the parent task")
    status: str = Field(..., description="Task status")
    display_order: int = Field(..., description="Display order")
    # Compatibility field: maps to actual_effort_total in model
    actual_effort: Optional[int] = Field(
        None, description="[Deprecated] Actual effort in minutes (mapped to total)"
    )
    # New fields
    actual_effort_self: int = Field(
        0, ge=0, description="Minutes from ActualEvents directly attached to this task"
    )
    actual_effort_total: int = Field(
        0, ge=0, description="Minutes including this task self and all descendant tasks"
    )
    notes_count: int = Field(
        0, ge=0, description="Number of notes associated with this task"
    )
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    deleted_at: Optional[datetime] = Field(None, description="Soft delete timestamp")
    persons: List["PersonSummaryResponse"] = Field(
        default_factory=list, description="Persons associated with this task"
    )

    @field_validator("persons", mode="before")
    @classmethod
    def ensure_person_summaries(cls, value):
        """Convert ORM Person objects to PersonSummaryResponse before validation."""
        if not value:
            return []

        # Already serialized to summaries
        from app.schemas.person import (  # Late import to avoid cycles
            PersonSummaryResponse,
        )

        if isinstance(value, list):
            if all(isinstance(item, PersonSummaryResponse) for item in value):
                return value

            # Convert SQLAlchemy Person objects using shared utility
            try:
                from app.utils.person_utils import convert_persons_to_summary
            except Exception:
                return value

            converted: List[Any] = []
            for item in value:
                if isinstance(item, PersonSummaryResponse):
                    converted.append(item)
                    continue

                if hasattr(item, "get_primary_nickname"):
                    try:
                        summary = convert_persons_to_summary([item])[0]
                    except Exception:
                        summary = item
                    converted.append(summary)
                else:
                    # Preserve unexpected types so downstream validation can surface errors
                    converted.append(item)

            return converted

        return value


class TaskMoveResponse(TaskResponse):
    """Schema for task move responses including affected descendants"""

    updated_descendants: List["TaskResponse"] = Field(
        default_factory=list,
        description="Descendant tasks that were updated as part of the move operation",
    )


class TaskWithSubtasks(TaskResponse):
    """Schema for task with its subtasks included"""

    subtasks: List["TaskWithSubtasks"] = Field(
        default_factory=list, description="Subtasks of this task"
    )
    completion_percentage: float = Field(
        ..., ge=0.0, le=1.0, description="Completion percentage based on subtasks"
    )
    depth: int = Field(..., ge=0, description="Depth in the task hierarchy")


class TaskHierarchy(BaseModel):
    """Schema for representing task hierarchy"""

    vision_id: UUID = Field(..., description="Vision UUID")
    root_tasks: List[TaskWithSubtasks] = Field(
        default_factory=list, description="Root level tasks with their subtask trees"
    )


class TaskStatusUpdate(BaseModel):
    """Schema for updating task status"""

    status: str = Field(..., description="New task status")

    @field_validator("status")
    @classmethod
    def validate_status(cls, v):
        """Validate task status"""
        if v not in TASK_ALLOWED_STATUSES:
            raise ValueError(
                f"Status must be one of: {', '.join(sorted(TASK_ALLOWED_STATUSES))}"
            )
        return v


class TaskReorderRequest(BaseModel):
    """Schema for reordering tasks"""

    task_orders: List[dict] = Field(
        ..., description="List of task ID and display_order pairs"
    )

    @field_validator("task_orders")
    @classmethod
    def validate_task_orders(cls, v):
        """Validate task order data"""
        for item in v:
            if (
                not isinstance(item, dict)
                or "id" not in item
                or "display_order" not in item
            ):
                raise ValueError("Each item must have 'id' and 'display_order' fields")
            if not isinstance(item["id"], str) or not isinstance(
                item["display_order"], int
            ):
                raise ValueError(
                    "'id' must be UUID string and 'display_order' must be integer"
                )
            if item["display_order"] < 0:
                raise ValueError("display_order must be non-negative")
        return v


class TaskMoveRequest(BaseModel):
    """Schema for moving a task to a different parent or vision"""

    old_parent_task_id: Optional[UUID] = Field(
        None,
        description="Current parent task ID (None for root level, required for accurate effort recalculation)",
    )
    new_parent_task_id: Optional[UUID] = Field(
        None, description="New parent task ID (None for root level)"
    )
    new_vision_id: Optional[UUID] = Field(
        None, description="New vision UUID (if moving to different vision)"
    )
    new_display_order: int = Field(
        0, ge=0, description="New display order in the target location"
    )


class TaskStatsResponse(BaseModel):
    """Schema for task statistics"""

    total_subtasks: int = Field(..., ge=0, description="Total number of subtasks")
    completed_subtasks: int = Field(
        ..., ge=0, description="Number of completed subtasks"
    )
    completion_percentage: float = Field(
        ..., ge=0.0, le=1.0, description="Completion percentage"
    )
    total_estimated_effort: Optional[int] = Field(
        None, ge=0, description="Total estimated effort in minutes"
    )
    total_actual_effort: Optional[int] = Field(
        None, ge=0, description="Total actual effort in minutes"
    )


class TaskPagination(Pagination):
    """Pagination metadata for task lists."""


class TaskListMeta(BaseModel):
    """Additional list metadata for task queries."""

    vision_id: Optional[UUID] = None
    vision_in: Optional[str] = None
    status_filter: Optional[str] = None
    status_in: Optional[str] = None
    exclude_status: Optional[str] = None
    planning_cycle_type: Optional[str] = None
    planning_cycle_start_date: Optional[date] = None
    fields: Optional[str] = None


class TaskQueryRequest(BaseModel):
    """Schema for POST-based task list queries."""

    page: int = Field(1, ge=1, description="Page number (1-indexed)")
    size: int = Field(100, ge=1, description="Maximum number of records to return")
    vision_id: Optional[UUID] = None
    vision_ids: Optional[List[UUID]] = None
    status_filter: Optional[str] = None
    status_in: Optional[List[str]] = None
    exclude_status: Optional[List[str]] = None
    planning_cycle_type: Optional[str] = None
    planning_cycle_start_date: Optional[date] = None
    fields: str = Field("basic", description="Response fields: basic or full")


class TaskListResponse(ListResponse[TaskResponse, TaskListMeta]):
    """Schema for task list response"""

    items: List["TaskResponse"]
    pagination: TaskPagination
    meta: TaskListMeta


# Forward references will be resolved automatically by Pydantic
