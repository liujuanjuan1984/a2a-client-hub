"""
Person Pydantic schemas for data validation

These schemas define the data structure for API requests and responses for person management.
Designed for the social module (v0.9) to track relationships and social interactions.
"""

from datetime import date as DateType
from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.pagination import ListResponse, Pagination
from app.schemas.tag import TagResponse


class PersonBase(BaseModel):
    """Base schema for person with common fields"""

    name: Optional[str] = Field(
        None,
        min_length=1,
        max_length=200,
        description="Person's name (can be null for anonymous contacts)",
    )
    nicknames: Optional[List[str]] = Field(
        None, description="Array of nicknames/aliases for this person"
    )
    birth_date: Optional[DateType] = Field(None, description="Person's birth date")
    location: Optional[str] = Field(
        None, min_length=1, max_length=100, description="Person's location or address"
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        """Validate person name"""
        if v is not None and not v.strip():
            raise ValueError("Person name cannot be empty string")
        return v.strip() if v else None

    @field_validator("nicknames")
    @classmethod
    def validate_nicknames(cls, v):
        """Validate nicknames list"""
        if v is not None:
            # Remove empty strings and duplicates
            v = [nickname.strip() for nickname in v if nickname and nickname.strip()]
            v = list(dict.fromkeys(v))  # Remove duplicates while preserving order
        return v if v else None

    @field_validator("birth_date", mode="before")
    @classmethod
    def validate_birth_date(cls, v):
        """Validate birth date - convert empty string to None"""
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    @field_validator("location")
    @classmethod
    def validate_location(cls, v):
        """Validate location - convert empty string to None"""
        if v is not None and not v.strip():
            return None
        return v.strip() if v else None

    @model_validator(mode="before")
    @classmethod
    def normalize_empty_strings(cls, values):
        """Convert empty strings to None for optional fields in Person schemas"""
        if isinstance(values, dict):
            if values.get("birth_date", None) == "":
                values["birth_date"] = None
            if values.get("location", None) == "":
                values["location"] = None
        return values


class PersonCreate(PersonBase):
    """Schema for creating a new person"""

    tag_ids: Optional[List[str]] = Field(
        None, description="List of tag IDs to associate with this person"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "张三",
                "nicknames": ["小张", "阿三"],
                "birth_date": "1990-05-15",
                "location": "北京市",
                "tag_ids": [1, 2],
            }
        }
    )


class PersonUpdate(PersonBase):
    """Schema for updating an existing person"""

    tag_ids: Optional[List[str]] = Field(
        None, description="List of tag IDs to associate with this person"
    )

    # Validators and normalization are inherited from PersonBase

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "张三丰",
                "nicknames": ["小张", "张师傅"],
                "birth_date": "1990-05-15",
                "location": "上海市",
                "tag_ids": [1, 3],
            }
        }
    )


class AnniversaryBase(BaseModel):
    """Base schema for anniversary"""

    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Anniversary name (e.g., 'First Met', 'Wedding Anniversary')",
    )
    date: DateType = Field(..., description="Anniversary date")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        """Validate anniversary name"""
        if not v or not v.strip():
            raise ValueError("Anniversary name cannot be empty")
        return v.strip()


class AnniversaryCreate(AnniversaryBase):
    """Schema for creating a new anniversary"""

    model_config = ConfigDict(
        json_schema_extra={"example": {"name": "First Met", "date": "2020-03-15"}}
    )


class AnniversaryUpdate(BaseModel):
    """Schema for updating an existing anniversary (partial)."""

    name: Optional[str] = Field(
        None, min_length=1, max_length=200, description="Updated anniversary name"
    )
    date: Optional[DateType] = Field(None, description="Updated anniversary date")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {"name": "Wedding Anniversary", "date": "2021-05-20"}
        }
    )


