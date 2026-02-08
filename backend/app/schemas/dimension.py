"""
Dimension Pydantic schemas

This module contains all Pydantic schemas for dimension-related operations.
"""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.pagination import ListResponse, Pagination


class DimensionBase(BaseModel):
    """Base schema for dimension data"""

    name: str = Field(..., min_length=1, max_length=100, description="Dimension name")
    description: Optional[str] = Field(
        None, description="Detailed description of this life dimension"
    )
    color: str = Field(
        ...,
        pattern=r"^#[0-9A-Fa-f]{6}$",
        description="Color code in hex format (e.g., '#3B82F6')",
    )
    icon: Optional[str] = Field(
        None, max_length=50, description="Icon identifier for this dimension"
    )
    is_active: bool = Field(
        True, description="Whether this dimension is currently active"
    )
    display_order: int = Field(0, ge=0, description="Display order for this dimension")

    @field_validator("color")
    @classmethod
    def validate_color(cls, v):
        """Validate that color is a proper hex color code"""
        if v is None:
            return v
        if not v.startswith("#"):
            raise ValueError("Color must start with #")
        if len(v) != 7:
            raise ValueError("Color must be in format #RRGGBB")
        try:
            int(v[1:], 16)
        except ValueError:
            raise ValueError("Color must be a valid hex color code")
        return v.upper()

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        """Validate dimension name"""
        if v is None:
            return v
        if not v or not v.strip():
            raise ValueError("Dimension name cannot be empty")
        return v.strip()


class DimensionCreate(DimensionBase):
    """Schema for creating a new dimension"""


class DimensionUpdate(DimensionBase):
    """Schema for updating an existing dimension"""

    name: Optional[str] = Field(
        None, min_length=1, max_length=100, description="Dimension name"
    )
    description: Optional[str] = Field(
        None, description="Detailed description of this life dimension"
    )
    color: Optional[str] = Field(
        None, pattern=r"^#[0-9A-Fa-f]{6}$", description="Color code in hex format"
    )
    icon: Optional[str] = Field(
        None, max_length=50, description="Icon identifier for this dimension"
    )
    is_active: Optional[bool] = Field(
        None, description="Whether this dimension is currently active"
    )
    display_order: Optional[int] = Field(
        None, ge=0, description="Display order for this dimension"
    )


class DimensionResponse(DimensionBase):
    """Schema for dimension response data"""

    id: UUID = Field(..., description="Dimension ID")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    model_config = ConfigDict(from_attributes=True)


class DimensionSummaryResponse(BaseModel):
    """Lightweight dimension summary for embedding在其它实体中"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(..., description="Dimension ID")
    name: str = Field(..., description="Dimension name")
    color: Optional[str] = Field(
        None,
        description="Hex color assigned to the dimension (nullable for legacy data)",
    )


class DimensionPagination(Pagination):
    """Pagination metadata for dimension lists."""


class DimensionListMeta(BaseModel):
    """Additional list metadata for dimensions."""

    include_inactive: Optional[bool] = Field(
        None, description="Whether inactive dimensions are included"
    )


class DimensionListResponse(ListResponse[DimensionSummaryResponse, DimensionListMeta]):
    """Schema for dimension list response."""

    items: List[DimensionResponse]
    pagination: DimensionPagination
    meta: DimensionListMeta
