"""
Export schemas for different data types
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ExportParams(BaseModel):
    """Base parameters for export operations."""

    locale: Optional[str] = Field(default="zh-CN", description="Locale for formatting")


class TimeLogExportParams(ExportParams):
    """Parameters for timelog export."""

    start_date: datetime = Field(description="Start date for export range")
    end_date: datetime = Field(description="End date for export range")
    dimension_id: Optional[UUID] = Field(
        default=None, description="Filter by dimension"
    )
    description_keyword: Optional[str] = Field(
        default=None, description="Filter by keyword in description"
    )


class NotesExportParams(ExportParams):
    """Parameters for notes export."""

    selected_filter_tags: List[Dict[str, Any]] = Field(
        default_factory=list, description="Tag filters"
    )
    selected_filter_persons: List[Dict[str, Any]] = Field(
        default_factory=list, description="Person filters"
    )
    search_keyword: str = Field(default="", description="Search keyword")
    filter_summary: List[str] = Field(
        default_factory=list, description="Filter summary description"
    )


class PlanningExportParams(ExportParams):
    """Parameters for planning export."""

    view_type: str = Field(description="View type: year, month, week, day")
    selected_date: datetime = Field(description="Selected date for export")
    include_notes: bool = Field(
        default=True, description="Include related notes in export"
    )
    include_task_notes: Optional[bool] = Field(
        default=None,
        description="Include notes linked to tasks in the selected planning window",
    )
    include_cycle_notes: Optional[bool] = Field(
        default=None,
        description="Include notes created in the selected planning window",
    )


class VisionExportParams(ExportParams):
    """Parameters for vision export."""

    include_subtasks: bool = Field(
        default=True, description="Include subtasks in export"
    )
    include_notes: bool = Field(
        default=True, description="Include task notes in export"
    )
    include_time_records: bool = Field(default=True, description="Include time records")


class FinanceTradingExportParams(ExportParams):
    """Parameters for finance trading export."""

    plan_id: UUID = Field(description="Trading plan ID")
    instrument_id: Optional[UUID] = Field(
        default=None, description="Filter by instrument"
    )
    start_time: Optional[datetime] = Field(
        default=None, description="Filter trades from this time (inclusive)"
    )
    end_time: Optional[datetime] = Field(
        default=None, description="Filter trades until this time (inclusive)"
    )
    format: str = Field(default="text", description="Export format: text|csv|json")


class FinanceAccountsExportParams(ExportParams):
    format: str = Field(default="text", description="Export format: text|csv|json")
    tree_id: Optional[UUID] = Field(default=None, description="Account tree id")


class FinanceCashflowExportParams(ExportParams):
    start_time: Optional[datetime] = Field(
        default=None, description="Filter snapshots from this time"
    )
    end_time: Optional[datetime] = Field(
        default=None, description="Filter snapshots until this time"
    )
    format: str = Field(default="text", description="Export format: text|csv|json")
    tree_id: Optional[UUID] = Field(default=None, description="Cashflow source tree id")


class ExportResult(BaseModel):
    """Result of an export operation."""

    success: bool = Field(description="Whether the export was successful")
    message: str = Field(description="Result message")
    export_text: Optional[str] = Field(
        default=None, description="Formatted export text"
    )
    content_type: str = Field(
        default="text/plain", description="Content type of the export"
    )
    filename: Optional[str] = Field(
        default=None, description="Suggested filename for download"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None, description="Additional metadata (e.g., truncation info)"
    )


class ExportEstimateRequest(BaseModel):
    """Generic export estimate request."""

    module: str = Field(description="Module key, e.g. finance-trading")
    params: Dict[str, Any] = Field(default_factory=dict, description="Module params")


class ExportEstimateResult(BaseModel):
    """Response for export size estimation."""

    estimated_size_bytes: int = Field(description="Estimated export payload size")
    record_count: int = Field(description="Estimated record count")
    can_clipboard: bool = Field(description="Whether clipboard is recommended")


class ExportStatistics(BaseModel):
    """Statistics for export data."""

    total_records: int = Field(description="Total number of records")
    total_duration_minutes: Optional[int] = Field(
        default=None, description="Total duration in minutes"
    )
    dimension_stats: Optional[Dict[str, Any]] = Field(
        default=None, description="Statistics by dimension"
    )
    status_distribution: Optional[Dict[str, int]] = Field(
        default=None, description="Distribution by status"
    )
