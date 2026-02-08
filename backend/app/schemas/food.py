"""
Food Pydantic schemas

This module contains all Pydantic schemas for food-related operations.
"""

from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.pagination import ListResponse, Pagination


class FoodFields(BaseModel):
    """Shared schema fields for food data."""

    name: str = Field(..., min_length=1, max_length=200, description="Food name")
    description: Optional[str] = Field(
        None, description="Additional description of the food"
    )
    is_common: bool = Field(
        False, description="Whether this is a commonly used food item"
    )
    calories_per_100g: Optional[float] = Field(
        None, ge=0, description="Calories per 100g"
    )
    protein_per_100g: Optional[float] = Field(
        None, ge=0, description="Protein content per 100g (g)"
    )
    carbs_per_100g: Optional[float] = Field(
        None, ge=0, description="Carbohydrate content per 100g (g)"
    )
    fat_per_100g: Optional[float] = Field(
        None, ge=0, description="Fat content per 100g (g)"
    )
    fiber_per_100g: Optional[float] = Field(
        None, ge=0, description="Fiber content per 100g (g)"
    )
    sugar_per_100g: Optional[float] = Field(
        None, ge=0, description="Sugar content per 100g (g)"
    )
    sodium_per_100g: Optional[float] = Field(
        None, ge=0, description="Sodium content per 100g (mg)"
    )


class FoodBase(FoodFields):
    """Base schema for food data"""

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        """Validate food name"""
        if not v or not v.strip():
            raise ValueError("Food name cannot be empty")
        return v.strip()


class FoodCreate(FoodBase):
    """Schema for creating a new food item"""


class FoodUpdate(FoodFields):
    """Schema for updating an existing food item"""

    name: Optional[str] = Field(
        None, min_length=1, max_length=200, description="Food name"
    )
    is_common: Optional[bool] = Field(
        None, description="Whether this is a commonly used food item"
    )


class FoodResponse(FoodBase):
    """Schema for food responses"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(..., description="Food ID")
    created_at: str = Field(..., description="Creation timestamp")
    updated_at: str = Field(..., description="Last update timestamp")

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def convert_datetime_to_iso(cls, v):
        """Convert datetime objects to ISO format strings"""
        if hasattr(v, "isoformat"):
            return v.isoformat()
        return v


class FoodSummary(BaseModel):
    """Schema for food summary (used in lists)"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(..., description="Food ID")
    name: str = Field(..., description="Food name")
    is_common: bool = Field(
        ..., description="Whether this is a commonly used food item"
    )
    calories_per_100g: Optional[float] = Field(None, description="Calories per 100g")


class FoodPagination(Pagination):
    """Pagination metadata for food lists."""


class FoodListMeta(BaseModel):
    """Additional list metadata for food listings."""

    search: Optional[str] = Field(None, description="Applied search keyword")
    common_only: Optional[bool] = Field(
        None, description="Whether only common foods were included"
    )


class FoodListResponse(ListResponse[FoodResponse, FoodListMeta]):
    """Schema for food list response."""

    items: List[FoodSummary]
    pagination: FoodPagination
    meta: FoodListMeta
