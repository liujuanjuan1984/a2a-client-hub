"""Pydantic schemas for invitation API responses."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.pagination import ListResponse, Pagination


class InvitationStatusEnum(str, enum.Enum):
    pending = "pending"
    registered = "registered"
    revoked = "revoked"
    expired = "expired"


class InvitationCreateRequest(BaseModel):
    email: EmailStr = Field(..., description="Email address to invite")
    memo: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Optional operator note recorded with the invitation",
    )


class InvitationResponse(BaseModel):
    id: UUID
    code: str
    target_email: EmailStr
    status: InvitationStatusEnum
    creator_user_id: UUID
    target_user_id: Optional[UUID]
    memo: Optional[str]
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime]
    registered_at: Optional[datetime]
    revoked_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class InvitationWithCreatorResponse(InvitationResponse):
    creator_email: Optional[EmailStr] = None
    creator_name: Optional[str] = None


class InvitationPagination(Pagination):
    """Pagination metadata for invitation lists."""


class InvitationListMeta(BaseModel):
    """Additional list metadata for invitations."""

    scope: Optional[Literal["created", "invited"]] = Field(
        None, description="List scope for invitations"
    )
    creator_user_id: Optional[UUID] = Field(
        None, description="Creator user ID for created invitations"
    )
    target_email: Optional[EmailStr] = Field(
        None, description="Target email for invitations addressed to the user"
    )


class InvitationListResponse(ListResponse[InvitationResponse, InvitationListMeta]):
    """Paginated invitation response."""

    items: List[InvitationResponse]
    pagination: InvitationPagination
    meta: InvitationListMeta


class InvitationWithCreatorListResponse(
    ListResponse[InvitationWithCreatorResponse, InvitationListMeta]
):
    """Paginated invitation response including creator info."""

    items: List[InvitationWithCreatorResponse]
    pagination: InvitationPagination
    meta: InvitationListMeta


class InvitationLookupResponse(BaseModel):
    code: str
    target_email: EmailStr
    status: InvitationStatusEnum
    creator_email: Optional[EmailStr]
    creator_name: Optional[str]
    memo: Optional[str]

    model_config = ConfigDict(from_attributes=True)
