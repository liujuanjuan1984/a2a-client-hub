"""Schemas for the current-user unified agent catalog."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

UnifiedAgentSource = Literal["personal", "shared", "builtin"]
UnifiedAgentAuthType = Literal["none", "bearer", "basic"]
UnifiedAgentHealthStatus = Literal["unknown", "healthy", "degraded", "unavailable"]
UnifiedAgentHealthReasonCode = Literal[
    "card_validation_failed",
    "runtime_validation_failed",
    "agent_unavailable",
    "client_reset_required",
    "credential_required",
    "unexpected_error",
]
UnifiedAgentCredentialMode = Literal["none", "shared", "user"]


class UnifiedAgentCatalogItem(BaseModel):
    id: str
    source: UnifiedAgentSource
    name: str
    card_url: str
    auth_type: UnifiedAgentAuthType = "none"
    enabled: bool = True
    health_status: UnifiedAgentHealthStatus = "unknown"
    last_health_check_at: Optional[datetime] = None
    last_health_check_error: Optional[str] = None
    last_health_check_reason_code: Optional[UnifiedAgentHealthReasonCode] = None
    credential_mode: Optional[UnifiedAgentCredentialMode] = None
    credential_configured: Optional[bool] = None
    credential_display_hint: Optional[str] = None
    description: Optional[str] = None
    runtime: Optional[str] = None
    resources: List[str] = Field(default_factory=list)
    extra_headers: Dict[str, str] = Field(default_factory=dict)
    invoke_metadata_defaults: Dict[str, str] = Field(default_factory=dict)


class UnifiedAgentCatalogResponse(BaseModel):
    items: List[UnifiedAgentCatalogItem]


class UnifiedAgentHealthCheckItem(BaseModel):
    agent_id: str
    agent_source: UnifiedAgentSource
    health_status: UnifiedAgentHealthStatus
    checked_at: datetime
    skipped_cooldown: bool = False
    error: Optional[str] = None
    reason_code: Optional[UnifiedAgentHealthReasonCode] = None


class UnifiedAgentHealthCheckSummary(BaseModel):
    requested: int
    checked: int
    skipped_cooldown: int
    healthy: int
    degraded: int
    unavailable: int
    unknown: int


class UnifiedAgentHealthCheckResponse(BaseModel):
    summary: UnifiedAgentHealthCheckSummary
    items: List[UnifiedAgentHealthCheckItem]
