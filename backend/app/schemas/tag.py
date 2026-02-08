"""
Tag Pydantic schemas

This module contains Pydantic models for the unified tagging system.
"""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.pagination import ListResponse, Pagination

VALID_TAG_TYPES = ["person", "note", "task", "vision", "general"]
VALID_TAG_CATEGORIES = ["general", "location"]


def _normalize_tag_name(value: Optional[str], *, required: bool) -> Optional[str]:
    if value is None:
        if required:
            raise ValueError("Tag name cannot be empty")
        return None
    if not value or not value.strip():
        raise ValueError("Tag name cannot be empty")
    return value.strip().lower()


def _validate_entity_type(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if value not in VALID_TAG_TYPES:
        raise ValueError(f"Entity type must be one of: {', '.join(VALID_TAG_TYPES)}")
    return value


def _validate_category(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if value not in VALID_TAG_CATEGORIES:
        raise ValueError(f"Category must be one of: {', '.join(VALID_TAG_CATEGORIES)}")
    return value


def _validate_color(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if not value.startswith("#") or len(value) != 7:
        raise ValueError("Color must be a valid hex color (e.g., '#3B82F6')")
    return value


class TagBase(BaseModel):
    """Base schema for tag"""

    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Tag name (e.g., 'family', 'important', 'work', 'personal')",
    )
    entity_type: str = Field(
        default="general",
        min_length=1,
        max_length=50,
        description="Entity type this tag is designed for: 'person', 'note', 'task', 'vision', 'general'",
    )
    category: str = Field(
        default="general",
        min_length=1,
        max_length=50,
        description="Tag category for semantic grouping (e.g., 'general', 'location')",
    )
    description: Optional[str] = Field(
        None,
        description="Optional description explaining the purpose of this tag",
    )
    color: Optional[str] = Field(
        None,
        max_length=7,
        description="Color code for this tag (hex format, e.g., '#3B82F6')",
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        """Validate tag name"""
        return _normalize_tag_name(v, required=True)

    @field_validator("entity_type")
    @classmethod
    def validate_entity_type(cls, v):
        """Validate entity type"""
        return _validate_entity_type(v)

    @field_validator("category")
    @classmethod
    def validate_category(cls, v):
        """Validate category"""
        return _validate_category(v)

    @field_validator("color")
    @classmethod
    def validate_color(cls, v):
        """Validate color format"""
        return _validate_color(v)


class TagCreate(TagBase):
    """Schema for creating a new tag"""


class TagUpdate(BaseModel):
    """Schema for updating a tag"""

    name: Optional[str] = Field(
        None,
        min_length=1,
        max_length=100,
        description="Tag name",
    )
    entity_type: Optional[str] = Field(
        None,
        min_length=1,
        max_length=50,
        description="Entity type",
    )
    category: Optional[str] = Field(
        None,
        min_length=1,
        max_length=50,
        description="Tag category",
    )
    description: Optional[str] = Field(
        None,
        description="Tag description",
    )
    color: Optional[str] = Field(
        None,
        max_length=7,
        description="Tag color",
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        """Validate tag name"""
        return _normalize_tag_name(v, required=False)

    @field_validator("entity_type")
    @classmethod
    def validate_entity_type(cls, v):
        """Validate entity type"""
        return _validate_entity_type(v)

    @field_validator("category")
    @classmethod
    def validate_category(cls, v):
        """Validate category"""
        return _validate_category(v)

    @field_validator("color")
    @classmethod
    def validate_color(cls, v):
        """Validate color format"""
        return _validate_color(v)


class TagResponse(BaseModel):
    """Schema for tag response without mutating stored casing"""

    id: UUID = Field(..., description="Tag ID")
    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Tag name (preserves original casing)",
    )
    entity_type: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Entity type this tag is associated with",
    )
    category: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Tag category for semantic grouping",
    )
    description: Optional[str] = Field(
        None,
        description="Optional description explaining the purpose of this tag",
    )
    color: Optional[str] = Field(
        None,
        max_length=7,
        description="Color code for this tag (hex format, e.g., '#3B82F6')",
    )
    created_at: datetime = Field(..., description="Record creation timestamp")
    updated_at: datetime = Field(..., description="Record last update timestamp")

    model_config = ConfigDict(from_attributes=True)


class TagPagination(Pagination):
    """Pagination metadata for tag lists."""


class TagListMeta(BaseModel):
    """Additional list metadata for tag listings."""

    entity_type: Optional[str] = Field(None, description="Applied entity type filter")
    category: Optional[str] = Field(None, description="Applied category filter")


class TagListResponse(ListResponse[TagResponse, TagListMeta]):
    """Schema for tag list response."""

    items: List[TagResponse]
    pagination: TagPagination
    meta: TagListMeta


class TagCategoryOption(BaseModel):
    """Schema for tag category option."""

    value: str = Field(..., description="Tag category value")
    label: str = Field(..., description="Display label for the category")
