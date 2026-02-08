"""
Pydantic schemas for Habit models
"""

from datetime import date
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.constants import get_habit_action_allowed_statuses
from app.schemas.pagination import ListResponse, Pagination


class HabitBase(BaseModel):
    """Base schema for habit data"""

    title: str = Field(..., max_length=200, description="Habit title")
    description: Optional[str] = Field(None, description="Habit description")
    start_date: date = Field(..., description="Start date of the habit")
    duration_days: int = Field(..., description="Duration in days")
    task_id: Optional[UUID] = Field(None, description="ID of the associated task")


class HabitCreate(HabitBase):
    """Schema for creating a new habit"""


class HabitUpdate(BaseModel):
    """Schema for updating a habit"""

    title: Optional[str] = Field(None, max_length=200, description="Habit title")
    description: Optional[str] = Field(None, description="Habit description")
    start_date: Optional[date] = Field(None, description="Start date of the habit")
    duration_days: Optional[int] = Field(None, description="Duration in days")
    status: Optional[str] = Field(None, description="Habit status")
    task_id: Optional[UUID] = Field(None, description="ID of the associated task")


class HabitResponse(HabitBase):
    """Schema for habit response"""

    id: UUID
    status: str
    created_at: str = Field(..., description="Creation timestamp")
    updated_at: str = Field(..., description="Last update timestamp")
    deleted_at: Optional[str] = Field(None, description="Deletion timestamp")

    model_config = ConfigDict(from_attributes=True)

    @field_validator("created_at", "updated_at", "deleted_at", mode="before")
    @classmethod
    def convert_datetime_to_iso(cls, v):
        """Convert datetime objects to ISO format strings"""
        if v is not None and hasattr(v, "isoformat"):
            return v.isoformat()
        return v


class HabitWithActions(HabitResponse):
    """Schema for habit with its actions"""

    actions: List["HabitActionResponse"] = []

    model_config = ConfigDict(from_attributes=True)


class HabitActionBase(BaseModel):
    """Base schema for habit action data"""

    action_date: date = Field(..., description="Action date")
    status: str = Field(..., description="Action status")
    notes: Optional[str] = Field(None, description="Action notes")


class HabitActionCreate(HabitActionBase):
    """Schema for creating a habit action (system use only)"""

    habit_id: UUID = Field(..., description="Habit ID")


class HabitActionUpdate(BaseModel):
    """Schema for updating a habit action"""

    status: Optional[str] = Field(None, description="Action status")
    notes: Optional[str] = Field(None, description="Action notes")

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            allowed_statuses = get_habit_action_allowed_statuses()
            if value not in allowed_statuses:
                raise ValueError(f"Invalid status. Allowed values: {allowed_statuses}")
        return value


class HabitActionResponse(HabitActionBase):
    """Schema for habit action response"""

    id: UUID
    habit_id: UUID
    created_at: str = Field(..., description="Creation timestamp")
    updated_at: str = Field(..., description="Last update timestamp")
    deleted_at: Optional[str] = Field(None, description="Deletion timestamp")

    model_config = ConfigDict(from_attributes=True)

    @field_validator("created_at", "updated_at", "deleted_at", mode="before")
    @classmethod
    def convert_datetime_to_iso(cls, v):
        """Convert datetime objects to ISO format strings"""
        if v is not None and hasattr(v, "isoformat"):
            return v.isoformat()
        return v


class HabitActionWithHabit(HabitActionResponse):
    """Schema for habit action with habit info"""

    habit: HabitResponse

    model_config = ConfigDict(from_attributes=True)


class HabitStatsResponse(BaseModel):
    """Schema for habit statistics"""

    habit_id: UUID
    total_actions: int
    completed_actions: int
    missed_actions: int
    skipped_actions: int
    progress_percentage: float
    current_streak: int
    longest_streak: int


class HabitOverviewResponse(BaseModel):
    """Schema combining habit detail with statistics"""

    habit: HabitResponse
    stats: HabitStatsResponse


class HabitPagination(Pagination):
    """Pagination metadata for habit lists."""


class HabitListMeta(BaseModel):
    """Additional list metadata for habits and overviews."""

    status_filter: Optional[str] = None


class HabitActionListMeta(BaseModel):
    """Additional list metadata for habit actions."""

    status_filter: Optional[str] = None
    center_date: Optional[date] = None
    days_before: Optional[int] = None
    days_after: Optional[int] = None


class HabitActionByDateListMeta(BaseModel):
    """Additional list metadata for habit actions by date."""

    action_date: Optional[date] = None


class HabitOverviewListResponse(ListResponse[HabitOverviewResponse, HabitListMeta]):
    """Schema for list of habit overviews"""

    items: List[HabitOverviewResponse]
    pagination: HabitPagination
    meta: HabitListMeta


class HabitListResponse(ListResponse[HabitResponse, HabitListMeta]):
    """Schema for habit list response"""

    items: List[HabitResponse]
    pagination: HabitPagination
    meta: HabitListMeta


class HabitActionListResponse(ListResponse[HabitActionResponse, HabitActionListMeta]):
    """Schema for habit action list response"""

    items: List[HabitActionResponse]
    pagination: HabitPagination
    meta: HabitActionListMeta


class HabitActionWithHabitListResponse(
    ListResponse[HabitActionWithHabit, HabitActionByDateListMeta]
):
    """Schema for habit action list response including habit details."""

    items: List[HabitActionWithHabit]
    pagination: HabitPagination
    meta: HabitActionByDateListMeta


class HabitTaskAssociationsResponse(BaseModel):
    """Schema for all habit-task associations response"""

    associations: dict[UUID, List[HabitResponse]] = Field(
        ..., description="Dictionary mapping task_id to habit list"
    )


# Update forward references
HabitWithActions.model_rebuild()
HabitActionWithHabit.model_rebuild()
