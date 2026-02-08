"""
Planned Event Pydantic schemas for data validation

These schemas define the data structure for API requests and responses for planned events.
"""

from datetime import datetime

# Forward reference for PersonSummaryResponse
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.constants import PLANNED_EVENT_ALLOWED_STATUSES
from app.schemas.pagination import ListResponse, Pagination

if TYPE_CHECKING:
    from app.schemas.person import PersonSummaryResponse


class PlannedEventBase(BaseModel):
    """Base schema for planned event with common fields"""

    title: str = Field(..., min_length=1, max_length=200, description="Event title")
    start_time: datetime = Field(..., description="Planned start time")
    end_time: Optional[datetime] = Field(None, description="Planned end time")
    priority: int = Field(0, ge=0, le=5, description="Priority level (0-5)")
    dimension_id: Optional[UUID] = Field(
        None, description="UUID of the life dimension this event belongs to"
    )
    task_id: Optional[UUID] = Field(
        None, description="Optional UUID of the task this event is planned to work on"
    )
    is_all_day: bool = Field(False, description="Whether this is an all-day event")
    is_recurring: bool = Field(False, description="Whether this event recurs")
    recurrence_pattern: Optional[Dict[str, Any]] = Field(
        None, description="Recurrence pattern details"
    )
    rrule_string: Optional[str] = Field(
        None, description="RRULE string for recurring events (RFC 5545)"
    )
    status: str = Field("planned", description="Event status")
    tags: Optional[List[str]] = Field(None, description="Event tags")
    extra_data: Optional[Dict[str, Any]] = Field(
        None, description="Additional metadata"
    )


class PlannedEventCreate(PlannedEventBase):
    """Schema for creating a new planned event"""

    person_ids: Optional[List[str]] = Field(
        None, description="List of person UUIDs to associate with this event"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "title": "Morning Workout",
                "start_time": "2024-01-15T07:00:00Z",
                "end_time": "2024-01-15T07:30:00Z",
                "priority": 3,
                "dimension_id": 1,
                "task_id": 5,
                "is_all_day": False,
                "is_recurring": True,
                "rrule_string": "FREQ=DAILY;INTERVAL=1;COUNT=30",
                "tags": ["health", "morning"],
                "extra_data": {"location": "home_gym"},
            }
        }
    )


class PlannedEventUpdate(BaseModel):
    """Schema for updating an existing planned event"""

    title: Optional[str] = Field(None, min_length=1, max_length=200)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    priority: Optional[int] = Field(None, ge=0, le=5)
    dimension_id: Optional[UUID] = Field(
        None, description="UUID of the life dimension this event belongs to"
    )
    task_id: Optional[UUID] = Field(
        None, description="Optional UUID of the task this event is planned to work on"
    )
    is_all_day: Optional[bool] = None
    is_recurring: Optional[bool] = None
    recurrence_pattern: Optional[Dict[str, Any]] = None
    rrule_string: Optional[str] = None
    status: Optional[str] = None
    tags: Optional[List[str]] = None
    extra_data: Optional[Dict[str, Any]] = None
    person_ids: Optional[List[str]] = Field(
        None, description="List of person UUIDs to associate with this event"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "title": "Updated Morning Workout",
                "priority": 4,
                "task_id": 7,
                "tags": ["health", "morning", "updated"],
            }
        }
    )

    @field_validator("status")
    @classmethod
    def validate_status(cls, v):
        if v is not None and v not in PLANNED_EVENT_ALLOWED_STATUSES:
            raise ValueError(
                f"Status must be one of: {', '.join(sorted(PLANNED_EVENT_ALLOWED_STATUSES))}"
            )
        return v


class PlannedEventResponse(PlannedEventBase):
    """Schema for planned event API responses"""

    id: UUID = Field(..., description="Unique event identifier (UUID)")
    created_at: datetime = Field(..., description="Record creation time")
    updated_at: datetime = Field(..., description="Record last update time")
    persons: List["PersonSummaryResponse"] = Field(
        default=[], description="Associated persons"
    )

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": 1,
                "title": "Morning Workout",
                "start_time": "2024-01-15T07:00:00Z",
                "end_time": "2024-01-15T07:30:00Z",
                "priority": 3,
                "dimension_id": 1,
                "task_id": 5,
                "is_all_day": False,
                "is_recurring": True,
                "rrule_string": "FREQ=DAILY;INTERVAL=1;COUNT=30",
                "status": "planned",
                "tags": ["health", "morning"],
                "created_at": "2024-01-14T20:00:00Z",
                "updated_at": "2024-01-14T20:00:00Z",
            }
        },
    )


class PlannedEventPagination(Pagination):
    """Pagination metadata for planned event lists."""


class PlannedEventListMeta(BaseModel):
    """Additional list metadata for planned event listings."""

    start: Optional[datetime] = Field(
        None, description="Start of time range (range query only)"
    )
    end: Optional[datetime] = Field(
        None, description="End of time range (range query only)"
    )
    status: Optional[str] = Field(None, description="Applied status filter")
    task_id: Optional[UUID] = Field(None, description="Applied task filter")


class PlannedEventListResponse(
    ListResponse[PlannedEventResponse, PlannedEventListMeta]
):
    """Schema for planned event list response."""

    items: List[PlannedEventResponse]
    pagination: PlannedEventPagination
    meta: PlannedEventListMeta


class PlannedEventRangeListResponse(ListResponse[Dict[str, Any], PlannedEventListMeta]):
    """Schema for planned event range list response with expanded instances."""

    items: List[Dict[str, Any]]
    pagination: PlannedEventPagination
    meta: PlannedEventListMeta
