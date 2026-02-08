"""Pydantic schemas for user-managed A2A agents."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.pagination import ListResponse, Pagination

A2AAuthType = Literal["none", "bearer"]


class A2AAgentBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    card_url: str = Field(..., min_length=4, max_length=1024)
    auth_type: A2AAuthType = Field(default="none")
    auth_header: Optional[str] = Field(default=None)
    auth_scheme: Optional[str] = Field(default=None)
    enabled: bool = Field(default=True)
    tags: List[str] = Field(default_factory=list)
    extra_headers: Dict[str, str] = Field(default_factory=dict)


class A2AAgentCreate(A2AAgentBase):
    token: Optional[str] = Field(
        default=None,
        min_length=1,
        description="Bearer token to encrypt when auth_type=bearer",
    )


class A2AAgentUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    card_url: Optional[str] = Field(default=None, min_length=4, max_length=1024)
    auth_type: Optional[A2AAuthType] = None
    auth_header: Optional[str] = None
    auth_scheme: Optional[str] = None
    enabled: Optional[bool] = None
    tags: Optional[List[str]] = None
    extra_headers: Optional[Dict[str, str]] = None
    token: Optional[str] = Field(
        default=None,
        min_length=1,
        description="New bearer token to replace the stored secret",
    )


class A2AAgentResponse(A2AAgentBase):
    id: UUID
    token_last4: Optional[str] = Field(
        default=None, description="Last four characters of the stored token"
    )
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class A2AAgentPagination(Pagination):
    """Pagination metadata for A2A agent listings."""


class A2AAgentListMeta(BaseModel):
    """Additional list metadata for agents."""


class A2AAgentListResponse(ListResponse[A2AAgentResponse, A2AAgentListMeta]):
    items: List[A2AAgentResponse]
    pagination: A2AAgentPagination
    meta: A2AAgentListMeta


__all__ = [
    "A2AAgentCreate",
    "A2AAgentUpdate",
    "A2AAgentResponse",
    "A2AAgentListResponse",
    "A2AAgentPagination",
    "A2AAgentListMeta",
]
