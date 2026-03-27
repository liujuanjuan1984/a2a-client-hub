"""Schemas for A2A extension endpoints."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class A2AExtensionQueryRequest(BaseModel):
    page: int = Field(1, ge=1, description="Page number (1-indexed)")
    size: Optional[int] = Field(
        default=None,
        ge=1,
        description="Page size (uses card default when omitted)",
    )
    include_raw: bool = Field(
        default=False,
        description="Whether to include the upstream raw payload in the response",
    )
    query: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional query object forwarded to the upstream extension method",
    )


class A2AExtensionResponse(BaseModel):
    success: bool
    result: Optional[Any] = None
    error_code: Optional[str] = None
    source: Optional[str] = None
    jsonrpc_code: Optional[int] = None
    missing_params: Optional[List[Dict[str, Any]]] = None
    upstream_error: Optional[Dict[str, Any]] = None
    meta: Dict[str, Any] = Field(default_factory=dict)


class A2ARuntimeStatusContractResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    version: str
    canonical_states: List[str] = Field(..., alias="canonicalStates")
    terminal_states: List[str] = Field(..., alias="terminalStates")
    final_states: List[str] = Field(..., alias="finalStates")
    interactive_states: List[str] = Field(..., alias="interactiveStates")
    failure_states: List[str] = Field(..., alias="failureStates")
    aliases: Dict[str, str]
    passthrough_unknown: bool = Field(..., alias="passthroughUnknown")


class A2AExtensionQueryPagination(BaseModel):
    model_config = ConfigDict(extra="allow")

    page: int = Field(..., ge=1)
    size: int = Field(..., ge=1)
    total: Optional[int] = None
    pages: Optional[int] = None


class A2AExtensionQueryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: List[Dict[str, Any]]
    pagination: A2AExtensionQueryPagination
    raw: Optional[Any] = None


class A2AExtensionQueryResponse(A2AExtensionResponse):
    result: Optional[A2AExtensionQueryResult] = None


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


class A2AExtensionSessionCommandRequest(BaseModel):
    request: Dict[str, Any] = Field(
        ...,
        description="Session command payload forwarded through the hub contract",
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional extension metadata object forwarded to upstream",
    )


class A2AModelDiscoveryRequest(BaseModel):
    provider_id: Optional[str] = Field(
        default=None,
        min_length=1,
        description="Optional provider id filter for generic model discovery",
    )
    session_metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Optional session metadata envelope used by the backend to resolve "
            "provider-private discovery context"
        ),
    )


class A2ASessionControlMethodResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    declared: bool = Field(
        ...,
        description="Whether the upstream extension currently declares this control method",
    )
    consumed_by_hub: bool = Field(
        ...,
        alias="consumedByHub",
        description="Whether the hub currently consumes and exposes this control method",
    )
    availability: Literal["always", "conditional", "unsupported"] = Field(
        ...,
        description="Hub-normalized availability for this control method",
    )
    method: Optional[str] = Field(
        default=None,
        description="Declared upstream JSON-RPC method name when available",
    )
    enabled_by_default: Optional[bool] = Field(
        default=None,
        alias="enabledByDefault",
        description="Whether the deployment-conditional method is enabled by default",
    )
    config_key: Optional[str] = Field(
        default=None,
        alias="configKey",
        description="Configuration key that governs deployment-conditional availability",
    )


class A2ASessionControlCapabilitiesResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    prompt_async: A2ASessionControlMethodResponse = Field(..., alias="promptAsync")
    command: A2ASessionControlMethodResponse
    shell: A2ASessionControlMethodResponse


class A2AExtensionCapabilitiesResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    model_selection: bool = Field(
        ...,
        alias="modelSelection",
        description="Whether the agent supports generic chat model selection",
    )
    provider_discovery: bool = Field(
        ...,
        alias="providerDiscovery",
        description="Whether the agent exposes OpenCode provider/model discovery",
    )
    session_prompt_async: bool = Field(
        ...,
        alias="sessionPromptAsync",
        description=(
            "Whether the agent advertises shared session-query prompt_async support"
        ),
    )
    session_control: A2ASessionControlCapabilitiesResponse = Field(
        ...,
        alias="sessionControl",
        description="Hub-stable method-level session control capability contract",
    )
    runtime_status: A2ARuntimeStatusContractResponse = Field(
        ...,
        alias="runtimeStatus",
        description="Canonical runtime status contract advertised by the hub.",
    )


__all__ = [
    "A2AExtensionPromptAsyncRequest",
    "A2AExtensionSessionCommandRequest",
    "A2AExtensionCapabilitiesResponse",
    "A2ASessionControlCapabilitiesResponse",
    "A2ASessionControlMethodResponse",
    "A2AModelDiscoveryRequest",
    "A2AExtensionPermissionReplyRequest",
    "A2ARuntimeStatusContractResponse",
    "A2AExtensionQueryPagination",
    "A2AExtensionQueryResponse",
    "A2AExtensionQueryRequest",
    "A2AExtensionQueryResult",
    "A2AExtensionQuestionRejectRequest",
    "A2AExtensionQuestionReplyRequest",
    "A2AExtensionResponse",
]
