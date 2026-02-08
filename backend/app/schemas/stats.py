"""
Pydantic schemas for Statistics models
"""

from enum import Enum
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.pagination import ListResponse, Pagination


class DailyDimensionStatResponse(BaseModel):
    """Schema for daily dimension statistics response"""

    date: str = Field(..., description="Date in ISO format")
    dimension_id: UUID = Field(..., description="Dimension ID")
    minutes: int = Field(..., description="Minutes spent")


class AggregationGranularity(str, Enum):
    """Supported aggregation granularities for time statistics."""

    day = "day"
    week = "week"
    month = "month"
    year = "year"


class AggregatedDimensionStatResponse(BaseModel):
    """Schema for aggregated (non-daily) dimension statistics response."""

    granularity: AggregationGranularity = Field(
        ..., description="Aggregation granularity applied to the bucket"
    )
    period_start: str = Field(
        ..., description="Inclusive start date of the aggregated bucket"
    )
    period_end: str = Field(
        ..., description="Inclusive end date of the aggregated bucket"
    )
    dimension_id: UUID = Field(..., description="Dimension ID")
    minutes: int = Field(..., description="Minutes spent within the bucket")


class DayBreakdownResponse(BaseModel):
    """Schema for day breakdown response"""

    dimension_id: UUID = Field(..., description="Dimension ID")
    minutes: int = Field(..., description="Minutes spent")


class RecomputeResponse(BaseModel):
    """Schema for recompute operation response"""

    days_recomputed: int = Field(..., description="Number of days recomputed")


class TagUsageStatResponse(BaseModel):
    """Schema for tag usage statistics"""

    id: UUID = Field(..., description="Tag ID")
    name: str = Field(..., description="Tag name")
    usage_count: int = Field(..., description="Number of times tag is used")


class TagUsageStatsResponse(BaseModel):
    """Schema for tag usage statistics response"""

    entity_type: str = Field(..., description="Entity type")
    tag_stats: List[TagUsageStatResponse] = Field(
        ..., description="List of tag statistics"
    )
    total_tags: int = Field(..., description="Total number of tags")


class StatsPagination(Pagination):
    """Pagination metadata for stats listings."""


class DailyDimensionStatsMeta(BaseModel):
    """Additional list metadata for daily dimension stats."""

    start: Optional[str] = Field(None, description="Start date (YYYY-MM-DD)")
    end: Optional[str] = Field(None, description="End date (YYYY-MM-DD)")
    timezone: Optional[str] = Field(None, description="Timezone identifier (IANA)")
    dimension_ids: Optional[List[str]] = Field(
        None, description="Filtered dimension IDs"
    )


class DailyDimensionStatListResponse(
    ListResponse[DailyDimensionStatResponse, DailyDimensionStatsMeta]
):
    """Schema for daily dimension stats list response."""

    items: List[DailyDimensionStatResponse]
    pagination: StatsPagination
    meta: DailyDimensionStatsMeta


class AggregatedDimensionStatsMeta(BaseModel):
    """Additional list metadata for aggregated dimension stats."""

    granularity: Optional[AggregationGranularity] = None
    start: Optional[str] = Field(None, description="Start date (YYYY-MM-DD)")
    end: Optional[str] = Field(None, description="End date (YYYY-MM-DD)")
    timezone: Optional[str] = Field(None, description="Timezone identifier (IANA)")
    dimension_ids: Optional[List[str]] = Field(
        None, description="Filtered dimension IDs"
    )
    first_day_of_week: Optional[int] = Field(
        None, description="First day of the week (1=Monday ... 7=Sunday)"
    )
    calendar_system: Optional[str] = Field(
        None, description="Calendar system used for aggregation"
    )


class AggregatedDimensionStatListResponse(
    ListResponse[AggregatedDimensionStatResponse, AggregatedDimensionStatsMeta]
):
    """Schema for aggregated dimension stats list response."""

    items: List[AggregatedDimensionStatResponse]
    pagination: StatsPagination
    meta: AggregatedDimensionStatsMeta


class DayBreakdownMeta(BaseModel):
    """Additional list metadata for day breakdown stats."""

    day: Optional[str] = Field(None, description="Local day (YYYY-MM-DD)")
    timezone: Optional[str] = Field(None, description="Timezone identifier (IANA)")


class DayBreakdownListResponse(ListResponse[DayBreakdownResponse, DayBreakdownMeta]):
    """Schema for day breakdown list response."""

    items: List[DayBreakdownResponse]
    pagination: StatsPagination
    meta: DayBreakdownMeta
