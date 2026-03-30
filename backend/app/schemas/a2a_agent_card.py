"""Pydantic schemas for A2A agent card validation."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import AnyHttpUrl, BaseModel, Field

from app.features.personal_agents.schemas import A2AAuthType
from app.schemas.a2a_compatibility_profile import (
    A2ACompatibilityProfileDiagnostic,
)


class A2AAgentCardProxyRequest(BaseModel):
    card_url: AnyHttpUrl = Field(..., description="Must be a valid HTTP/HTTPS URL")
    auth_type: A2AAuthType = Field(default="none")
    auth_header: Optional[str] = Field(default=None)
    auth_scheme: Optional[str] = Field(default=None)
    token: Optional[str] = Field(
        default=None,
        min_length=1,
        description="Bearer token used when auth_type=bearer",
    )
    basic_username: Optional[str] = Field(default=None, min_length=1)
    basic_password: Optional[str] = Field(default=None, min_length=1)
    extra_headers: Dict[str, str] = Field(default_factory=dict)


class SharedSessionQueryDiagnostic(BaseModel):
    declared: bool = Field(
        ..., description="Whether the card declares a shared session query extension"
    )
    status: Literal["canonical", "legacy", "unsupported", "invalid"] = Field(
        ...,
        description="Hub compatibility classification for the declared contract",
    )
    uri: Optional[str] = Field(default=None)
    provider: Optional[str] = Field(default=None)
    methods: List[str] = Field(default_factory=list)
    pagination_mode: Optional[str] = Field(default=None)
    pagination_params: List[str] = Field(default_factory=list)
    result_envelope_declared: Optional[bool] = Field(default=None)
    jsonrpc_interface_fallback_used: Optional[bool] = Field(default=None)
    uses_legacy_uri: bool = Field(default=False)
    uses_legacy_contract_fields: bool = Field(default=False)
    error: Optional[str] = Field(
        default=None,
        description="Structured validation error when the contract is invalid",
    )


class A2AAgentCardValidationResponse(BaseModel):
    success: bool = Field(..., description="Whether the card validation succeeded")
    message: str = Field(..., description="Human-readable validation result")
    card_name: Optional[str] = Field(default=None)
    card_description: Optional[str] = Field(default=None)
    card: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Full agent card payload when available",
    )
    validation_errors: Optional[List[str]] = Field(
        default=None, description="Detailed validation errors (only in debug mode)"
    )
    validation_warnings: Optional[List[str]] = Field(
        default=None,
        description="Non-blocking validation warnings exposed to clients",
    )
    shared_session_query: Optional[SharedSessionQueryDiagnostic] = Field(
        default=None,
        description="Shared session query extension compatibility diagnostics",
    )
    compatibility_profile: Optional[A2ACompatibilityProfileDiagnostic] = Field(
        default=None,
        description="Compatibility-profile extension diagnostics",
    )


__all__ = [
    "A2AAgentCardProxyRequest",
    "A2AAgentCardValidationResponse",
    "SharedSessionQueryDiagnostic",
]
