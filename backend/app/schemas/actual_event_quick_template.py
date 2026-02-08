"""Pydantic schemas for actual event quick templates."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.pagination import ListResponse, Pagination
from app.schemas.person import PersonSummaryResponse

_MINUTES_PER_DAY = 24 * 60


class ActualEventQuickTemplateBase(BaseModel):
    """Shared fields between create and update operations."""

    title: Optional[str] = Field(
        None,
        min_length=1,
        max_length=200,
        description="Display title for the template",
    )
    dimension_id: Optional[UUID] = Field(
        None, description="Associated life dimension identifier"
    )
    person_ids: Optional[List[UUID]] = Field(
        None, description="Optional list of related person identifiers"
    )
    default_duration_minutes: Optional[int] = Field(
        None,
        ge=1,
        le=_MINUTES_PER_DAY,
        description="Optional default duration in minutes (1-1440)",
    )
    position: Optional[int] = Field(
        None,
        ge=0,
        description="Manual ordering index; null lets the server append",
    )
    usage_count: Optional[int] = Field(
        None, ge=0, description="Usage counter for migration scenarios"
    )
    last_used_at: Optional[datetime] = Field(
        None, description="Timestamp of the most recent usage"
    )

    @field_validator("title")
    @classmethod
    def _strip_title(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("Title cannot be blank")
        return stripped


class ActualEventQuickTemplateCreate(ActualEventQuickTemplateBase):
    """Schema for creating a new quick template."""

    title: str = Field(..., min_length=1, max_length=200, description="Template title")


class ActualEventQuickTemplateUpdate(ActualEventQuickTemplateBase):
    """Schema for updating an existing quick template."""


class ActualEventQuickTemplateResponse(BaseModel):
    """Serialized quick template returned to clients."""

    id: UUID = Field(..., description="Template identifier")
    user_id: UUID = Field(..., description="Owner identifier")
    title: str = Field(..., description="Display title")
    dimension_id: Optional[UUID] = Field(None, description="Dimension identifier")
    dimension_name: Optional[str] = Field(
        None, description="Dimension display name for convenience"
    )
    dimension_color: Optional[str] = Field(
        None, description="Dimension color hex used for chips"
    )
    person_ids: List[UUID] = Field(
        default_factory=list, description="Related person identifiers"
    )
    persons: List[PersonSummaryResponse] = Field(
        default_factory=list, description="Related person summaries"
    )
    default_duration_minutes: Optional[int] = Field(
        None, description="Default duration in minutes"
    )
    position: int = Field(..., description="Ordering index")
    usage_count: int = Field(..., description="Usage counter maintained server-side")
    last_used_at: Optional[datetime] = Field(
        None, description="Timestamp of the last usage event"
    )
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    model_config = ConfigDict(from_attributes=True)


class ActualEventQuickTemplatePagination(Pagination):
    """Pagination metadata for quick templates."""


class ActualEventQuickTemplateListMeta(BaseModel):
    """Additional list metadata for quick templates."""

    order_by: Optional[str] = Field(None, description="Applied ordering strategy")


class ActualEventQuickTemplateListResponse(
    ListResponse[ActualEventQuickTemplateResponse, ActualEventQuickTemplateListMeta]
):
    """Paginated collection response for quick templates."""

    items: List[ActualEventQuickTemplateResponse] = Field(
        ..., description="Template items"
    )
    pagination: ActualEventQuickTemplatePagination
    meta: ActualEventQuickTemplateListMeta


class ActualEventQuickTemplateReorderItem(BaseModel):
    """Reorder request item mapping template to target position."""

    id: UUID = Field(..., description="Template identifier")
    position: int = Field(..., ge=0, description="New position index")


class ActualEventQuickTemplateReorderRequest(BaseModel):
    """Bulk reorder request payload."""

    items: List[ActualEventQuickTemplateReorderItem] = Field(
        ..., description="Ordered list of template-position pairs"
    )


class ActualEventQuickTemplateBulkCreateRequest(BaseModel):
    """Batch create request used during migration from local storage."""

    items: List[ActualEventQuickTemplateCreate] = Field(
        ..., description="Templates to create in bulk"
    )
