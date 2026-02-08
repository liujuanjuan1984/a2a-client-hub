"""Pydantic schemas for user BYOT credentials."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.pagination import ListResponse, Pagination


class UserLlmCredentialBase(BaseModel):
    provider: str = Field(default="openai", description="Provider identifier")
    display_name: Optional[str] = Field(
        default=None, description="User-facing label for the credential"
    )
    api_base: Optional[str] = Field(
        default=None, description="Optional base URL override for the provider"
    )
    model_override: Optional[str] = Field(
        default=None, description="Preferred model when using this credential"
    )


class UserLlmCredentialCreate(UserLlmCredentialBase):
    api_key: str = Field(..., min_length=4, description="Plain API key to encrypt")
    make_default: bool = Field(
        default=True,
        description="Whether the new credential should become the default",
    )


class UserLlmCredentialUpdate(BaseModel):
    provider: Optional[str] = None
    display_name: Optional[str] = None
    api_base: Optional[str] = None
    model_override: Optional[str] = None
    api_key: Optional[str] = Field(
        default=None,
        description="Optional new API key to replace the stored secret",
    )
    make_default: Optional[bool] = Field(
        default=None, description="Set credential as default when true"
    )


class UserLlmCredentialTestRequest(BaseModel):
    provider: str = Field(default="openai")
    api_key: str = Field(..., min_length=4)
    api_base: Optional[str] = None
    model_override: Optional[str] = None


class UserLlmCredentialTestResponse(BaseModel):
    success: bool
    message: str


class UserLlmCredentialResponse(UserLlmCredentialBase):
    id: UUID
    token_last4: Optional[str] = Field(
        default=None, description="Trailing characters for confirmation"
    )
    is_default: bool = False
    last_used_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserLlmCredentialPagination(Pagination):
    """Pagination metadata for credential listings."""


class UserLlmCredentialListMeta(BaseModel):
    """Additional list metadata for credentials."""

    provider: Optional[str] = None


class UserLlmCredentialListResponse(
    ListResponse[UserLlmCredentialResponse, UserLlmCredentialListMeta]
):
    items: List[UserLlmCredentialResponse]
    pagination: UserLlmCredentialPagination
    meta: UserLlmCredentialListMeta


__all__ = [
    "UserLlmCredentialCreate",
    "UserLlmCredentialUpdate",
    "UserLlmCredentialResponse",
    "UserLlmCredentialListResponse",
    "UserLlmCredentialPagination",
    "UserLlmCredentialListMeta",
    "UserLlmCredentialTestRequest",
    "UserLlmCredentialTestResponse",
]
