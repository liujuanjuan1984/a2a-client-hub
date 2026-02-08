"""Task-related tools exposed to the agent layer."""

import sys
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.agents.tools.arg_utils import normalize_uuid_list, parse_uuid_list_argument
from app.agents.tools.audit_utils import audit_for_entity, ensure_snapshot
from app.agents.tools.base import AbstractTool, ToolMetadata
from app.agents.tools.responses import (
    ToolResult,
    create_tool_error,
    create_tool_response,
    serialize_entity,
)
from app.core.constants import PLANNING_CYCLE_DAYS_BY_CALENDAR
from app.core.logging import get_logger, log_exception
from app.handlers import tasks as task_service
from app.handlers.tasks import (
    InvalidOperationError,
    InvalidStatusError,
    TaskNotFoundError,
)
from app.schemas.task import TaskCreate, TaskUpdate
from app.utils.timezone_util import utc_today

logger = get_logger(__name__)

_DEFAULT_CALENDAR = PLANNING_CYCLE_DAYS_BY_CALENDAR.get("gregorian", {})


def resolve_planning_cycle_days(
    planning_cycle_type: Optional[str], planning_cycle_days: Optional[int]
) -> Optional[int]:
    """Autofill planning_cycle_days based on cycle type when absent."""

    if planning_cycle_type and planning_cycle_days is None:
        return _DEFAULT_CALENDAR.get(planning_cycle_type, planning_cycle_days)
    return planning_cycle_days


class ListTasksByPlanningCycleArgs(BaseModel):
    """Arguments for listing tasks by planning cycle."""

    planning_cycle_type: str = Field(
        ..., description="Planning cycle type: day, week, month, year"
    )
    planning_cycle_start_date: str = Field(
        ..., description="ISO date (YYYY-MM-DD) to filter planning cycles by start date"
    )
    skip: int = Field(0, ge=0, le=1000, description="Number of tasks to skip.")
    limit: int = Field(
        50,
        ge=1,
        le=500,
        description="Maximum number of tasks to return (1-500).",
    )


