"""Pydantic schemas for admin-managed hub A2A agent catalog."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.pagination import ListResponse, Pagination

HubA2AAuthType = Literal["none", "bearer"]
HubA2AAvailabilityPolicy = Literal["public", "allowlist"]


class HubA2AAgentBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    card_url: str = Field(..., min_length=4, max_length=1024)
    availability_policy: HubA2AAvailabilityPolicy = Field(default="public")
    auth_type: HubA2AAuthType = Field(default="none")
    auth_header: Optional[str] = Field(default=None)
    auth_scheme: Optional[str] = Field(default=None)
    enabled: bool = Field(default=True)
    tags: List[str] = Field(default_factory=list)
    extra_headers: Dict[str, str] = Field(default_factory=dict)


class HubA2AAgentAdminCreate(HubA2AAgentBase):
    token: Optional[str] = Field(
        default=None,
        min_length=1,
        description="Bearer token to encrypt when auth_type=bearer",
    )


class HubA2AAgentAdminUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    card_url: Optional[str] = Field(default=None, min_length=4, max_length=1024)
    availability_policy: Optional[HubA2AAvailabilityPolicy] = None
    auth_type: Optional[HubA2AAuthType] = None
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


class HubA2AAgentAdminResponse(HubA2AAgentBase):
    id: UUID
    has_credential: bool = Field(
        default=False, description="Whether a system-managed credential is configured"
    )
    token_last4: Optional[str] = Field(
        default=None, description="Last four characters of the stored token"
    )
    created_by_user_id: UUID
    updated_by_user_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class HubA2AAgentUserResponse(BaseModel):
    id: UUID
    name: str
    card_url: str
    tags: List[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class HubA2AAgentPagination(Pagination):
    """Pagination metadata for hub agent listings."""


class HubA2AAgentListMeta(BaseModel):
    """Additional list metadata for hub agents."""


class HubA2AAgentAdminListResponse(
    ListResponse[HubA2AAgentAdminResponse, HubA2AAgentListMeta]
):
    items: List[HubA2AAgentAdminResponse]
    pagination: HubA2AAgentPagination
    meta: HubA2AAgentListMeta


class HubA2AAgentUserListResponse(
    ListResponse[HubA2AAgentUserResponse, HubA2AAgentListMeta]
):
    items: List[HubA2AAgentUserResponse]
    pagination: HubA2AAgentPagination
    meta: HubA2AAgentListMeta


class HubA2AAllowlistAddRequest(BaseModel):
    user_id: Optional[UUID] = Field(default=None)
    email: Optional[str] = Field(
        default=None, description="User email (server resolves to user_id)"
    )


class HubA2AAllowlistEntryResponse(BaseModel):
    id: UUID
    agent_id: UUID
    user_id: UUID
    user_email: Optional[str] = None
    user_name: Optional[str] = None
    created_by_user_id: UUID
    created_at: datetime


class HubA2AAllowlistListResponse(BaseModel):
    items: List[HubA2AAllowlistEntryResponse]


__all__ = [
    "HubA2AAuthType",
    "HubA2AAvailabilityPolicy",
    "HubA2AAgentAdminCreate",
    "HubA2AAgentAdminUpdate",
    "HubA2AAgentAdminResponse",
    "HubA2AAgentUserResponse",
    "HubA2AAgentAdminListResponse",
    "HubA2AAgentUserListResponse",
    "HubA2AAllowlistAddRequest",
    "HubA2AAllowlistEntryResponse",
    "HubA2AAllowlistListResponse",
]