class AnniversaryResponse(AnniversaryBase):
    """Schema for anniversary response"""

    id: UUID = Field(..., description="Unique identifier for the anniversary")
    person_id: UUID = Field(
        ..., description="ID of the person this anniversary belongs to"
    )
    created_at: datetime = Field(..., description="Anniversary creation timestamp")
    updated_at: datetime = Field(..., description="Anniversary last update timestamp")

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": 1,
                "person_id": 1,
                "name": "First Met",
                "date": "2020-03-15",
                "created_at": "2024-01-15T10:30:00Z",
                "updated_at": "2024-01-15T10:30:00Z",
            }
        },
    )


class AnniversaryPagination(Pagination):
    """Pagination metadata for anniversary lists."""


class AnniversaryListMeta(BaseModel):
    """Additional list metadata for anniversary listings."""

    person_id: Optional[UUID] = Field(None, description="Associated person ID")


class AnniversaryListResponse(ListResponse[AnniversaryResponse, AnniversaryListMeta]):
    """Schema for anniversary list response."""

    items: List[AnniversaryResponse]
    pagination: AnniversaryPagination
    meta: AnniversaryListMeta


class PersonResponse(PersonBase):
    """Schema for person response (includes all fields)"""

    id: UUID = Field(..., description="Unique identifier for the person")
    display_name: str = Field(..., description="Display name (name or Person #id)")
    deleted_at: Optional[datetime] = Field(None, description="Soft delete timestamp")
    is_soft_deleted: bool = Field(
        False, description="Soft delete flag (True if deleted)"
    )
    created_at: datetime = Field(..., description="Person creation timestamp")
    updated_at: datetime = Field(..., description="Person last update timestamp")
    tags: List[TagResponse] = Field(default=[], description="Associated tags")
    anniversaries: List[AnniversaryResponse] = Field(
        default=[], description="Associated anniversaries"
    )

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": 1,
                "name": "张三",
                "nicknames": ["小张", "阿三"],
                "birth_date": "1990-05-15",
                "location": "北京市",
                "deleted_at": None,
                "is_soft_deleted": False,
                "created_at": "2024-01-15T10:30:00Z",
                "updated_at": "2024-01-15T10:30:00Z",
                "tags": [{"id": 1, "name": "friend"}, {"id": 2, "name": "colleague"}],
                "anniversaries": [
                    {
                        "id": 1,
                        "person_id": 1,
                        "name": "First Met",
                        "date": "2020-03-15",
                        "created_at": "2024-01-15T10:30:00Z",
                        "updated_at": "2024-01-15T10:30:00Z",
                    }
                ],
            }
        },
    )

    @model_validator(mode="after")
    def _derive_is_soft_deleted(self) -> "PersonResponse":
        """Derive is_soft_deleted from deleted_at to keep response consistent."""
        self.is_soft_deleted = self.deleted_at is not None
        return self


class PersonSummaryResponse(BaseModel):
    """Schema for person summary (minimal info for lists/selectors)"""

    id: UUID = Field(..., description="Unique identifier for the person")
    name: Optional[str] = Field(None, description="Person's name")
    display_name: str = Field(..., description="Display name (name or Person #id)")
    primary_nickname: str = Field(..., description="Primary nickname or display name")
    birth_date: Optional[DateType] = Field(None, description="Person's birth date")
    location: Optional[str] = Field(None, description="Person's location or address")
    tags: List[TagResponse] = Field(default=[], description="Associated tags")

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": 1,
                "name": "张三",
                "display_name": "张三",
                "primary_nickname": "小张",
                "tags": [
                    {
                        "id": 1,
                        "name": "friend",
                        "entity_type": "person",
                        "description": None,
                        "color": None,
                        "created_at": "2024-01-15T10:30:00Z",
                        "updated_at": "2024-01-15T10:30:00Z",
                    }
                ],
            }
        },
    )


class PersonPagination(Pagination):
    """Pagination metadata for person lists."""


class PersonListMeta(BaseModel):
    """Additional list metadata for persons."""

    search: Optional[str] = Field(None, description="Search keyword filter")
    tag_filter: Optional[str] = Field(None, description="Tag name filter")
    tag_id: Optional[UUID] = Field(None, description="Tag ID filter")


