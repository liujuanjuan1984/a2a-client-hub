"""Timelog-related tools exposed to the agent layer."""

import sys
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tools.arg_utils import normalize_uuid_list, parse_uuid_list_argument
from app.agents.tools.audit_utils import audit_for_entity, ensure_snapshot
from app.agents.tools.base import AbstractTool, ToolMetadata
from app.agents.tools.responses import (
    ToolResult,
    create_tool_error,
    create_tool_response,
    serialize_entity,
)
from app.core.logging import get_logger, log_exception
from app.db.models.actual_event import ActualEvent
from app.handlers import actual_events as actual_event_service
from app.schemas.actual_event import ActualEventCreate, ActualEventUpdate
from app.utils.timezone_util import utc_now

logger = get_logger(__name__)


def _ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def _load_time_log_for_audit(
    db: AsyncSession, user_id: UUID, event_id: UUID
) -> Optional[ActualEvent]:
    stmt = (
        select(ActualEvent)
        .where(
            ActualEvent.id == event_id,
            ActualEvent.user_id == user_id,
            ActualEvent.deleted_at.is_(None),
        )
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


class ListTimeLogsArgs(BaseModel):
    """Arguments for retrieving timelog entries."""

    start: Optional[datetime] = Field(
        None,
        description="Start datetime (inclusive). Defaults to now minus seven days.",
    )
    end: Optional[datetime] = Field(
        None,
        description="End datetime (inclusive). Defaults to current time.",
    )
    page: int = Field(1, ge=1, description="Page number (1-indexed).")
    size: int = Field(
        20,
        ge=1,
        le=200,
        description="Page size / number of timelog entries to return (1-200).",
    )
    tracking_method: Optional[str] = Field(
        None,
        description="Filter by tracking method (manual, automatic, imported).",
    )


class ListTimeLogsTool(AbstractTool):
    """Tool for retrieving timelog entries within a time window."""

    name = "list_time_logs"
    description = (
        "Retrieve recent time log entries for the current user."
        " Defaults to the last seven days when no interval is provided."
    )
    args_schema = ListTimeLogsArgs
    metadata = ToolMetadata(
        read_only=True,
        labels=("timelog", "read"),
        default_timeout=20.0,
    )

    async def execute(
        self,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        page: int = 1,
        size: int = 20,
        tracking_method: Optional[str] = None,
    ) -> ToolResult:
        try:
            db = self._ensure_db()
            now = utc_now()
            start_dt = _ensure_aware(start) if start else now - timedelta(days=7)
            end_dt = _ensure_aware(end) if end else now

            if start_dt > end_dt:
                return create_tool_error(
                    "Invalid time range",
                    kind="validation_error",
                    detail="Start datetime must be before end datetime.",
                )

            offset = (page - 1) * size
            events, total = await actual_event_service.list_actual_events_paginated(
                db=db,
                user_id=self.user_id,
                skip=offset,
                limit=size,
                start_date=start_dt,
                end_date=end_dt,
                tracking_method=tracking_method,
            )

            serialized_events = [
                serialize_entity(event, "actual_event")
                for event, persons, task in events
            ]

            pages = (total + size - 1) // size if size else 0
            return create_tool_response(
                data={
                    "items": serialized_events,
                    "pagination": {
                        "page": page,
                        "size": size,
                        "total": total,
                        "pages": pages,
                    },
                    "meta": {
                        "start_date": start_dt.isoformat(),
                        "end_date": end_dt.isoformat(),
                        "tracking_method": tracking_method,
                        "returned_count": len(serialized_events),
                        "total_count": total,
                        "truncated": False,
                    },
                }
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(logger, f"Error retrieving time logs: {exc}", sys.exc_info())
            return create_tool_error("Failed to retrieve time logs", detail=str(exc))


class CreateTimeLogArgs(BaseModel):
    """Arguments for creating a time log entry."""

    title: str = Field(
        ..., min_length=1, max_length=200, description="Actual activity title"
    )
    start_time: datetime = Field(..., description="Actual start time")
    end_time: datetime = Field(..., description="Actual end time")
    dimension_id: Optional[UUID] = Field(
        None, description="ID of the life dimension this activity belongs to"
    )
    tracking_method: str = Field(
        "manual",
        description="How this was tracked (manual, automatic, imported).",
    )
    location: Optional[str] = Field(
        None, max_length=200, description="Where this activity took place"
    )
    energy_level: Optional[int] = Field(
        None, ge=1, le=5, description="Energy level during activity (1-5)"
    )
    notes: Optional[str] = Field(None, description="Personal notes and reflections")
    tags: Optional[list[str]] = Field(None, description="Activity tags")
    task_id: Optional[UUID] = Field(
        None, description="Associated task ID (many ActualEvents to one Task)"
    )
    person_ids: Optional[list[UUID]] = Field(
        None, description="List of person IDs to associate with this activity"
    )

    @field_validator("person_ids", mode="before")
    @classmethod
    def _coerce_person_ids(cls, value):
        return parse_uuid_list_argument(value, field_name="person_ids")


class CreateTimeLogTool(AbstractTool):
    """Tool for creating a new time log entry."""

    name = "create_time_log"
    description = (
        "Create a new time log entry (ActualEvent) for the current user and persist it."
        " Use this tool when the user records a new activity duration."
    )
    args_schema = CreateTimeLogArgs
    metadata = ToolMetadata(
        read_only=False,
        requires_confirmation=False,
        idempotent=False,
        labels=("timelog", "write"),
        default_timeout=30.0,
    )

    async def execute(
        self,
        title: str,
        start_time: datetime,
        end_time: datetime,
        dimension_id: Optional[UUID] = None,
        tracking_method: str = "manual",
        location: Optional[str] = None,
        energy_level: Optional[int] = None,
        notes: Optional[str] = None,
        tags: Optional[list[str]] = None,
        task_id: Optional[UUID] = None,
        person_ids: Optional[list[UUID]] = None,
    ) -> ToolResult:
        try:
            db = self._ensure_db()
            # Ensure timezone awareness
            start_time = _ensure_aware(start_time)
            end_time = _ensure_aware(end_time)
            normalized_person_ids = normalize_uuid_list(person_ids)

            event_data = ActualEventCreate(
                title=title,
                start_time=start_time,
                end_time=end_time,
                dimension_id=dimension_id,
                tracking_method=tracking_method,
                location=location,
                energy_level=energy_level,
                notes=notes,
                tags=tags,
                task_id=task_id,
                person_ids=normalized_person_ids,
            )
            event, _ = await actual_event_service.create_actual_event(
                db=db, user_id=self.user_id, event_in=event_data
            )
            serialized = serialize_entity(event, "actual_event")
            audit = audit_for_entity(
                "timelog.create",
                entity_type="actual_event",
                entity_id=getattr(event, "id", None),
                after_snapshot=serialized,
            )
            return create_tool_response(
                data={"time_log": serialized},
                audit=audit,
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(logger, f"Error creating time log: {exc}", sys.exc_info())
            return create_tool_error("Failed to create time log", detail=str(exc))


class UpdateTimeLogArgs(BaseModel):
    """
    Arguments for updating a time log entry.

    Omit optional fields to keep their current values. Set nullable fields (dimension,
    location, energy_level, notes, tags, task_id, person_ids) to null/[] to clear them.
    """

    event_id: UUID = Field(..., description="Time log event identifier to update.")
    title: Optional[str] = Field(
        None,
        min_length=1,
        max_length=200,
        description="Updated activity title; omit to keep it (cannot be null).",
    )
    start_time: Optional[datetime] = Field(
        None,
        description="Updated start time; omit to keep current timestamp (cannot be null).",
    )
    end_time: Optional[datetime] = Field(
        None,
        description="Updated end time; omit to keep current timestamp (cannot be null).",
    )
    dimension_id: Optional[UUID] = Field(
        None,
        description="Updated life dimension; omit to keep it or set null to remove the link.",
    )
    tracking_method: Optional[str] = Field(
        None,
        description="Updated tracking method; omit to keep current value (cannot be null).",
    )
    location: Optional[str] = Field(
        None,
        max_length=200,
        description="Updated location; omit to keep it or set null to clear the stored value.",
    )
    energy_level: Optional[int] = Field(
        None,
        ge=1,
        le=5,
        description="Updated energy level; omit to keep it or set null to remove it.",
    )
    notes: Optional[str] = Field(
        None,
        description="Updated notes; omit to keep them or set null to erase existing notes.",
    )
    tags: Optional[list[str]] = Field(
        None,
        description="Updated tags list; omit to keep, pass an empty list or null to clear.",
    )
    task_id: Optional[UUID] = Field(
        None,
        description="Updated associated task ID; omit to keep it or set null to unlink.",
    )
    person_ids: Optional[list[UUID]] = Field(
        None,
        description="Updated person IDs; omit to keep, or pass null/[] to remove all associations.",
    )

    @field_validator("person_ids", mode="before")
    @classmethod
    def _coerce_person_ids(cls, value):
        return parse_uuid_list_argument(value, field_name="person_ids")


class UpdateTimeLogTool(AbstractTool):
    """Tool for updating an existing time log entry."""

    name = "update_time_log"
    description = (
        "Partially update an existing time log entry. Omit properties to keep them "
        "unchanged; set nullable ones to null (or empty lists) to clear stored values."
    )
    args_schema = UpdateTimeLogArgs
    metadata = ToolMetadata(
        read_only=False,
        requires_confirmation=False,
        idempotent=False,
        labels=("timelog", "write"),
        default_timeout=30.0,
    )

    async def execute(
        self,
        event_id: UUID,
        title: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        dimension_id: Optional[UUID] = None,
        tracking_method: Optional[str] = None,
        location: Optional[str] = None,
        energy_level: Optional[int] = None,
        notes: Optional[str] = None,
        tags: Optional[list[str]] = None,
        task_id: Optional[UUID] = None,
        person_ids: Optional[list[UUID]] = None,
    ) -> ToolResult:
        try:
            db = self._ensure_db()
            # Ensure timezone awareness for datetime fields
            if start_time:
                start_time = _ensure_aware(start_time)
            if end_time:
                end_time = _ensure_aware(end_time)

            existing = await _load_time_log_for_audit(db, self.user_id, event_id)
            if existing is None:
                return create_tool_error(
                    "Time log not found",
                    kind="not_found",
                    detail="Time log entry not found",
                )
            before_snapshot = ensure_snapshot(existing, "actual_event")

            update_data = ActualEventUpdate(
                title=title,
                start_time=start_time,
                end_time=end_time,
                dimension_id=dimension_id,
                tracking_method=tracking_method,
                location=location,
                energy_level=energy_level,
                notes=notes,
                tags=tags,
                task_id=task_id,
                person_ids=normalize_uuid_list(person_ids),
            )
            event, _, _ = await actual_event_service.update_actual_event(
                db=db,
                user_id=self.user_id,
                event_id=event_id,
                update_in=update_data,
            )
            serialized = serialize_entity(event, "actual_event")
            audit = audit_for_entity(
                "timelog.update",
                entity_type="actual_event",
                entity_id=event_id,
                before_snapshot=before_snapshot,
                after_snapshot=serialized,
            )
            return create_tool_response(
                data={"time_log": serialized},
                audit=audit,
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(logger, f"Error updating time log: {exc}", sys.exc_info())
            return create_tool_error("Failed to update time log", detail=str(exc))


class DeleteTimeLogArgs(BaseModel):
    """Arguments for deleting a time log entry."""

    event_id: UUID = Field(..., description="Time log event identifier to delete.")


class DeleteTimeLogTool(AbstractTool):
    """Tool for deleting a time log entry."""

    name = "delete_time_log"
    description = "Delete a time log entry."
    args_schema = DeleteTimeLogArgs
    metadata = ToolMetadata(
        read_only=False,
        requires_confirmation=False,
        idempotent=False,
        labels=("timelog", "write"),
        default_timeout=20.0,
    )

    async def execute(self, event_id: UUID) -> ToolResult:
        try:
            db = self._ensure_db()
            existing = await _load_time_log_for_audit(db, self.user_id, event_id)
            if existing is None:
                return create_tool_error(
                    "Time log not found",
                    kind="not_found",
                    detail="Time log entry not found",
                )
            before_snapshot = ensure_snapshot(existing, "actual_event")

            await actual_event_service.delete_actual_event(
                db=db,
                user_id=self.user_id,
                event_id=event_id,
                hard_delete=False,
            )
            audit = audit_for_entity(
                "timelog.delete",
                entity_type="actual_event",
                entity_id=event_id,
                before_snapshot=before_snapshot,
                extra={"hard_delete": False},
            )
            return create_tool_response(
                data={
                    "message": f"Time log {event_id} successfully deleted",
                    "event_id": event_id,
                },
                audit=audit,
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(logger, f"Error deleting time log: {exc}", sys.exc_info())
            return create_tool_error("Failed to delete time log", detail=str(exc))


__all__ = [
    "ListTimeLogsTool",
    "CreateTimeLogTool",
    "UpdateTimeLogTool",
    "DeleteTimeLogTool",
]
