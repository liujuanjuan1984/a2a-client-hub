"""Schemas for A2A extension endpoints."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

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


class A2AExtensionPermissionReplyRequest(BaseModel):
    request_id: str = Field(..., min_length=1, description="Interrupt request id")
    reply: Literal["once", "always", "reject"] = Field(
        ...,
        description="Permission reply action",
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional extension metadata object forwarded to upstream",
    )


class A2AExtensionQuestionReplyRequest(BaseModel):
    request_id: str = Field(..., min_length=1, description="Interrupt request id")
    answers: List[List[str]] = Field(
        ...,
        description="Answer groups in the same order as asked questions",
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional extension metadata object forwarded to upstream",
    )


class A2AExtensionQuestionRejectRequest(BaseModel):
    request_id: str = Field(..., min_length=1, description="Interrupt request id")
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional extension metadata object forwarded to upstream",
    )


class A2AExtensionPromptAsyncRequest(BaseModel):
    request: Dict[str, Any] = Field(
        ...,
        description="Shared session control payload forwarded to upstream",
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional extension metadata object forwarded to upstream",
    )


class A2AProviderDiscoveryRequest(BaseModel):
    provider_id: Optional[str] = Field(
        default=None,
        min_length=1,
        description="Optional provider id filter for model discovery",
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional provider-private metadata object forwarded to upstream",
    )


__all__ = [
    "A2AExtensionPromptAsyncRequest",
    "A2AExtensionPermissionReplyRequest",
    "A2AExtensionQueryRequest",
    "A2AExtensionQuestionRejectRequest",
    "A2AExtensionQuestionReplyRequest",
    "A2AExtensionResponse",
    "A2AProviderDiscoveryRequest",
]
