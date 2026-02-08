"""
Actual Event Pydantic schemas for data validation

These schemas define the data structure for API requests and responses for actual events.
"""

from datetime import datetime

# Forward reference for PersonSummaryResponse
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.dimension import DimensionSummaryResponse
from app.schemas.note import NoteSummary
from app.schemas.pagination import ListResponse, Pagination
from app.schemas.vision import VisionSummaryResponse

if TYPE_CHECKING:
    from app.schemas.person import PersonSummaryResponse


class ActualEventBase(BaseModel):
    """Base schema for actual event with common fields"""

    title: str = Field(
        ..., min_length=1, max_length=200, description="Actual activity title"
    )
    start_time: datetime = Field(..., description="Actual start time")
    end_time: datetime = Field(..., description="Actual end time")

    dimension_id: Optional[UUID] = Field(
        None, description="ID of the life dimension this activity belongs to"
    )
    tracking_method: str = Field("manual", description="How this was tracked")
    location: Optional[str] = Field(
        None, max_length=200, description="Where this activity took place"
    )
    energy_level: Optional[int] = Field(
        None, ge=1, le=5, description="Energy level during activity (1-5)"
    )
    notes: Optional[str] = Field(None, description="Personal notes and reflections")
    tags: Optional[List[str]] = Field(None, description="Activity tags")
    extra_data: Optional[Dict[str, Any]] = Field(
        None, description="Additional metadata"
    )
    # v0.9: Single task association for timelog entries (preferred)
    task_id: Optional[UUID] = Field(
        None, description="Associated task ID (many ActualEvents to one Task)"
    )
    # Legacy v0.7: Many-to-many task completion support (deprecated input, kept for compatibility)
    completed_task_ids: Optional[List[str]] = Field(
        None,
        description="[Deprecated] List of task IDs completed during this activity (length must be 0 or 1)",
    )


class ActualEventCreate(ActualEventBase):
    """Schema for creating a new actual event"""

    person_ids: Optional[List[str]] = Field(
        None, description="List of person IDs to associate with this activity"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "title": "Morning Workout Completed",
                "start_time": "2024-01-15T07:05:00Z",
                "end_time": "2024-01-15T07:30:00Z",
                "location": "Home gym",
                "energy_level": 4,
                "notes": "Good session, slightly late start but maintained intensity",
                "tags": ["health", "morning", "completed"],
            }
        }
    )


class ActualEventUpdate(BaseModel):
    """Schema for updating an existing actual event"""

    title: Optional[str] = Field(None, min_length=1, max_length=200)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    dimension_id: Optional[UUID] = Field(
        None, description="ID of the life dimension this activity belongs to"
    )
    tracking_method: Optional[str] = None
    location: Optional[str] = Field(None, max_length=200)
    energy_level: Optional[int] = Field(None, ge=1, le=5)
    notes: Optional[str] = None
    tags: Optional[List[str]] = None
    extra_data: Optional[Dict[str, Any]] = None
    # v0.9: Single task association for timelog entries (preferred)
    task_id: Optional[UUID] = Field(
        None, description="Associated task ID (many ActualEvents to one Task)"
    )
    # Legacy v0.7: Many-to-many task completion support (deprecated input, kept for compatibility)
    completed_task_ids: Optional[List[str]] = Field(
        None,
        description="[Deprecated] List of task IDs completed during this activity (length must be 0 or 1)",
    )
    person_ids: Optional[List[str]] = Field(
        None, description="List of person IDs to associate with this activity"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "energy_level": 5,
                "notes": "Updated reflection: This was an excellent session!",
            }
        }
    )


