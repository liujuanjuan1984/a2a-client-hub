"""Personal A2A agent feature schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Literal, Optional
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field

from app.schemas.pagination import ListResponse, Pagination

A2AAuthType = Literal["none", "bearer", "basic"]
A2AAgentHealthStatus = Literal["unknown", "healthy", "degraded", "unavailable"]
A2AAgentHealthReasonCode = Literal[
    "card_validation_failed",
    "runtime_validation_failed",
    "agent_unavailable",
    "client_reset_required",
    "unexpected_error",
]
A2AAgentHealthBucket = Literal[
    "all",
    "healthy",
    "degraded",
    "unavailable",
    "unknown",
    "attention",
]


class A2AAgentBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    card_url: AnyHttpUrl = Field(..., description="Must be a valid HTTP/HTTPS URL")
    auth_type: A2AAuthType = Field(default="none")
    auth_header: Optional[str] = Field(default=None)
    auth_scheme: Optional[str] = Field(default=None)
    enabled: bool = Field(default=True)
    tags: List[str] = Field(default_factory=list)
    extra_headers: Dict[str, str] = Field(default_factory=dict)
    invoke_metadata_defaults: Dict[str, str] = Field(default_factory=dict)


class A2AAgentCreate(A2AAgentBase):
    token: Optional[str] = Field(
        default=None,
        min_length=1,
        description="Bearer token to encrypt when auth_type=bearer",
    )
    basic_username: Optional[str] = Field(default=None, min_length=1)
    basic_password: Optional[str] = Field(default=None, min_length=1)


class A2AAgentUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    card_url: Optional[AnyHttpUrl] = Field(
        default=None, description="Must be a valid HTTP/HTTPS URL"
    )
    auth_type: Optional[A2AAuthType] = None
    auth_header: Optional[str] = None
    auth_scheme: Optional[str] = None
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


class A2AAgentResponse(A2AAgentBase):
    id: UUID
    health_status: A2AAgentHealthStatus
    consecutive_health_check_failures: int
    last_health_check_at: Optional[datetime] = None
    last_successful_health_check_at: Optional[datetime] = None
    last_health_check_error: Optional[str] = None
    last_health_check_reason_code: Optional[A2AAgentHealthReasonCode] = None
    token_last4: Optional[str] = Field(
        default=None, description="Last four characters of the stored token"
    )
    username_hint: Optional[str] = Field(
        default=None,
        description="Non-secret username hint for basic auth",
    )
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class A2AAgentPagination(Pagination):
    """Pagination metadata for A2A agent listings."""


class A2AAgentListCounts(BaseModel):
    healthy: int = 0
    degraded: int = 0
    unavailable: int = 0
    unknown: int = 0


class A2AAgentListMeta(BaseModel):
    """Additional list metadata for agents."""

    counts: A2AAgentListCounts = Field(default_factory=A2AAgentListCounts)


class A2AAgentListResponse(ListResponse[A2AAgentResponse, A2AAgentListMeta]):
    items: List[A2AAgentResponse]
    pagination: A2AAgentPagination
    meta: A2AAgentListMeta


class A2AAgentHealthCheckItem(BaseModel):
    agent_id: UUID
    health_status: A2AAgentHealthStatus
    checked_at: datetime
    skipped_cooldown: bool = False
    error: Optional[str] = None
    reason_code: Optional[A2AAgentHealthReasonCode] = None


class A2AAgentHealthCheckSummary(BaseModel):
    requested: int
    checked: int
    skipped_cooldown: int
    healthy: int
    degraded: int
    unavailable: int
    unknown: int


class A2AAgentHealthCheckResponse(BaseModel):
    summary: A2AAgentHealthCheckSummary
    items: List[A2AAgentHealthCheckItem]


__all__ = [
    "A2AAgentCreate",
    "A2AAgentHealthBucket",
    "A2AAgentHealthCheckItem",
    "A2AAgentHealthReasonCode",
    "A2AAgentHealthCheckResponse",
    "A2AAgentHealthCheckSummary",
    "A2AAgentHealthStatus",
    "A2AAgentUpdate",
    "A2AAgentResponse",
    "A2AAgentListResponse",
    "A2AAgentListCounts",
    "A2AAgentPagination",
    "A2AAgentListMeta",
]
