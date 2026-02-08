"""
User Preference Pydantic schemas

This module contains simplified Pydantic models for user preference validation and serialization.
"""

from datetime import datetime
from typing import Any, Dict, List, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class UserPreferenceBase(BaseModel):
    """Base schema for user preference operations"""

    key: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Preference key (e.g., 'theme', 'language', 'notifications.email')",
    )
    value: Union[str, int, float, bool, Dict[str, Any], List[Any]] = Field(
        ..., description="Preference value"
    )
    module: str = Field(
        default="general",
        min_length=1,
        max_length=50,
        description="Module or category this preference belongs to (e.g., 'ui', 'notifications', 'calendar')",
    )


class UserPreferenceResponse(UserPreferenceBase):
    """Schema for user preference response"""

    id: UUID = Field(..., description="Unique preference record ID")
    user_id: UUID = Field(..., description="User ID who owns this preference")
    created_at: datetime = Field(..., description="Record creation timestamp")
    updated_at: datetime = Field(..., description="Record last update timestamp")

    model_config = ConfigDict(from_attributes=True)
