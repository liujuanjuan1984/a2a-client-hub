"""Shared pagination schemas."""

from typing import Generic, List, TypeVar

from pydantic import BaseModel, Field

TItem = TypeVar("TItem")
TMeta = TypeVar("TMeta")


class Pagination(BaseModel):
    """Common pagination metadata."""

    page: int = Field(..., description="Current page number")
    size: int = Field(..., description="Page size")
    total: int = Field(..., description="Total number of items")
    pages: int = Field(..., description="Total number of pages")


class ListResponse(BaseModel, Generic[TItem, TMeta]):
    """Generic list response with pagination."""

    items: List[TItem]
    pagination: Pagination
    meta: TMeta
