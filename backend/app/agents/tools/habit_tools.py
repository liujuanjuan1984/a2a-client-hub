"""Habit-related tools exposed to the agent layer."""

import sys
from datetime import date
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.agents.tools.audit_utils import audit_for_entity, ensure_snapshot
from app.agents.tools.base import AbstractTool, ToolMetadata
from app.agents.tools.responses import (
    ToolResult,
    create_tool_error,
    create_tool_response,
    serialize_entity,
)
from app.core.constants import MAX_HABIT_ACTION_WINDOW_DAYS
from app.core.logging import get_logger, log_exception
from app.handlers import habits as habit_service
from app.handlers.habits import (
    HabitActionNotFoundError,
    HabitNotFoundError,
    InvalidOperationError,
    ValidationError,
)
from app.schemas.habit import HabitActionUpdate, HabitCreate, HabitUpdate

logger = get_logger(__name__)


class ListHabitsArgs(BaseModel):
    """Arguments for listing habits."""

    status: Optional[str] = Field(
        None,
        description="Optional status filter (active, completed, paused, expired).",
    )
    title: Optional[str] = Field(
        None, description="Exact habit title filter for deduplication."
    )
    active_window_only: bool = Field(
        False,
        description="If true, only habits whose date window includes today are returned.",
    )
    page: int = Field(1, ge=1, description="Page number (1-indexed).")
    size: int = Field(
        20,
        ge=1,
        le=200,
        description="Page size / number of habits per page (1-200).",
    )