class PersonListResponse(ListResponse[PersonSummaryResponse, PersonListMeta]):
    """Schema for person list response"""

    items: List[PersonSummaryResponse] = Field(..., description="List of persons")
    pagination: PersonPagination
    meta: PersonListMeta

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "items": [
                    {
                        "id": 1,
                        "name": "张三",
                        "display_name": "张三",
                        "primary_nickname": "小张",
                        "tags": [{"id": 1, "name": "friend"}],
                    },
                    {
                        "id": 2,
                        "name": "李四",
                        "display_name": "李四",
                        "primary_nickname": "李四",
                        "tags": [{"id": 2, "name": "colleague"}],
                    },
                ],
                "pagination": {"page": 1, "size": 50, "total": 2, "pages": 1},
                "meta": {"search": None, "tag_filter": None},
            }
        }
    )


class PersonDetailListResponse(ListResponse[PersonResponse, PersonListMeta]):
    """Schema for person list response with full person records."""

    items: List[PersonResponse] = Field(..., description="List of persons")
    pagination: PersonPagination
    meta: PersonListMeta


class PersonActivityItem(BaseModel):
    """Schema for a single activity item in person timeline"""

    id: UUID = Field(..., description="Activity ID")
    type: str = Field(
        ...,
        description="Activity type: vision, task, planned_event, actual_event, note",
    )
    title: str = Field(..., description="Activity title/content")
    description: Optional[str] = Field(None, description="Activity description")
    date: datetime = Field(..., description="Activity date (created_at or start_time)")
    status: Optional[str] = Field(None, description="Activity status if applicable")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": 1,
                "type": "task",
                "title": "Complete project proposal",
                "description": "Write and review the project proposal document",
                "date": "2024-01-15T10:30:00Z",
                "status": "done",
            }
        }
    )


class PersonActivityPagination(Pagination):
    """Pagination metadata for person activity timeline."""


class PersonActivitiesMeta(BaseModel):
    """Additional metadata for person activity timeline."""

    person_id: UUID = Field(..., description="Person ID")
    person_name: str = Field(..., description="Person display name")
    activity_type: Optional[
        Literal["vision", "task", "planned_event", "actual_event", "note"]
    ] = Field(None, description="Activity type filter")


class PersonActivitiesResponse(ListResponse[PersonActivityItem, PersonActivitiesMeta]):
    """Schema for person activities timeline response"""

    items: List[PersonActivityItem] = Field(..., description="List of activities")
    pagination: PersonActivityPagination
    meta: PersonActivitiesMeta

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "items": [
                    {
                        "id": 1,
                        "type": "task",
                        "title": "Complete project proposal",
                        "description": "Write and review the project proposal document",
                        "date": "2024-01-15T10:30:00Z",
                        "status": "done",
                    },
                    {
                        "id": 2,
                        "type": "note",
                        "title": "Meeting notes with Zhang San",
                        "description": None,
                        "date": "2024-01-14T15:20:00Z",
                        "status": None,
                    },
                ],
                "pagination": {"page": 1, "size": 50, "total": 2, "pages": 1},
                "meta": {
                    "person_id": 1,
                    "person_name": "张三",
                    "activity_type": None,
                },
            }
        }
    )


class PersonTagSearchRequest(BaseModel):
    """Schema for searching persons by tag"""

    tag_id: Optional[UUID] = Field(
        None, description="Tag ID to search for (mutually exclusive with tag_name)"
    )
    tag_name: Optional[str] = Field(
        None,
        min_length=1,
        max_length=100,
        description="Tag name to search for (mutually exclusive with tag_id)",
    )

    @model_validator(mode="after")
    def validate_exactly_one_identifier(self) -> "PersonTagSearchRequest":
        """Ensure exactly one of tag_id or tag_name is provided"""
        if self.tag_id is None and self.tag_name is None:
            raise ValueError("Either 'tag_id' or 'tag_name' must be provided")
        if self.tag_id is not None and self.tag_name is not None:
            raise ValueError("Only one of 'tag_id' or 'tag_name' should be provided")
        return self

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "tag_id": 1,
                    "tag_name": None,
                },
                {
                    "tag_id": None,
                    "tag_name": "family",
                },
            ]
        }
    )
