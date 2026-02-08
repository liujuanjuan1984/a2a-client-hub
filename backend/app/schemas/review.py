"""Pydantic schemas for daily review workflows."""

from __future__ import annotations

from datetime import date as DateType
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class DailyReviewRunRequest(BaseModel):
    """Parameters to trigger a daily review run."""

    date: Optional[DateType] = Field(
        None, description="Target natural date, defaults to the day before today"
    )
    user_id: Optional[UUID] = Field(
        None, description="Specify user ID, only administrators can specify others"
    )
    force: bool = Field(
        False, description="Whether to force regeneration even if output already exists"
    )


class DailyReviewCardSummary(BaseModel):
    """Metadata about generated review cards."""

    stage: str
    card_id: Optional[str] = None
    content: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DailyReviewRunResponse(BaseModel):
    """API response payload for a daily review run."""

    status: str
    output_box: Optional[str] = None
    summaries: List[DailyReviewCardSummary] = Field(default_factory=list)
    chat_markdown: Optional[str] = None
    error: Optional[str] = None


class DailyReviewRunResult(BaseModel):
    """Envelope wrapping run result with user/date info."""

    user_id: UUID
    target_date: DateType
    trigger_source: str
    detail: DailyReviewRunResponse