class ListTasksByPlanningCycleTool(AbstractTool):
    """Tool that lists tasks for a specific planning cycle."""

    name = "list_tasks_by_planning_cycle"
    description = (
        "List tasks for a specific planning cycle (day/week/month/year)."
        " This tool is read-only and does not modify tasks."
    )
    args_schema = ListTasksByPlanningCycleArgs
    metadata = ToolMetadata(
        read_only=True,
        labels=("tasks", "read"),
        default_timeout=20.0,
    )

    async def execute(
        self,
        planning_cycle_type: str,
        planning_cycle_start_date: str,
        skip: int = 0,
        limit: int = 50,
    ) -> ToolResult:
        try:
            db = self._ensure_db()
            tasks = await task_service.list_tasks(
                db=db,
                user_id=self.user_id,
                skip=skip,
                limit=limit,
                planning_cycle_type=planning_cycle_type,
                planning_cycle_start_date=planning_cycle_start_date,
            )
            payload = {
                "tasks": [serialize_entity(task, "task") for task in tasks if task],
                "count": len(tasks),
                "skip": skip,
                "limit": limit,
                "planning_cycle_type": planning_cycle_type,
                "planning_cycle_start_date": planning_cycle_start_date,
            }
            return create_tool_response(data=payload)
        except InvalidStatusError as exc:
            return create_tool_error(
                "Invalid task status",
                kind="validation_error",
                detail=str(exc),
            )
        except InvalidOperationError as exc:
            return create_tool_error(
                "Invalid task filter",
                kind="validation_error",
                detail=str(exc),
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(
                logger, f"Error listing tasks by planning cycle: {exc}", sys.exc_info()
            )
            return create_tool_error(
                "Failed to list tasks by planning cycle", detail=str(exc)
            )


class ListTasksByVisionAndStatusArgs(BaseModel):
    """Arguments for listing tasks by vision and status."""

    vision_id: UUID = Field(..., description="Vision ID to filter tasks.")
    status: Optional[str] = Field(
        None,
        description="Optional status filter (todo, in_progress, done, archived, etc.). If not provided, returns all statuses.",
    )
    content: Optional[str] = Field(
        None,
        description="Exact task content to filter under the given vision.",
    )
    skip: int = Field(0, ge=0, le=1000, description="Number of tasks to skip.")
    limit: int = Field(
        50,
        ge=1,
        le=500,
        description="Maximum number of tasks to return (1-500).",
    )


class ListTasksByVisionAndStatusTool(AbstractTool):
    """Tool that lists tasks for a specific vision and optional status."""

    name = "list_tasks_by_vision_and_status"
    description = (
        "List tasks for a specific vision with optional status filtering."
        " Returns read-only task summaries."
    )
    args_schema = ListTasksByVisionAndStatusArgs
    metadata = ToolMetadata(
        read_only=True,
        labels=("tasks", "read"),
        default_timeout=20.0,
    )

    async def execute(
        self,
        vision_id: UUID,
        status: Optional[str] = None,
        content: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> ToolResult:
        try:
            db = self._ensure_db()
            tasks = await task_service.list_tasks(
                db=db,
                user_id=self.user_id,
                skip=skip,
                limit=limit,
                vision_id=vision_id,
                status_filter=status,
                content=content,
            )
            payload = {
                "tasks": [serialize_entity(task, "task") for task in tasks if task],
                "count": len(tasks),
                "skip": skip,
                "limit": limit,
                "vision_id": vision_id,
                "status": status,
            }
            return create_tool_response(data=payload)
        except InvalidStatusError as exc:
            return create_tool_error(
                "Invalid task status",
                kind="validation_error",
                detail=str(exc),
            )
        except InvalidOperationError as exc:
            return create_tool_error(
                "Invalid task filter",
                kind="validation_error",
                detail=str(exc),
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(
                logger,
                f"Error listing tasks by vision and status: {exc}",
                sys.exc_info(),
            )
            return create_tool_error(
                "Failed to list tasks by vision and status", detail=str(exc)
            )


class GetTaskDetailArgs(BaseModel):
    """Arguments for retrieving task detail."""

    task_id: UUID = Field(..., description="Task identifier to retrieve.")
    include_subtasks: bool = Field(
        True,
        description="Whether to include nested subtasks in the response.",
    )


class GetTaskDetailTool(AbstractTool):
    """Tool that returns details for a single task."""

    name = "get_task_detail"
    description = (
        "Retrieve a task, optionally including nested subtasks."
        " This tool does not modify task data."
    )
    args_schema = GetTaskDetailArgs
    metadata = ToolMetadata(
        read_only=True,
        labels=("tasks", "read"),
        default_timeout=20.0,
    )

    async def execute(self, task_id: UUID, include_subtasks: bool = True) -> ToolResult:
        try:
            db = self._ensure_db()
            if include_subtasks:
                task = await task_service.get_task_with_subtasks(
                    db=db, user_id=self.user_id, task_id=task_id
                )
                serialized = serialize_entity(task, "task")
            else:
                task = await task_service.get_task(
                    db=db, user_id=self.user_id, task_id=task_id
                )
                if task is None:
                    raise TaskNotFoundError("Task not found")
                serialized = serialize_entity(task, "task")

            return create_tool_response(data={"task": serialized})
        except TaskNotFoundError as exc:
            return create_tool_error(
                "Task not found",
                kind="not_found",
                detail=str(exc),
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(
                logger, f"Error retrieving task detail: {exc}", sys.exc_info()
            )
            return create_tool_error("Failed to retrieve task detail", detail=str(exc))


class CreateTaskArgs(BaseModel):
    """Arguments for creating a task."""

    content: str = Field(
        ..., min_length=1, max_length=500, description="Task description or title"
    )
    vision_id: UUID = Field(..., description="ID of the vision this task belongs to")
    parent_task_id: Optional[UUID] = Field(
        None, description="ID of the parent task (for hierarchical tasks)"
    )
    notes: Optional[str] = Field(
        None, description="Additional notes or details about the task"
    )
    priority: int = Field(
        0,
        ge=0,
        description="Task priority (higher numbers = higher priority)",
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
    planning_cycle_start_date: Optional[str] = Field(
        None, description="Cycle start date (YYYY-MM-DD)"
    )
    display_order: int = Field(
        0, ge=0, description="Display order within the same parent/vision"
    )
    person_ids: Optional[list[UUID]] = Field(
        None, description="List of person IDs to associate with this task"
    )

    @field_validator("person_ids", mode="before")
    @classmethod
    def _coerce_person_ids(cls, value):
        return parse_uuid_list_argument(value, field_name="person_ids")


class CreateTaskTool(AbstractTool):
    """Tool that creates a new task."""

    name = "create_task"
    description = (
        "Create and persist a new task for the current user."
        " Supports optional parent relationships, planning cycles, and person associations."
    )
    args_schema = CreateTaskArgs
    metadata = ToolMetadata(
        read_only=False,
        requires_confirmation=False,
        idempotent=False,
        labels=("tasks", "write"),
        default_timeout=30.0,
    )

    async def execute(
        self,
        content: str,
        vision_id: UUID,
        parent_task_id: Optional[UUID] = None,
        notes: Optional[str] = None,
        priority: int = 0,
        estimated_effort: Optional[int] = None,
        planning_cycle_type: Optional[str] = None,
        planning_cycle_days: Optional[int] = None,
        planning_cycle_start_date: Optional[str] = None,
        display_order: int = 0,
        person_ids: Optional[list[UUID]] = None,
    ) -> ToolResult:
        try:
            db = self._ensure_db()
            normalized_person_ids = normalize_uuid_list(person_ids)
            resolved_cycle_days = resolve_planning_cycle_days(
                planning_cycle_type, planning_cycle_days
            )
            task_data = TaskCreate(
                content=content,
                vision_id=vision_id,
                parent_task_id=parent_task_id,
                notes=notes,
                priority=priority,
                estimated_effort=estimated_effort,
                planning_cycle_type=planning_cycle_type,
                planning_cycle_days=resolved_cycle_days,
                planning_cycle_start_date=planning_cycle_start_date,
                display_order=display_order,
                person_ids=normalized_person_ids,
            )
            task = await task_service.create_task(
                db=db, user_id=self.user_id, task_data=task_data
            )
            serialized = serialize_entity(task, "task")
            audit = audit_for_entity(
                "tasks.create",
                entity_type="task",
                entity_id=getattr(task, "id", None),
                after_snapshot=serialized,
            )
            return create_tool_response(data={"task": serialized}, audit=audit)
        except InvalidOperationError as exc:
            return create_tool_error(
                "Invalid task operation",
                kind="validation_error",
                detail=str(exc),
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(logger, f"Error creating task: {exc}", sys.exc_info())
            return create_tool_error("Failed to create task", detail=str(exc))


class UpdateTaskArgs(BaseModel):
    """
    Arguments for updating a task.

    Omit optional fields to keep their current values. Nullable fields (notes,
    estimated_effort, planning cycle fields, parent_task_id, person_ids) accept explicit
    null/[] to clear data or unlink associations.
    """

    task_id: UUID = Field(..., description="Task identifier to update.")
    content: Optional[str] = Field(
        None,
        description="Updated task description or title; omit to keep (cannot be null).",
    )
    notes: Optional[str] = Field(
        None,
        description="Updated notes; omit to keep them or set null to clear existing notes.",
    )
    status: Optional[str] = Field(
        None,
        description="Updated task status; omit to keep current status (cannot be null).",
    )
    priority: Optional[int] = Field(
        None,
        ge=0,
        description="Updated task priority; omit to keep it (cannot be set to null).",
    )
    estimated_effort: Optional[int] = Field(
        None,
        ge=0,
        description="Updated estimated effort in minutes; omit to keep or set null to clear it.",
    )
    planning_cycle_type: Optional[str] = Field(
        None,
        description=(
            "Updated planning cycle type (year/month/week/day); omit to keep, "
            "or set to null alongside the other planning cycle fields to remove scheduling."
        ),
    )
    planning_cycle_days: Optional[int] = Field(
        None,
        ge=1,
        description="Updated cycle duration in days; omit to keep or set null when clearing the cycle.",
    )
    planning_cycle_start_date: Optional[str] = Field(
        None,
        description="Updated cycle start date (YYYY-MM-DD); omit to keep or set null when clearing the cycle.",
    )
    display_order: Optional[int] = Field(
        None,
        ge=0,
        description="Updated display order; omit to keep (cannot be set to null).",
    )
    parent_task_id: Optional[UUID] = Field(
        None,
        description="Updated parent task; omit to keep or set null to convert the task into a root task.",
    )
    person_ids: Optional[list[UUID]] = Field(
        None,
        description="Updated person associations; omit to keep them or pass null/[] to remove all links.",
    )

    @field_validator("person_ids", mode="before")
    @classmethod
    def _coerce_person_ids(cls, value):
        return parse_uuid_list_argument(value, field_name="person_ids")


class UpdateTaskTool(AbstractTool):
    """Tool that updates an existing task."""

    name = "update_task"
    description = (
        "Update an existing task for the current user. Omit properties to keep them "
        "unchanged; set nullable fields (notes, estimated effort, planning cycle, "
        "parent/person links) to null/[] to clear their values."
    )
    args_schema = UpdateTaskArgs
    metadata = ToolMetadata(
        read_only=False,
        requires_confirmation=False,
        idempotent=False,
        labels=("tasks", "write"),
        default_timeout=30.0,
    )

    async def execute(
        self,
        task_id: UUID,
        content: Optional[str] = None,
        notes: Optional[str] = None,
        status: Optional[str] = None,
        priority: Optional[int] = None,
        estimated_effort: Optional[int] = None,
        planning_cycle_type: Optional[str] = None,
        planning_cycle_days: Optional[int] = None,
        planning_cycle_start_date: Optional[str] = None,
        display_order: Optional[int] = None,
        parent_task_id: Optional[UUID] = None,
        person_ids: Optional[list[UUID]] = None,
    ) -> ToolResult:
        try:
            db = self._ensure_db()
            # Convert string date to date object if provided
            planning_cycle_start_date_obj = None
            if planning_cycle_type and not planning_cycle_start_date:
                planning_cycle_start_date_obj = utc_today()
            if planning_cycle_start_date:
                planning_cycle_start_date_obj = datetime.fromisoformat(
                    planning_cycle_start_date
                ).date()

            existing = await task_service.get_task(
                db=db, user_id=self.user_id, task_id=task_id
            )
            if existing is None:
                raise TaskNotFoundError("Task not found")
            before_snapshot = ensure_snapshot(existing, "task")

            # Create TaskUpdate with all provided fields
            # Pydantic will handle exclude_unset automatically in the service layer
            normalized_person_ids = normalize_uuid_list(person_ids)
            resolved_cycle_days = resolve_planning_cycle_days(
                planning_cycle_type, planning_cycle_days
            )
            update_data = TaskUpdate(
                content=content,
                notes=notes,
                status=status,
                priority=priority,
                estimated_effort=estimated_effort,
                planning_cycle_type=planning_cycle_type,
                planning_cycle_days=resolved_cycle_days,
                planning_cycle_start_date=planning_cycle_start_date_obj,
                display_order=display_order,
                parent_task_id=parent_task_id,
                person_ids=normalized_person_ids,
            )
            task = await task_service.update_task(
                db=db, user_id=self.user_id, task_id=task_id, task_data=update_data
            )
            serialized = serialize_entity(task, "task")
            audit = audit_for_entity(
                "tasks.update",
                entity_type="task",
                entity_id=task_id,
                before_snapshot=before_snapshot,
                after_snapshot=serialized,
            )
            return create_tool_response(data={"task": serialized}, audit=audit)
        except TaskNotFoundError as exc:
            return create_tool_error(
                "Task not found",
                kind="not_found",
                detail=str(exc),
            )
        except InvalidStatusError as exc:
            return create_tool_error(
                "Invalid task status",
                kind="validation_error",
                detail=str(exc),
            )
        except InvalidOperationError as exc:
            return create_tool_error(
                "Invalid task operation",
                kind="validation_error",
                detail=str(exc),
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(logger, f"Error updating task: {exc}", sys.exc_info())
            return create_tool_error("Failed to update task", detail=str(exc))


class DeleteTaskArgs(BaseModel):
    """Arguments for deleting a task."""

    task_id: UUID = Field(..., description="Task identifier to delete.")


class DeleteTaskTool(AbstractTool):
    """Tool that deletes a task."""

    name = "delete_task"
    description = "Delete a task."
    args_schema = DeleteTaskArgs
    metadata = ToolMetadata(
        read_only=False,
        requires_confirmation=False,
        idempotent=False,
        labels=("tasks", "write"),
        default_timeout=20.0,
    )

    async def execute(self, task_id: UUID) -> ToolResult:
        try:
            db = self._ensure_db()
            success = await task_service.delete_task(
                db=db,
                user_id=self.user_id,
                task_id=task_id,
                hard_delete=False,
            )
            if not success:
                raise TaskNotFoundError("Task not found")
            audit = audit_for_entity(
                "tasks.delete",
                entity_type="task",
                entity_id=task_id,
                extra={"hard_delete": False},
            )
            return create_tool_response(data={"task_id": str(task_id)}, audit=audit)
        except TaskNotFoundError as exc:
            return create_tool_error(
                "Task not found",
                kind="not_found",
                detail=str(exc),
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(logger, f"Error deleting task: {exc}", sys.exc_info())
            return create_tool_error("Failed to delete task", detail=str(exc))


__all__ = [
    "ListTasksByPlanningCycleTool",
    "ListTasksByVisionAndStatusTool",
    "GetTaskDetailTool",
    "CreateTaskTool",
    "UpdateTaskTool",
    "DeleteTaskTool",
]
