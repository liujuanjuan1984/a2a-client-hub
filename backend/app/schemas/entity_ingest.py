from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class EntityIngestRequest(BaseModel):
    """Request payload for free-text entity ingestion."""

    text: str = Field(
        ..., min_length=1, max_length=12000, description="User supplied free text"
    )
    session_id: Optional[UUID] = Field(
        None, description="Optional session identifier to reuse conversation context"
    )


class EntityIngestResponse(BaseModel):
    """Response payload summarizing the agent-driven ingest result."""

    content: str
    tool_runs: List[Dict[str, Any]] = []
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    cost_usd: Optional[Decimal] = None
    model_name: Optional[str] = None


# --------- Intermediate Representation (IR) for free-text extraction ---------


class TagDraft(BaseModel):
    """Lightweight tag definition produced by the extractor."""

    name: str = Field(..., min_length=1, max_length=100)
    entity_type: str = Field(
        default="general",
        description="Target entity type; defaults to general for MVP.",
    )
    description: Optional[str] = Field(None, max_length=500)
    color: Optional[str] = Field(
        None, max_length=7, description="Hex color like '#3B82F6' (optional)."
    )


class PersonDraft(BaseModel):
    """Person payload with only create-time fields (no dedup required)."""

    ref: Optional[str] = Field(
        None,
        description="Local-only key for cross references inside one extraction run.",
    )
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    nicknames: Optional[List[str]] = None
    birth_date: Optional[str] = Field(
        None, description="YYYY-MM-DD if present; keep raw text if uncertain."
    )
    location: Optional[str] = Field(None, max_length=200)
    tags: List[str] = Field(
        default_factory=list,
        description="Tag names to create/attach to this person (no IDs here).",
    )


class VisionDraft(BaseModel):
    """Vision payload used for creation-only flow."""

    ref: Optional[str] = Field(None, description="Local reference for tasks to target.")
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    person_refs: List[str] = Field(
        default_factory=list,
        description="Local person refs to associate after creation (optional).",
    )
    tags: List[str] = Field(
        default_factory=list, description="Tag names to create/attach to this vision"
    )


class TaskDraft(BaseModel):
    """Task payload; vision linkage is by local ref, not DB ID."""

    ref: Optional[str] = Field(None, description="Local reference for other entities.")
    content: str = Field(..., min_length=1, max_length=500)
    vision_ref: Optional[str] = Field(
        None, description="Local vision ref this task belongs to."
    )
    person_refs: List[str] = Field(
        default_factory=list,
        description="Local person refs to associate with this task (optional).",
    )
    tags: List[str] = Field(
        default_factory=list, description="Tag names to create/attach to this task"
    )


class HabitDraft(BaseModel):
    """Habit payload; task linkage via local ref."""

    ref: Optional[str] = Field(None, description="Local reference for note linking.")
    title: str = Field(..., max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    start_date: Optional[str] = Field(
        None, description="Start date text; can stay raw for MVP."
    )
    duration_days: Optional[int] = Field(
        None, description="Planned duration in days; optional for MVP."
    )
    task_ref: Optional[str] = Field(
        None, description="Local task ref this habit is attached to."
    )


class NoteDraft(BaseModel):
    """Note payload captured from the raw text."""

    content: str = Field(..., min_length=1, max_length=10000)
    person_refs: List[str] = Field(
        default_factory=list, description="Persons mentioned (local refs)."
    )
    tags: List[str] = Field(
        default_factory=list, description="Tag names to create/attach to this note"
    )
    task_ref: Optional[str] = Field(
        None, description="Single task to attach the note to (local ref)."
    )


class EntityExtraction(BaseModel):
    """Intermediate Representation: single-pass extraction result for creation flow."""

    note: NoteDraft
    persons: List[PersonDraft] = Field(default_factory=list)
    tags: List[TagDraft] = Field(default_factory=list)
    visions: List[VisionDraft] = Field(default_factory=list)
    tasks: List[TaskDraft] = Field(default_factory=list)
    habits: List[HabitDraft] = Field(default_factory=list)
    confidence: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Model self-reported confidence in extraction.",
    )
    uncertainties: List[str] = Field(
        default_factory=list,
        description="List of doubts/edge cases for caller to review.",
    )