class ActualEventTaskSummary(BaseModel):
    """Embedded task summary returned alongside实际事件"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(..., description="Associated task ID")
    content: str = Field(..., description="Task title/content")
    vision_id: Optional[UUID] = Field(
        None, description="Vision UUID the task belongs to"
    )
    status: Optional[str] = Field(None, description="Task status")
    vision_summary: Optional[VisionSummaryResponse] = Field(
        None, description="Embedded vision summary for quick display"
    )


class ActualEventResponse(ActualEventBase):
    """Schema for actual event API responses"""

    id: UUID = Field(..., description="Unique event identifier")
    created_at: datetime = Field(..., description="Record creation time")
    updated_at: datetime = Field(..., description="Record last update time")
    persons: List["PersonSummaryResponse"] = Field(
        default=[], description="Associated persons"
    )
    # Preferred read model: single associated task summary
    task: Optional[ActualEventTaskSummary] = Field(
        None,
        description="Summary of the associated task (id, content, vision info, status)",
    )
    dimension_summary: Optional[DimensionSummaryResponse] = Field(
        None,
        description="Optional dimension summary (id/name/color) for quick UI usage",
    )
    linked_notes: List[NoteSummary] = Field(
        default_factory=list,
        description="Notes linked to this actual event (timelog)",
    )
    linked_notes_count: int = Field(
        0, description="Number of notes linked to this actual event"
    )
    # completed_tasks removed in v0.9

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": 1,
                "title": "Morning Workout Completed",
                "start_time": "2024-01-15T07:05:00Z",
                "end_time": "2024-01-15T07:30:00Z",
                "tracking_method": "manual",
                "location": "Home gym",
                "energy_level": 4,
                "notes": "Good session, slightly late start but maintained intensity",
                "tags": ["health", "morning", "completed"],
                "created_at": "2024-01-15T07:35:00Z",
                "updated_at": "2024-01-15T07:35:00Z",
            }
        },
    )


# v0.7: Energy injection response schema
class EnergyInjectionResult(BaseModel):
    """Result of energy injection from completed tasks"""

    vision_id: UUID = Field(..., description="Vision that received energy")
    experience_gained: int = Field(..., description="Experience points gained")
    stage_evolved: bool = Field(
        ..., description="Whether the vision evolved to next stage"
    )
    new_stage: int = Field(..., description="Current stage after energy injection")
    total_experience: int = Field(..., description="Total experience points")


class ActualEventWithEnergyResponse(ActualEventResponse):
    """Schema for actual event response with energy injection results"""

    energy_injections: Optional[List[EnergyInjectionResult]] = Field(
        None, description="Results of energy injection into visions"
    )


class ActualEventBatchCreateRequest(BaseModel):
    """Schema for batch creating actual events"""

    events: List[ActualEventCreate] = Field(
        ...,
        min_length=1,
        max_length=500,
        description="List of actual events to create (max 500 at once)",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "events": [
                    {
                        "title": "Meeting with team",
                        "start_time": "2024-01-15T09:00:00Z",
                        "end_time": "2024-01-15T10:00:00Z",
                        "dimension_id": 1,
                    },
                    {
                        "title": "Code review",
                        "start_time": "2024-01-15T10:00:00Z",
                        "end_time": "2024-01-15T11:00:00Z",
                        "dimension_id": 2,
                    },
                ]
            }
        }
    )


class ActualEventBatchCreateResponse(BaseModel):
    """Schema for batch create response"""

    created_count: int = Field(..., description="Number of events successfully created")
    failed_count: int = Field(..., description="Number of events that failed to create")
    created_events: List[ActualEventResponse] = Field(
        default_factory=list, description="List of successfully created events"
    )
    errors: List[str] = Field(
        default_factory=list, description="List of error messages for failed creations"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "created_count": 2,
                "failed_count": 0,
                "created_events": [],
                "errors": [],
            }
        }
    )


class ActualEventBatchDeleteRequest(BaseModel):
    """Schema for batch deleting actual events"""

    event_ids: List[str] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="List of actual event IDs to delete (max 100 at once)",
    )

    model_config = ConfigDict(
        json_schema_extra={"example": {"event_ids": [1, 2, 3, 4, 5]}}
    )


class ActualEventBatchDeleteResponse(BaseModel):
    """Schema for batch delete response"""

    deleted_count: int = Field(..., description="Number of events successfully deleted")
    failed_ids: List[str] = Field(
        default=[], description="List of event IDs that failed to delete"
    )
    errors: List[str] = Field(
        default=[], description="List of error messages for failed deletions"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "deleted_count": 4,
                "failed_ids": [5],
                "errors": ["Event with ID 5 not found"],
            }
        }
    )


class ActualEventAdvancedSearchRequest(BaseModel):
    """Schema for advanced search request"""

    start_date: datetime = Field(..., description="Start date for search (required)")
    end_date: Optional[datetime] = Field(
        None, description="End date for search (optional, defaults to start_date)"
    )
    dimension_name: Optional[str] = Field(
        None, description="Dimension name for exact text match (optional)"
    )
    description_keyword: Optional[str] = Field(
        None, description="Keyword to search in title and notes (optional)"
    )
    task_id: Optional[UUID] = Field(
        None,
        description="Specific task ID for filtering (UUID)",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "start_date": "2024-01-01T00:00:00Z",
                "end_date": "2024-01-31T23:59:59Z",
                "dimension_name": "3-家庭",
                "description_keyword": "会议",
                "task_id": 1,
            }
        }
    )


class ActualEventPagination(Pagination):
    """Pagination metadata for actual event lists."""


class ActualEventListMeta(BaseModel):
    """Additional list metadata for actual event queries."""

    start_date: Optional[datetime] = Field(
        None, description="Start datetime filter (if applied)"
    )
    end_date: Optional[datetime] = Field(
        None, description="End datetime filter (if applied)"
    )
    tracking_method: Optional[str] = Field(
        None, description="Tracking method filter (if applied)"
    )
    dimension_name: Optional[str] = Field(
        None, description="Dimension name filter (advanced search only)"
    )
    description_keyword: Optional[str] = Field(
        None, description="Description keyword filter (advanced search only)"
    )
    task_id: Optional[UUID] = Field(
        None, description="Task filter (advanced search only)"
    )
    limit: Optional[int] = Field(
        None, description="Requested maximum number of records (advanced search)"
    )
    returned_count: Optional[int] = Field(
        None, description="Number of records actually returned"
    )
    total_count: Optional[int] = Field(
        None, description="Total number of records matching the query"
    )
    truncated: Optional[bool] = Field(
        None, description="Whether the result set was truncated"
    )


class ActualEventListResponse(ListResponse[ActualEventResponse, ActualEventListMeta]):
    """Standard list payload for actual event results."""

    items: List[ActualEventResponse]
    pagination: ActualEventPagination
    meta: ActualEventListMeta


class ActualEventSearchResponse(ActualEventListResponse):
    """Advanced search payload including pagination."""


class ActualEventBatchUpdateRequest(BaseModel):
    """Schema for batch updating actual events"""

    event_ids: List[str] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="List of actual event IDs to update (max 100 at once)",
    )
    update_type: str = Field(
        ..., description="Type of update: 'persons', 'title', 'task', or 'dimension'"
    )
    persons: Optional[Dict[str, Any]] = Field(
        None, description="Person update configuration"
    )
    title: Optional[Dict[str, Any]] = Field(
        None, description="Title update configuration"
    )
    task: Optional[Dict[str, Any]] = Field(
        None, description="Task update configuration"
    )
    dimension: Optional[Dict[str, Any]] = Field(
        None, description="Dimension update configuration"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "event_ids": [1, 2, 3],
                "update_type": "persons",
                "persons": {"mode": "replace", "person_ids": [1, 2]},
            }
        }
    )


class ActualEventBatchUpdateResponse(BaseModel):
    """Schema for batch update response"""

    updated_count: int = Field(..., description="Number of events successfully updated")
    failed_ids: List[str] = Field(
        default=[], description="List of event IDs that failed to update"
    )
    errors: List[str] = Field(
        default=[], description="List of error messages for failed updates"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "updated_count": 3,
                "failed_ids": [],
                "errors": [],
            }
        }
    )
