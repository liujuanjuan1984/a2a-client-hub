"""
Note Pydantic schemas

This module contains Pydantic models for the Note entity.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from app.schemas.pagination import ListResponse, Pagination
from app.schemas.person import PersonSummaryResponse
from app.schemas.tag import TagResponse
from app.schemas.task import TaskSummaryResponse
from app.schemas.vision import VisionSummaryResponse


class NoteBase(BaseModel):
    """Base schema for note"""

    content: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="The main content of the note",
    )

    @field_validator("content")
    @classmethod
    def validate_content(cls, v):
        """Validate note content"""
        if not v or not v.strip():
            raise ValueError("Note content cannot be empty")
        return v.strip()


class NoteTimelogDimensionSummary(BaseModel):
    """Dimension summary embedded in timelog responses."""

    id: UUID = Field(..., description="Dimension identifier")
    name: Optional[str] = Field(None, description="Dimension name")
    color: Optional[str] = Field(
        None, description="Dimension color in hex format (if available)"
    )

    model_config = ConfigDict(from_attributes=True)


class NoteTimelogTaskSummary(BaseModel):
    """Task summary embedded in timelog responses."""

    id: UUID = Field(..., description="Associated task identifier")
    content: str = Field(..., description="Task title/content")
    status: Optional[str] = Field(None, description="Task status")
    vision_id: Optional[UUID] = Field(None, description="Associated vision identifier")
    vision_summary: Optional[VisionSummaryResponse] = Field(
        None, description="Optional embedded vision summary"
    )

    model_config = ConfigDict(from_attributes=True)


class NoteTimelogSummary(BaseModel):
    """Summary info for timelog entries linked to a note."""

    id: UUID = Field(..., description="Associated timelog ID")
    title: Optional[str] = Field(None, description="Timelog title or description")
    start_time: Optional[datetime] = Field(None, description="Timelog start time")
    end_time: Optional[datetime] = Field(None, description="Timelog end time")
    dimension_id: Optional[UUID] = Field(None, description="Dimension identifier")
    dimension_summary: Optional[NoteTimelogDimensionSummary] = Field(
        None, description="Optional dimension summary for quick display"
    )
    task_summary: Optional[NoteTimelogTaskSummary] = Field(
        None, description="Optional associated task summary"
    )
    created_at: Optional[datetime] = Field(None, description="Timelog creation time")
    updated_at: Optional[datetime] = Field(None, description="Timelog last update time")

    model_config = ConfigDict(from_attributes=True)


class NoteSummary(BaseModel):
    """Lightweight representation of a note for related entity lists."""

    id: UUID = Field(..., description="Note ID")
    content: str = Field(..., description="Note content snippet")
    created_at: datetime = Field(..., description="Record creation timestamp")
    updated_at: datetime = Field(..., description="Record last update timestamp")

    model_config = ConfigDict(from_attributes=True)


class NoteAssociationBase(BaseModel):
    """Shared association fields for note create/update."""

    person_ids: Optional[List[str]] = Field(
        None,
        description="List of person IDs to associate with this note",
    )
    tag_ids: Optional[List[str]] = Field(
        None,
        description="List of tag IDs to associate with this note",
    )
    task_id: Optional[UUID] = Field(
        None,
        description="Task ID to associate with this note",
    )
    actual_event_ids: Optional[List[UUID]] = Field(
        None,
        description="Actual event (timelog) IDs to associate with this note",
    )

    @field_validator("task_id", mode="before")
    @classmethod
    def validate_task_id(cls, v):
        """Convert empty string to None for task_id"""
        if isinstance(v, str) and v.strip() == "":
            return None
        return v


class NoteCreate(NoteBase, NoteAssociationBase):
    """Schema for creating a new note"""


class NoteUpdate(NoteAssociationBase):
    """Schema for updating a note"""

    content: Optional[str] = Field(
        None,
        min_length=1,
        description="The main content of the note",
    )

    @field_validator("content")
    @classmethod
    def validate_content(cls, v):
        """Validate note content"""
        if v is not None:
            if not v or not v.strip():
                raise ValueError("Note content cannot be empty")
            return v.strip()
        return v


class NoteBulkCreateItem(NoteBase):
    """Single entry for bulk note creation."""


class NoteBulkCreateFailedItem(BaseModel):
    """Represents one failed bulk creation entry."""

    index: int = Field(
        ...,
        ge=1,
        description="1-based index of the failed note within the current request",
    )
    content_preview: str = Field(
        ..., description="Truncated preview of the note content for display"
    )
    error: str = Field(..., description="Error message describing the failure")


class NoteBulkCreateRequest(BaseModel):
    """Schema for batch creating notes in a single request."""

    notes: List[NoteBulkCreateItem] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Ordered list of notes to be created",
    )
    person_ids: Optional[List[str]] = Field(
        None,
        description="Optional list of person IDs applied to every note",
    )
    tag_ids: Optional[List[str]] = Field(
        None,
        description="Optional list of tag IDs applied to every note",
    )
    task_id: Optional[UUID] = Field(
        None,
        description="Optional task associated with every note",
    )
    actual_event_ids: Optional[List[UUID]] = Field(
        None,
        description="Optional list of timelog IDs applied to every note",
    )


class NoteBulkCreateResponse(BaseModel):
    """Response payload for bulk note creation."""

    created_notes: List[NoteResponse] = Field(
        default_factory=list,
        description="Notes successfully created in this request",
    )
    failed_items: List[NoteBulkCreateFailedItem] = Field(
        default_factory=list,
        description="Notes that failed to create along with error context",
    )
    created_count: int = Field(
        ..., description="Total number of notes successfully created"
    )
    failed_count: int = Field(
        ..., description="Total number of notes that failed to create"
    )


class NoteIngestJobSummary(BaseModel):
    """Lightweight summary of the asynchronous ingest job."""

    id: UUID = Field(..., description="Job ID")
    status: str = Field(..., description="Current job status")
    retry_count: int = Field(..., description="Number of retry attempts made so far")
    error: Optional[str] = Field(
        None, description="Last error captured while processing the job"
    )
    created_at: datetime = Field(..., description="Job creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    model_config = ConfigDict(from_attributes=True)


class NoteResponse(NoteBase):
    """Schema for note response"""

    id: UUID = Field(..., description="Note ID")
    content: str = Field(..., description="Note content")
    created_at: datetime = Field(..., description="Record creation timestamp")
    updated_at: datetime = Field(..., description="Record last update timestamp")
    persons: List[PersonSummaryResponse] = Field(
        default_factory=list,
        description="List of persons associated with this note",
    )
    tags: List[TagResponse] = Field(
        default_factory=list,
        description="List of tags associated with this note",
    )
    task: Optional[TaskSummaryResponse] = Field(
        None,
        description="Task associated with this note",
    )
    timelogs: List[NoteTimelogSummary] = Field(
        default_factory=list,
        description="List of timelog entries associated with this note",
    )
    ingest_job: Optional[NoteIngestJobSummary] = Field(
        None,
        description="Auto-ingest workflow job summary when `auto_ingest` is enabled",
    )

    model_config = ConfigDict(from_attributes=True)


class NotePagination(Pagination):
    """Pagination metadata for note lists."""


class NoteListMeta(BaseModel):
    """Additional list metadata for notes."""

    tag_id: Optional[UUID] = None
    person_id: Optional[UUID] = None
    task_id: Optional[UUID] = None
    actual_event_id: Optional[UUID] = None
    keyword: Optional[str] = None
    untagged: Optional[bool] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    tag_ids: Optional[List[UUID]] = None
    tag_mode: Optional[Literal["any", "all", "none"]] = None
    person_ids: Optional[List[UUID]] = None
    person_mode: Optional[Literal["any", "all", "none"]] = None
    task_filter: Optional[Literal["any", "none", "specific", "has"]] = None
    sort_order: Optional[Literal["asc", "desc"]] = None


class NoteListResponse(ListResponse[NoteResponse, NoteListMeta]):
    """Schema for note list response."""

    items: List[NoteResponse]
    pagination: NotePagination
    meta: NoteListMeta


class NoteAdvancedSearchRequest(BaseModel):
    """Schema for advanced note search requests."""

    start_date: Optional[datetime] = Field(
        default=None,
        description="Inclusive start datetime for the search range (optional)",
    )
    end_date: Optional[datetime] = Field(
        default=None,
        description="Inclusive end datetime for the search range (optional)",
    )
    tag_ids: Optional[List[UUID]] = Field(
        default=None,
        description="Tag IDs to filter by when tag_mode is 'any' or 'all'",
    )
    tag_mode: Literal["any", "all", "none"] = Field(
        "any",
        description="Tag filter mode: any/all selected tags or notes without tags",
    )
    person_ids: Optional[List[UUID]] = Field(
        default=None,
        description="Person IDs to filter by when person_mode is 'any' or 'all'",
    )
    person_mode: Literal["any", "all", "none"] = Field(
        "any",
        description="Person filter mode: any/all selected persons or notes without persons",
    )
    task_filter: Literal["any", "none", "specific", "has"] = Field(
        "any",
        description="Task filter mode: any task, notes without task, or a specific task",
    )
    task_id: Optional[UUID] = Field(
        default=None,
        description="Task ID required when task_filter is 'specific'",
    )
    keyword: Optional[str] = Field(
        default=None,
        description="Keyword to search within note content",
    )
    sort_order: Literal["asc", "desc"] = Field(
        "desc", description="Sort order applied to created_at column"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "start_date": "2024-01-01T00:00:00Z",
                "end_date": "2024-01-31T23:59:59Z",
                "tag_ids": ["2b358acb-32c8-464e-8e5a-1b8ad24e8d5a"],
                "tag_mode": "any",
                "person_ids": ["7363d1d8-5e54-40a9-8b8f-a7a2dc02d523"],
                "person_mode": "any",
                "task_filter": "specific",
                "task_id": "a67d2b44-39de-4a8e-8f83-3e4c77f7b6f4",
                "keyword": "会议纪要",
                "sort_order": "desc",
            }
        }
    )

    @model_validator(mode="after")
    def validate_combinations(self) -> "NoteAdvancedSearchRequest":
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must be greater than or equal to start_date")

        if self.task_filter == "specific" and self.task_id is None:
            raise ValueError("task_id is required when task_filter is 'specific'")
        if self.task_filter != "specific":
            self.task_id = None

        if self.tag_mode == "none":
            self.tag_ids = None
        elif self.tag_ids is not None and len(self.tag_ids) == 0:
            self.tag_ids = []
        if self.person_mode == "none":
            self.person_ids = None
        elif self.person_ids is not None and len(self.person_ids) == 0:
            self.person_ids = []

        if self.keyword is not None:
            cleaned = self.keyword.strip()
            self.keyword = cleaned if cleaned else None

        return self


class NoteBatchTagUpdate(BaseModel):
    mode: Literal["add", "replace"] = Field(
        ..., description="Add tags to existing set or replace entire set"
    )
    tag_ids: List[UUID] = Field(
        ..., min_length=0, max_length=100, description="Tag IDs to apply"
    )


class NoteBatchPersonUpdate(BaseModel):
    mode: Literal["add", "replace"] = Field(
        ..., description="Add persons to existing set or replace entire set"
    )
    person_ids: List[UUID] = Field(
        ..., min_length=0, max_length=100, description="Person IDs to apply"
    )


class NoteBatchTaskUpdate(BaseModel):
    mode: Literal["replace", "clear"] = Field(
        ..., description="Replace task assignment or clear it"
    )
    task_id: Optional[UUID] = Field(
        default=None,
        description="Task ID required when mode is 'replace'",
    )

    @field_validator("task_id")
    @classmethod
    def validate_task_id(cls, value: Optional[UUID], info: ValidationInfo):
        mode = info.data.get("mode")
        if mode == "replace" and value is None:
            raise ValueError("task_id is required when mode is 'replace'")
        if mode == "clear" and value is not None:
            raise ValueError("task_id must be omitted when mode is 'clear'")
        return value


class NoteBatchContentUpdate(BaseModel):
    find_text: str = Field(..., min_length=1, description="Text snippet to search for")
    replace_text: str = Field(
        default="",
        description="Replacement text to use for matches",
    )
    case_sensitive: bool = Field(
        default=False,
        description="Whether the find/replace should be case-sensitive",
    )


class NoteBatchUpdateRequest(BaseModel):
    """Schema representing a batch update operation for notes."""

    note_ids: List[UUID] = Field(
        ..., min_length=1, max_length=100, description="IDs of notes to update"
    )
    operation: Literal["tags", "persons", "task", "content"] = Field(
        ..., description="Type of batch update to apply"
    )
    tags: Optional[NoteBatchTagUpdate] = Field(
        default=None, description="Configuration for tag batch operations"
    )
    persons: Optional[NoteBatchPersonUpdate] = Field(
        default=None, description="Configuration for person batch operations"
    )
    task: Optional[NoteBatchTaskUpdate] = Field(
        default=None, description="Configuration for task batch operations"
    )
    content: Optional[NoteBatchContentUpdate] = Field(
        default=None, description="Configuration for content batch operations"
    )

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: Optional[NoteBatchTagUpdate], info: ValidationInfo):
        if info.data.get("operation") == "tags" and value is None:
            raise ValueError("tags configuration is required for tag operations")
        return value

    @field_validator("persons")
    @classmethod
    def validate_persons(
        cls, value: Optional[NoteBatchPersonUpdate], info: ValidationInfo
    ):
        if info.data.get("operation") == "persons" and value is None:
            raise ValueError("persons configuration is required for person operations")
        return value

    @field_validator("task")
    @classmethod
    def validate_task(cls, value: Optional[NoteBatchTaskUpdate], info: ValidationInfo):
        if info.data.get("operation") == "task" and value is None:
            raise ValueError("task configuration is required for task operations")
        return value

    @field_validator("content")
    @classmethod
    def validate_content_config(
        cls, value: Optional[NoteBatchContentUpdate], info: ValidationInfo
    ):
        if info.data.get("operation") == "content" and value is None:
            raise ValueError("content configuration is required for content operations")
        return value


class NoteBatchUpdateResponse(BaseModel):
    updated_count: int = Field(..., description="Number of notes successfully updated")
    failed_ids: List[UUID] = Field(
        default_factory=list, description="IDs of notes that failed to update"
    )
    errors: List[str] = Field(
        default_factory=list, description="Error messages for failed updates"
    )


class NoteBatchDeleteRequest(BaseModel):
    note_ids: List[UUID] = Field(
        ..., min_length=1, max_length=100, description="IDs of notes to delete"
    )


class NoteBatchDeleteResponse(BaseModel):
    deleted_count: int = Field(..., description="Number of notes successfully deleted")
    failed_ids: List[UUID] = Field(
        default_factory=list, description="IDs of notes that failed to delete"
    )
    errors: List[str] = Field(
        default_factory=list, description="Errors encountered during deletion"
    )
