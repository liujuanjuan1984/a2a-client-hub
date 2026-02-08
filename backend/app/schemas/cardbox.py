from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.pagination import ListResponse, Pagination


class ContextBoxCreateRequest(BaseModel):
    module: str = Field(
        ..., description="context module, eg: timelog / notes / vision_tasks"
    )
    name: Optional[str] = Field(None, description="user defined name")
    filters: Dict[str, Any] = Field(default_factory=dict, description="select filters")
    overwrite: bool = Field(False, description="overwrite if name duplicates")


class ContextBoxSummary(BaseModel):
    box_id: int
    name: str
    module: str
    display_name: str
    card_count: int
    updated_at: datetime
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ContextBoxPagination(Pagination):
    """Pagination metadata for context boxes."""


class CardboxPagination(Pagination):
    """Pagination metadata for cardbox sessions."""


class CardboxSessionListMeta(BaseModel):
    """Additional list metadata for cardbox sessions."""


class CardboxSessionListResponse(ListResponse[Dict[str, Any], CardboxSessionListMeta]):
    """Schema for cardbox session list response (messages or tools)."""

    items: List[Dict[str, Any]]
    pagination: CardboxPagination
    meta: CardboxSessionListMeta = Field(default_factory=CardboxSessionListMeta)


class ContextBoxItem(BaseModel):
    """Schema for a single context box card item."""

    card_id: str = Field(..., description="Card identifier")
    content: str = Field("", description="Card content text")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ContextBoxListMeta(BaseModel):
    """Additional list metadata for context boxes."""

    source: Optional[str] = Field(
        default=None, description="Data source for the listing"
    )


class ContextBoxListResponse(ListResponse[ContextBoxSummary, ContextBoxListMeta]):
    """Schema for context box list response."""

    items: List[ContextBoxSummary]
    pagination: ContextBoxPagination
    meta: ContextBoxListMeta = Field(default_factory=ContextBoxListMeta)


class ContextBoxCreateResponse(BaseModel):
    """Schema for context box create response."""

    box: ContextBoxSummary


class ContextBoxPreviewResponse(ListResponse[ContextBoxItem, Dict[str, Any]]):
    """Schema for context box preview response."""

    box: ContextBoxSummary
    items: List[ContextBoxItem]
    pagination: ContextBoxPagination
    meta: Dict[str, Any] = Field(default_factory=dict)


class SessionContextSelectionRequest(BaseModel):
    session_id: UUID
    box_ids: List[int] = Field(default_factory=list)


class SessionContextBox(BaseModel):
    box: ContextBoxSummary
    order: int


class SessionContextSelectionResponse(BaseModel):
    session_id: UUID
    boxes: List[SessionContextBox]
    preview_messages: List[Dict[str, Any]] = Field(default_factory=list)
    source_card_ids: List[str] = Field(default_factory=list)


class SessionContextStateResponse(BaseModel):
    session_id: UUID
    boxes: List[SessionContextBox]


class SnapshotDateRange(BaseModel):
    """Date range metadata for snapshot cards."""

    start: datetime
    end: datetime


class ActualEventSnapshotDimensionStat(BaseModel):
    """Aggregated statistics for a single dimension in actual-event snapshots."""

    dimension_id: Optional[str] = Field(
        default=None, description="Dimension identifier"
    )
    count: int = Field(
        default=0, ge=0, description="Number of events for the dimension"
    )
    duration_minutes: Optional[int] = Field(
        default=None,
        description="Total duration in minutes for the dimension",
        ge=0,
    )


class ActualEventSnapshotSummary(BaseModel):
    """Structured summary contract for actual-event (timelog) snapshots."""

    total_records: int = Field(description="Number of events included in the snapshot")
    total_duration_minutes: Optional[int] = Field(
        default=None,
        description="Aggregate duration across all events in minutes",
        ge=0,
    )
    date_range: SnapshotDateRange = Field(
        description="Covered time range for the snapshot"
    )
    dimension_stats: List[ActualEventSnapshotDimensionStat] = Field(
        default_factory=list,
        description="Per-dimension statistics",
    )
    entry_ids: List[str] = Field(
        default_factory=list,
        description="Event identifiers included in the snapshot",
    )


class ActualEventSnapshotQuery(BaseModel):
    """Applied filters for the actual-event snapshot generation."""

    dimension_name: Optional[str] = Field(
        default=None, description="Filtered dimension name"
    )
    keyword: Optional[str] = Field(
        default=None, description="Keyword applied to title/description"
    )
    description_keyword: Optional[str] = Field(
        default=None,
        description="Keyword applied specifically to description fields",
    )
    tracking_method: Optional[str] = Field(
        default=None,
        description="Tracking method constraint (manual, auto, etc.)",
    )
    limit: Optional[int] = Field(
        default=None,
        ge=1,
        description="Maximum number of events considered in the snapshot",
    )
