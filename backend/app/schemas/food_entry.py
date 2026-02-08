"""
Food Entry Pydantic schemas

This module contains all Pydantic schemas for food entry-related operations.
"""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.food import FoodResponse
from app.schemas.pagination import ListResponse, Pagination


class FoodEntryBase(BaseModel):
    """Base schema for food entry data"""

    date: str = Field(..., description="Date in YYYY-MM-DD format")
    consumed_at: datetime = Field(..., description="Exact time when food was consumed")
    meal_type: str = Field(
        ..., description="Type of meal: breakfast, lunch, dinner, snack, other"
    )
    food_id: UUID = Field(..., description="ID of the food item consumed")
    portion_size_g: float = Field(..., gt=0, description="Portion size in grams")
    notes: Optional[str] = Field(
        None, description="Additional notes about this food entry"
    )

    @field_validator("date")
    @classmethod
    def validate_date(cls, v):
        """Validate date format"""
        try:
            datetime.strptime(v, "%Y-%m-%d")
            return v
        except ValueError:
            raise ValueError("Date must be in YYYY-MM-DD format")

    @field_validator("meal_type")
    @classmethod
    def validate_meal_type(cls, v):
        """Validate meal type"""
        valid_types = ["breakfast", "lunch", "dinner", "snack", "other"]
        if v not in valid_types:
            raise ValueError(f"Meal type must be one of: {', '.join(valid_types)}")
        return v


class FoodEntryCreate(FoodEntryBase):
    """Schema for creating a new food entry"""


class FoodEntryUpdate(BaseModel):
    """Schema for updating an existing food entry"""

    date: Optional[str] = Field(None, description="Date in YYYY-MM-DD format")
    consumed_at: Optional[datetime] = Field(
        None, description="Exact time when food was consumed"
    )
    meal_type: Optional[str] = Field(
        None, description="Type of meal: breakfast, lunch, dinner, snack, other"
    )
    food_id: Optional[UUID] = Field(None, description="ID of the food item consumed")
    portion_size_g: Optional[float] = Field(
        None, gt=0, description="Portion size in grams"
    )
    notes: Optional[str] = Field(
        None, description="Additional notes about this food entry"
    )


class FoodEntryResponse(FoodEntryBase):
    """Schema for food entry responses"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(..., description="Food entry ID")
    calories: Optional[float] = Field(
        None, description="Calculated calories for this portion"
    )
    protein: Optional[float] = Field(
        None, description="Calculated protein for this portion (g)"
    )
    carbs: Optional[float] = Field(
        None, description="Calculated carbohydrates for this portion (g)"
    )
    fat: Optional[float] = Field(
        None, description="Calculated fat for this portion (g)"
    )
    fiber: Optional[float] = Field(
        None, description="Calculated fiber for this portion (g)"
    )
    sugar: Optional[float] = Field(
        None, description="Calculated sugar for this portion (g)"
    )
    sodium: Optional[float] = Field(
        None, description="Calculated sodium for this portion (mg)"
    )
    created_at: str = Field(..., description="Creation timestamp")
    updated_at: str = Field(..., description="Last update timestamp")
    food: FoodResponse = Field(..., description="Food item details")

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def convert_datetime_to_iso(cls, v):
        """Convert datetime objects to ISO format strings"""
        if hasattr(v, "isoformat"):
            return v.isoformat()
        return v


class FoodEntrySummary(BaseModel):
    """Schema for food entry summary (used in lists)"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(..., description="Food entry ID")
    date: str = Field(..., description="Date in YYYY-MM-DD format")
    consumed_at: datetime = Field(..., description="Exact time when food was consumed")
    meal_type: str = Field(..., description="Type of meal")
    food_name: str = Field(..., description="Name of the food item")
    portion_size_g: float = Field(..., description="Portion size in grams")
    calories: Optional[float] = Field(
        None, description="Calculated calories for this portion"
    )
    notes: Optional[str] = Field(
        None, description="Additional notes about this food entry"
    )


class FoodEntryPagination(Pagination):
    """Pagination metadata for food entry lists."""


class FoodEntryListMeta(BaseModel):
    """Additional list metadata for food entry listings."""

    start_date: Optional[str] = Field(
        None, description="Applied start date filter (YYYY-MM-DD)"
    )
    end_date: Optional[str] = Field(
        None, description="Applied end date filter (YYYY-MM-DD)"
    )
    meal_type: Optional[str] = Field(None, description="Applied meal type filter")


class FoodEntryListResponse(ListResponse[FoodEntrySummary, FoodEntryListMeta]):
    """Schema for food entry list response."""

    items: List[FoodEntrySummary]
    pagination: FoodEntryPagination
    meta: FoodEntryListMeta


class DailyNutritionSummary(BaseModel):
    """Schema for daily nutrition summary"""

    date: str = Field(..., description="Date in YYYY-MM-DD format")
    total_calories: float = Field(..., description="Total calories for the day")
    total_protein: float = Field(..., description="Total protein for the day (g)")
    total_carbs: float = Field(..., description="Total carbohydrates for the day (g)")
    total_fat: float = Field(..., description="Total fat for the day (g)")
    total_fiber: float = Field(..., description="Total fiber for the day (g)")
    total_sugar: float = Field(..., description="Total sugar for the day (g)")
    total_sodium: float = Field(..., description="Total sodium for the day (mg)")
    entry_count: int = Field(..., description="Number of food entries for the day")
