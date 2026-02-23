"""Pydantic schemas for A2A agent card validation."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import AnyHttpUrl, BaseModel, Field

from app.schemas.a2a_agent import A2AAuthType


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
    extra_headers: Dict[str, str] = Field(default_factory=dict)


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


__all__ = ["A2AAgentCardProxyRequest", "A2AAgentCardValidationResponse"]
