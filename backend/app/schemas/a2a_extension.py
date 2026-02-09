"""Schemas for A2A extension endpoints."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class A2AExtensionQueryRequest(BaseModel):
    page: int = Field(1, ge=1, description="Page number (1-indexed)")
    size: Optional[int] = Field(
        default=None,
        ge=1,
        description="Page size (uses card default when omitted)",
    )
    query: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional query object forwarded to the upstream extension method",
    )


class A2AExtensionResponse(BaseModel):
    success: bool
    result: Optional[Dict[str, Any]] = None
    error_code: Optional[str] = None
    upstream_error: Optional[Dict[str, Any]] = None
    meta: Dict[str, Any] = Field(default_factory=dict)


__all__ = ["A2AExtensionQueryRequest", "A2AExtensionResponse"]
