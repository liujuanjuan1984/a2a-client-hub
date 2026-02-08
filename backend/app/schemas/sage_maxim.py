"""Pydantic schemas for Sage Maxims feature."""

from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.pagination import ListResponse, Pagination


class SageMaximAuthor(BaseModel):
    """Minimal author info exposed to clients."""

    id: UUID = Field(..., description="Author identifier")
    name: str = Field(..., description="Author display name")

    model_config = ConfigDict(from_attributes=True)


class SageMaximBase(BaseModel):
    """Shared fields for create/update operations."""

    content: str = Field(
        ...,
        min_length=1,
        max_length=280,
        description="Maxim content limited to 280 characters",
    )
    language: str = Field(
        "zh-CN",
        min_length=2,
        max_length=16,
        description="ISO language tag for the maxim",
    )


class SageMaximCreate(SageMaximBase):
    """Payload for creating a maxim."""


class SageMaximResponse(BaseModel):
    """Full response model for a maxim entry."""

    id: UUID = Field(..., description="Maxim identifier")
    content: str = Field(..., description="Maxim content")
    language: str = Field(..., description="ISO language tag")
    like_count: int = Field(..., description="Total likes")
    dislike_count: int = Field(..., description="Total dislikes")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    author: SageMaximAuthor = Field(..., description="Author information")
    viewer_reaction: Optional[Literal["like", "dislike"]] = Field(
        default=None, description="Current user's reaction"
    )

    model_config = ConfigDict(from_attributes=True)


class SageMaximPagination(Pagination):
    """Pagination metadata for sage maxims."""


class SageMaximListMeta(BaseModel):
    """Additional list metadata for sage maxims."""

    sort: Optional[str] = Field(None, description="Applied sorting strategy")


class SageMaximListResponse(ListResponse[SageMaximResponse, SageMaximListMeta]):
    """List response with pagination metadata."""

    items: List[SageMaximResponse] = Field(
        default_factory=list, description="Returned maxim entries"
    )
    pagination: SageMaximPagination
    meta: SageMaximListMeta


class SageMaximReactionRequest(BaseModel):
    """Body for like/dislike operations."""

    action: Literal["like", "dislike"] = Field(..., description="Reaction type")


__all__ = [
    "SageMaximAuthor",
    "SageMaximBase",
    "SageMaximCreate",
    "SageMaximListResponse",
    "SageMaximReactionRequest",
    "SageMaximResponse",
]
