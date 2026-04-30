"""Pydantic schemas for A2A agent card validation."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field

from app.features.agents.personal.schemas import A2AAuthType
from app.schemas.a2a_compatibility_profile import (
    A2ACompatibilityProfileDiagnostic,
)
from app.schemas.a2a_extension import A2AExtensionCapabilitiesResponse


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
    model_config = ConfigDict(populate_by_name=True)

    declared: bool = Field(
        ..., description="Whether the card declares a shared session query extension"
    )
    status: Literal["supported", "unsupported", "invalid"] = Field(
        ...,
        description="Hub compatibility result for the declared session-query contract",
    )
    uri: Optional[str] = Field(default=None)
    declared_contract_family: Optional[Literal["opencode", "codex"]] = Field(
        default=None,
        alias="declaredContractFamily",
        description="Family inferred from the upstream-declared session-query contract",
    )
    provider: Optional[str] = Field(default=None)
    methods: List[str] = Field(default_factory=list)
    pagination_mode: Optional[str] = Field(default=None)
    pagination_params: List[str] = Field(default_factory=list)
    result_envelope_declared: Optional[bool] = Field(default=None)
    jsonrpc_interface_fallback_used: Optional[bool] = Field(default=None)
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
    extension_capabilities: Optional[A2AExtensionCapabilitiesResponse] = Field(
        default=None,
        alias="extensionCapabilities",
        description="Hub capability summary derived from declared extension contracts.",
    )
    shared_session_query: Optional[SharedSessionQueryDiagnostic] = Field(
        default=None,
        description="Shared session query extension compatibility diagnostics",
    )
    compatibility_profile: Optional[A2ACompatibilityProfileDiagnostic] = Field(
        default=None,
        description="Compatibility-profile extension diagnostics",
    )
