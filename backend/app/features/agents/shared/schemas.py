"""Shared A2A agent feature schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.pagination import ListResponse, Pagination

SharedAgentAuthType = Literal["none", "bearer", "basic"]
SharedAgentCredentialMode = Literal["none", "shared", "user"]
SharedAgentAvailabilityPolicy = Literal["public", "allowlist"]


class SharedAgentBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    card_url: str = Field(..., min_length=4, max_length=1024)
    availability_policy: SharedAgentAvailabilityPolicy = Field(default="public")
    auth_type: SharedAgentAuthType = Field(default="none")
    auth_header: Optional[str] = Field(default=None)
    auth_scheme: Optional[str] = Field(default=None)
    credential_mode: SharedAgentCredentialMode = Field(default="none")
    enabled: bool = Field(default=True)
    tags: List[str] = Field(default_factory=list)
    extra_headers: Dict[str, str] = Field(default_factory=dict)
    invoke_metadata_defaults: Dict[str, str] = Field(default_factory=dict)


class SharedAgentAdminCreate(SharedAgentBase):
    token: Optional[str] = Field(
        default=None,
        min_length=1,
        description="Bearer token to encrypt when auth_type=bearer",
    )
    basic_username: Optional[str] = Field(default=None, min_length=1)
    basic_password: Optional[str] = Field(default=None, min_length=1)


class SharedAgentAdminUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    card_url: Optional[str] = Field(default=None, min_length=4, max_length=1024)
    availability_policy: Optional[SharedAgentAvailabilityPolicy] = None
    auth_type: Optional[SharedAgentAuthType] = None
    auth_header: Optional[str] = None
    auth_scheme: Optional[str] = None
    credential_mode: Optional[SharedAgentCredentialMode] = None
    enabled: Optional[bool] = None
    tags: Optional[List[str]] = None
    extra_headers: Optional[Dict[str, str]] = None
    invoke_metadata_defaults: Optional[Dict[str, str]] = None
    token: Optional[str] = Field(
        default=None,
        min_length=1,
        description="New bearer token to replace the stored secret",
    )
    basic_username: Optional[str] = Field(default=None, min_length=1)
    basic_password: Optional[str] = Field(default=None, min_length=1)


class SharedAgentAdminResponse(SharedAgentBase):
    id: UUID
    has_credential: bool = Field(
        default=False, description="Whether a system-managed credential is configured"
    )
    token_last4: Optional[str] = Field(
        default=None, description="Last four characters of the stored token"
    )
    username_hint: Optional[str] = Field(
        default=None,
        description="Non-secret username hint for basic auth credentials",
    )
    created_by_user_id: UUID
    updated_by_user_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SharedAgentUserResponse(BaseModel):
    id: UUID
    name: str
    card_url: str
    auth_type: SharedAgentAuthType
    credential_mode: SharedAgentCredentialMode
    credential_configured: bool = False
    credential_display_hint: Optional[str] = None
    tags: List[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class SharedAgentPagination(Pagination):
    """Pagination metadata for shared-agent listings."""


class SharedAgentListMeta(BaseModel):
    """Additional list metadata for shared A2A agents."""


class SharedAgentAdminListResponse(
    ListResponse[SharedAgentAdminResponse, SharedAgentListMeta]
):
    items: List[SharedAgentAdminResponse]
    pagination: SharedAgentPagination
    meta: SharedAgentListMeta


class SharedAgentUserListResponse(
    ListResponse[SharedAgentUserResponse, SharedAgentListMeta]
):
    items: List[SharedAgentUserResponse]
    pagination: SharedAgentPagination
    meta: SharedAgentListMeta


class SharedAgentAllowlistAddRequest(BaseModel):
    user_id: Optional[UUID] = Field(default=None)
    email: Optional[str] = Field(
        default=None, description="User email (server resolves to user_id)"
    )


class SharedAgentAllowlistEntryResponse(BaseModel):
    id: UUID
    agent_id: UUID
    user_id: UUID
    user_email: Optional[str] = None
    user_name: Optional[str] = None
    created_by_user_id: UUID
    created_at: datetime


class SharedAgentAllowlistListResponse(BaseModel):
    items: List[SharedAgentAllowlistEntryResponse]


class SharedAgentAllowlistReplaceRequest(BaseModel):
    entries: List[SharedAgentAllowlistAddRequest] = Field(default_factory=list)


class SharedAgentUserCredentialStatusResponse(BaseModel):
    agent_id: UUID
    auth_type: SharedAgentAuthType
    credential_mode: SharedAgentCredentialMode
    configured: bool = False
    token_last4: Optional[str] = None
    username_hint: Optional[str] = None


class SharedAgentUserCredentialUpsertRequest(BaseModel):
    token: Optional[str] = Field(default=None, min_length=1)
    basic_username: Optional[str] = Field(default=None, min_length=1)
    basic_password: Optional[str] = Field(default=None, min_length=1)