class ListHabitsTool(AbstractTool):
    """Tool that lists the user's habits."""

    name = "list_habits"
    description = (
        "List habits for the current user with optional status filtering."
        " Read-only helper for overviews."
    )
    args_schema = ListHabitsArgs
    metadata = ToolMetadata(
        read_only=True,
        labels=("habits", "read"),
        default_timeout=20.0,
    )

    async def execute(
        self,
        status: Optional[str] = None,
        title: Optional[str] = None,
        active_window_only: bool = False,
        page: int = 1,
        size: int = 20,
    ) -> ToolResult:
        try:
            db = self._ensure_db()
            skip = (page - 1) * size
            overviews, total = await habit_service.list_habit_overviews(
                db=db,
                user_id=self.user_id,
                skip=skip,
                limit=size,
                status_filter=status,
                title=title,
                active_window_only=active_window_only,
            )
            serialized = [
                {
                    "habit": serialize_entity(entry["habit"], "habit"),
                    "stats": entry["stats"],
                }
                for entry in overviews
            ]
            pages = (total + size - 1) // size if size else 0
            return create_tool_response(
                data={
                    "items": serialized,
                    "pagination": {
                        "page": page,
                        "size": size,
                        "total": total,
                        "pages": pages,
                    },
                    "meta": {
                        "status_filter": status,
                        "title": title,
                        "active_window_only": active_window_only,
                    },
                }
            )
        except ValidationError as exc:
            return create_tool_error(
                "Invalid habit filter", kind="validation_error", detail=str(exc)
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(logger, f"Error listing habits: {exc}", sys.exc_info())
            return create_tool_error("Failed to list habits", detail=str(exc))


class GetHabitActionsArgs(BaseModel):
    """Arguments for retrieving actions of a habit."""

    habit_id: UUID = Field(..., description="The habit ID to query.")
    status: Optional[str] = Field(
        None,
        description="Optional action status filter (pending, done, skip, miss).",
    )
    page: int = Field(1, ge=1, description="Page number (1-indexed).")
    size: int = Field(
        31,
        ge=1,
        le=200,
        description="Page size / number of actions per page (1-200).",
    )
    center_date: Optional[date] = Field(
        None, description="Reference date for window queries (YYYY-MM-DD)."
    )
    days_before: Optional[int] = Field(
        None,
        ge=0,
        le=100,
        description="Days before the reference date to include (default 5 when used).",
    )
    days_after: Optional[int] = Field(
        None,
        ge=0,
        le=100,
        description="Days after the reference date to include (default same as days_before).",
    )


class GetHabitActionsTool(AbstractTool):
    """Tool that retrieves daily actions for a specific habit."""

    name = "get_habit_actions"
    description = (
        "Retrieve habit action records for a given habit ID."
        " Read-only timeline; does not change habit progress."
    )
    args_schema = GetHabitActionsArgs
    metadata = ToolMetadata(
        read_only=True,
        labels=("habits", "read"),
        default_timeout=20.0,
    )

    async def execute(
        self,
        habit_id: UUID,
        status: Optional[str] = None,
        page: int = 1,
        size: int = 31,
        center_date: Optional[date] = None,
        days_before: Optional[int] = None,
        days_after: Optional[int] = None,
    ) -> ToolResult:
        try:
            db = self._ensure_db()
            skip = (page - 1) * size
            actions, total = await habit_service.get_habit_actions(
                db=db,
                user_id=self.user_id,
                habit_id=habit_id,
                skip=skip,
                limit=size,
                status_filter=status,
                center_date=center_date,
                days_before=days_before,
                days_after=days_after,
            )
            serialized = [
                serialize_entity(action, "habit_action") for action in actions
            ]
            pages = (total + size - 1) // size if size else 0
            return create_tool_response(
                data={
                    "items": serialized,
                    "pagination": {
                        "page": page,
                        "size": size,
                        "total": total,
                        "pages": pages,
                    },
                    "meta": {
                        "habit_id": str(habit_id),
                        "status_filter": status,
                        "center_date": center_date,
                        "days_before": days_before,
                        "days_after": days_after,
                    },
                }
            )
        except HabitNotFoundError as exc:
            return create_tool_error(
                "Habit not found",
                kind="not_found",
                detail=str(exc),
            )
        except ValidationError as exc:
            return create_tool_error(
                "Invalid habit action filter",
                kind="validation_error",
                detail=str(exc),
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(
                logger, f"Error retrieving habit actions: {exc}", sys.exc_info()
            )
            return create_tool_error(
                "Failed to retrieve habit actions", detail=str(exc)
            )


class CreateHabitArgs(HabitCreate):
    """Arguments for creating a habit."""

    duration_days: int = Field(..., ge=1, description="Duration in days (>=1)")


class CreateHabitTool(AbstractTool):
    """Tool that creates a new habit."""

    name = "create_habit"
    description = (
        "Create and persist a new habit with specified start date and duration."
        " Associations to tasks are optional."
    )
    args_schema = CreateHabitArgs
    metadata = ToolMetadata(
        read_only=False,
        requires_confirmation=False,
        idempotent=False,
        labels=("habits", "write"),
        default_timeout=30.0,
    )

    async def execute(
        self,
        title: str,
        start_date: date,
        duration_days: int,
        description: Optional[str] = None,
        task_id: Optional[UUID] = None,
    ) -> ToolResult:
        try:
            db = self._ensure_db()
            habit_data = HabitCreate(
                title=title,
                description=description,
                start_date=start_date,
                duration_days=duration_days,
                task_id=task_id,
            )
            habit = await habit_service.create_habit(
                db=db, user_id=self.user_id, habit_in=habit_data
            )
            serialized = serialize_entity(habit, "habit")
            audit = audit_for_entity(
                "habits.create",
                entity_type="habit",
                entity_id=getattr(habit, "id", None),
                after_snapshot=serialized,
            )
            return create_tool_response(data={"habit": serialized}, audit=audit)
        except ValidationError as exc:
            return create_tool_error(
                "Invalid habit data",
                kind="validation_error",
                detail=str(exc),
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(logger, f"Error creating habit: {exc}", sys.exc_info())
            return create_tool_error("Failed to create habit", detail=str(exc))


class UpdateHabitArgs(HabitUpdate):
    """
    Arguments for updating a habit.

    Omit optional fields to keep their current values. Only nullable fields (description, task_id)
    support clearing via explicit null.
    """

    habit_id: UUID = Field(..., description="Habit identifier to update.")
    duration_days: Optional[int] = Field(
        None,
        ge=1,
        description="Updated duration in days (>=1); omit to keep it (cannot be null).",
    )


class UpdateHabitTool(AbstractTool):
    """Tool that updates an existing habit."""

    name = "update_habit"
    description = (
        "Update an existing habit. Omit properties to keep them unchanged; "
        "set nullable ones (description/task_id) to null to clear their values."
    )
    args_schema = UpdateHabitArgs
    metadata = ToolMetadata(
        read_only=False,
        requires_confirmation=False,
        idempotent=False,
        labels=("habits", "write"),
        default_timeout=30.0,
    )

    async def execute(
        self,
        habit_id: UUID,
        title: Optional[str] = None,
        description: Optional[str] = None,
        start_date: Optional[date] = None,
        duration_days: Optional[int] = None,
        status: Optional[str] = None,
        task_id: Optional[UUID] = None,
    ) -> ToolResult:
        try:
            db = self._ensure_db()
            existing = await habit_service.get_habit(
                db=db, user_id=self.user_id, habit_id=habit_id
            )
            if existing is None:
                raise HabitNotFoundError("Habit not found")
            before_snapshot = ensure_snapshot(existing, "habit")

            update_data = HabitUpdate(
                title=title,
                description=description,
                start_date=start_date,
                duration_days=duration_days,
                status=status,
                task_id=task_id,
            )
            habit = await habit_service.update_habit(
                db=db,
                user_id=self.user_id,
                habit_id=habit_id,
                habit_update=update_data,
            )
            if habit is None:
                raise HabitNotFoundError("Habit not found")

            serialized = serialize_entity(habit, "habit")
            audit = audit_for_entity(
                "habits.update",
                entity_type="habit",
                entity_id=habit_id,
                before_snapshot=before_snapshot,
                after_snapshot=serialized,
            )
            return create_tool_response(data={"habit": serialized}, audit=audit)
        except HabitNotFoundError as exc:
            return create_tool_error(
                "Habit not found",
                kind="not_found",
                detail=str(exc),
            )
        except ValidationError as exc:
            return create_tool_error(
                "Invalid habit data",
                kind="validation_error",
                detail=str(exc),
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(logger, f"Error updating habit: {exc}", sys.exc_info())
            return create_tool_error("Failed to update habit", detail=str(exc))


class DeleteHabitArgs(BaseModel):
    """Arguments for deleting a habit."""

    habit_id: UUID = Field(..., description="Habit identifier to delete.")


class DeleteHabitTool(AbstractTool):
    """Tool that deletes a habit."""

    name = "delete_habit"
    description = "Delete a habit."
    args_schema = DeleteHabitArgs
    metadata = ToolMetadata(
        read_only=False,
        requires_confirmation=False,
        idempotent=False,
        labels=("habits", "write"),
        default_timeout=20.0,
    )

    async def execute(self, habit_id: UUID) -> ToolResult:
        try:
            db = self._ensure_db()
            existing = await habit_service.get_habit(
                db=db, user_id=self.user_id, habit_id=habit_id
            )
            if existing is None:
                raise HabitNotFoundError("Habit not found")
            before_snapshot = ensure_snapshot(existing, "habit")

            success = await habit_service.delete_habit(
                db=db,
                user_id=self.user_id,
                habit_id=habit_id,
                hard_delete=False,
            )
            if not success:
                raise HabitNotFoundError("Habit not found")

            audit = audit_for_entity(
                "habits.delete",
                entity_type="habit",
                entity_id=habit_id,
                before_snapshot=before_snapshot,
                extra={"hard_delete": False},
            )
            return create_tool_response(
                data={
                    "message": f"Habit {habit_id} successfully deleted",
                    "habit_id": habit_id,
                },
                audit=audit,
            )
        except HabitNotFoundError as exc:
            return create_tool_error(
                "Habit not found",
                kind="not_found",
                detail=str(exc),
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(logger, f"Error deleting habit: {exc}", sys.exc_info())
            return create_tool_error("Failed to delete habit", detail=str(exc))


class GetHabitOverviewArgs(BaseModel):
    """Arguments for retrieving a habit overview."""

    habit_id: UUID = Field(..., description="Habit identifier to retrieve.")


class GetHabitOverviewTool(AbstractTool):
    """Tool that returns habit detail together with statistics."""

    name = "get_habit_overview"
    description = (
        "Retrieve a habit along with its calculated statistics."
        " Useful for presenting comprehensive progress summaries."
    )
    args_schema = GetHabitOverviewArgs
    metadata = ToolMetadata(
        read_only=True,
        labels=("habits", "read"),
        default_timeout=20.0,
    )

    async def execute(self, habit_id: UUID) -> ToolResult:
        try:
            db = self._ensure_db()
            overview = await habit_service.get_habit_overview(
                db=db, user_id=self.user_id, habit_id=habit_id
            )

            return create_tool_response(
                data={
                    "habit": serialize_entity(overview["habit"], "habit"),
                    "stats": overview["stats"],
                }
            )
        except HabitNotFoundError as exc:
            return create_tool_error(
                "Habit not found",
                kind="not_found",
                detail=str(exc),
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(
                logger, f"Error retrieving habit overview: {exc}", sys.exc_info()
            )
            return create_tool_error(
                "Failed to retrieve habit overview", detail=str(exc)
            )


class LogHabitActionArgs(BaseModel):
    """Arguments for logging (updating) a habit action by date."""

    habit_id: UUID = Field(..., description="Habit identifier.")
    action_date: date = Field(
        ..., description="Date of the action to update (YYYY-MM-DD)."
    )
    status: str = Field(
        ...,
        description="New action status (pending, done, skip, miss).",
    )
    notes: Optional[str] = Field(
        None, description="Optional notes describing the check-in."
    )
    window_days: int = Field(
        3,
        ge=0,
        le=MAX_HABIT_ACTION_WINDOW_DAYS // 2,
        description="Number of days before/after the target date to search (default 3).",
    )


class LogHabitActionTool(AbstractTool):
    """Tool that finds an action by date and updates its status/notes."""

    name = "log_habit_action"
    description = (
        "Check-in a habit action by specifying the date, desired status, and optional notes."
        " The tool searches within a ±window to locate the correct action and persists the update."
    )
    args_schema = LogHabitActionArgs
    metadata = ToolMetadata(
        read_only=False,
        requires_confirmation=False,
        idempotent=False,
        labels=("habits", "write"),
        default_timeout=20.0,
    )

    async def execute(
        self,
        habit_id: UUID,
        action_date: date,
        status: str,
        notes: Optional[str] = None,
        window_days: int = 3,
    ) -> ToolResult:
        try:
            db = self._ensure_db()
            half_window = min(window_days, MAX_HABIT_ACTION_WINDOW_DAYS // 2)
            actions, _ = await habit_service.get_habit_actions(
                db=db,
                user_id=self.user_id,
                habit_id=habit_id,
                center_date=action_date,
                days_before=half_window,
                days_after=half_window,
            )
            target = next(
                (action for action in actions if action.action_date == action_date),
                None,
            )
            if target is None:
                raise HabitActionNotFoundError(
                    "No habit action found for the specified date within the search window."
                )

            before_snapshot = ensure_snapshot(target, "habit_action")

            update_data = HabitActionUpdate(status=status, notes=notes)
            action = await habit_service.update_habit_action(
                db=db,
                user_id=self.user_id,
                habit_id=habit_id,
                action_id=target.id,
                action_update=update_data,
            )

            serialized = serialize_entity(action, "habit_action")
            audit = audit_for_entity(
                "habit_actions.update",
                entity_type="habit_action",
                entity_id=getattr(action, "id", None),
                before_snapshot=before_snapshot,
                after_snapshot=serialized,
                extra={
                    "habit_id": str(habit_id),
                    "action_date": action_date.isoformat(),
                },
            )

            return create_tool_response(
                data={
                    "habit_action": serialized,
                    "searched_days": {
                        "before": half_window,
                        "after": half_window,
                    },
                },
                audit=audit,
            )
        except HabitNotFoundError as exc:
            return create_tool_error(
                "Habit not found",
                kind="not_found",
                detail=str(exc),
            )
        except HabitActionNotFoundError as exc:
            return create_tool_error(
                "Habit action not found",
                kind="not_found",
                detail=str(exc),
            )
        except InvalidOperationError as exc:
            return create_tool_error(
                "Invalid operation",
                kind="validation_error",
                detail=str(exc),
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(logger, f"Error logging habit action: {exc}", sys.exc_info())
            return create_tool_error("Failed to log habit action", detail=str(exc))


__all__ = [
    "ListHabitsTool",
    "GetHabitActionsTool",
    "CreateHabitTool",
    "UpdateHabitTool",
    "DeleteHabitTool",
    "GetHabitOverviewTool",
    "LogHabitActionTool",
]
