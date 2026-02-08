"""
Vision Pydantic schemas

This module contains all Pydantic schemas for vision-related operations.
"""

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.constants import VISION_ALLOWED_STATUSES, VISION_EXPERIENCE_RATE_MAX
from app.schemas.pagination import ListResponse, Pagination

if TYPE_CHECKING:
    from app.schemas.person import PersonSummaryResponse
    from app.schemas.task import TaskResponse


class VisionBase(BaseModel):
    """Base schema for vision data"""

    name: str = Field(..., min_length=1, max_length=200, description="Vision name")
    description: Optional[str] = Field(
        None, description="Detailed description of this vision and its significance"
    )
    dimension_id: Optional[UUID] = Field(
        None,
        description=(
            "Default dimension for this vision. Tasks and quick time entries may inherit this."
        ),
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        """Validate vision name"""
        if not v or not v.strip():
            raise ValueError("Vision name cannot be empty")
        return v.strip()


class VisionCreate(VisionBase):
    """Schema for creating a new vision"""

    person_ids: Optional[List[str]] = Field(
        None, description="List of person IDs to associate with this vision"
    )
    experience_rate_per_hour: Optional[int] = Field(
        None,
        ge=1,
        le=VISION_EXPERIENCE_RATE_MAX,
        description="Optional override for experience points gained per hour of effort",
    )


class VisionUpdate(VisionBase):
    """Schema for updating an existing vision"""

    name: Optional[str] = Field(
        None, min_length=1, max_length=200, description="Vision name"
    )
    description: Optional[str] = Field(
        None, description="Detailed description of this vision"
    )
    status: Optional[str] = Field(None, description="Vision status")
    person_ids: Optional[List[str]] = Field(
        None, description="List of person IDs to associate with this vision"
    )
    experience_rate_per_hour: Optional[int] = Field(
        None,
        ge=1,
        le=VISION_EXPERIENCE_RATE_MAX,
        description="Optional override for experience points gained per hour of effort",
    )

    # name validator inherited from VisionBase works with Optional field

    @field_validator("status")
    @classmethod
    def validate_status(cls, v):
        """Validate vision status"""
        if v is not None:
            if v not in VISION_ALLOWED_STATUSES:
                raise ValueError(
                    f"Status must be one of: {', '.join(sorted(VISION_ALLOWED_STATUSES))}"
                )
        return v


class VisionResponse(VisionBase):
    """Schema for vision responses"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(..., description="Vision UUID")
    status: str = Field(..., description="Vision status")
    stage: int = Field(..., ge=0, le=10, description="Growth stage of the tree (0-10)")
    experience_points: int = Field(
        ..., ge=0, description="Accumulated experience points"
    )
    experience_rate_per_hour: Optional[int] = Field(
        None,
        ge=1,
        le=VISION_EXPERIENCE_RATE_MAX,
        description="Vision-specific experience points gained per hour of effort",
    )
    # Aggregated total actual effort in minutes (sum of root tasks' totals); optional
    total_actual_effort: Optional[int] = Field(
        None, ge=0, description="Total actual effort for the vision in minutes"
    )
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    deleted_at: Optional[datetime] = Field(None, description="Soft delete timestamp")
    persons: List["PersonSummaryResponse"] = Field(
        default_factory=list, description="Persons associated with this vision"
    )


class VisionWithTasks(VisionResponse):
    """Schema for vision with its tasks included"""

    # Import will be handled at runtime to avoid circular imports
    tasks: List["TaskResponse"] = Field(
        default_factory=list, description="Tasks associated with this vision"
    )


class VisionPagination(Pagination):
    """Pagination metadata for vision lists."""


class VisionListMeta(BaseModel):
    """Additional list metadata for visions."""

    status_filter: Optional[str] = Field(None, description="Applied status filter")


class VisionListResponse(ListResponse[VisionResponse, VisionListMeta]):
    """Schema for vision list response."""

    items: List[VisionResponse]
    pagination: VisionPagination
    meta: VisionListMeta


class VisionExperienceUpdate(BaseModel):
    """Schema for updating vision experience points"""

    experience_points: int = Field(
        ..., ge=0, description="Experience points to add to the vision"
    )


class VisionHarvestRequest(BaseModel):
    """Schema for harvesting a vision"""

    pass  # No additional fields needed for harvest request


class VisionStatsResponse(BaseModel):
    """Schema for vision statistics"""

    total_tasks: int = Field(..., ge=0, description="Total number of tasks")
    completed_tasks: int = Field(..., ge=0, description="Number of completed tasks")
    in_progress_tasks: int = Field(..., ge=0, description="Number of in-progress tasks")
    todo_tasks: int = Field(..., ge=0, description="Number of todo tasks")
    completion_percentage: float = Field(
        ..., ge=0.0, le=1.0, description="Overall completion percentage"
    )
    total_estimated_effort: Optional[int] = Field(
        None, ge=0, description="Total estimated effort in minutes"
    )
    total_actual_effort: Optional[int] = Field(
        None, ge=0, description="Total actual effort in minutes"
    )


# Forward reference will be resolved after all schemas are loaded


class VisionSummaryResponse(BaseModel):
    """Compact vision summary for嵌入其它响应"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(..., description="Vision UUID")
    name: str = Field(..., description="Vision name")
    status: Optional[str] = Field(None, description="Vision status")
    dimension_id: Optional[UUID] = Field(
        None, description="Associated dimension UUID (if any)"
    )
    experience_rate_per_hour: Optional[int] = Field(
        None,
        ge=1,
        le=VISION_EXPERIENCE_RATE_MAX,
        description="Vision-specific experience points gained per hour of effort",
    )


class VisionExperienceRateUpdateItem(BaseModel):
    """Item payload for bulk updating vision experience rates"""

    id: UUID = Field(..., description="Vision UUID to update")
    experience_rate_per_hour: Optional[int] = Field(
        None,
        ge=1,
        le=VISION_EXPERIENCE_RATE_MAX,
        description=(
            "Optional override for experience points gained per hour of effort. "
            "Set to null to fall back to the user's default preference."
        ),
    )


class VisionExperienceRateBulkUpdateRequest(BaseModel):
    """Request payload for bulk updating vision experience rates"""

    items: List[VisionExperienceRateUpdateItem] = Field(
        ..., description="List of vision rate updates to apply"
    )


class VisionExperienceRateBulkUpdateResponse(BaseModel):
    """Response payload after bulk updating vision experience rates"""

    items: List[VisionResponse] = Field(
        default_factory=list, description="Updated vision records"
    )
