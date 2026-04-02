"""Schemas for A2A extension endpoints."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.a2a_compatibility_profile import (
    A2ACompatibilityProfileDiagnostic,
)


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


class A2AExtensionSessionListFilters(BaseModel):
    directory: Optional[str] = Field(
        default=None,
        min_length=1,
        description="Optional session directory filter under the Hub contract",
    )
    roots: Optional[bool] = Field(
        default=None,
        description="Optional roots-only filter under the Hub contract",
    )
    start: Optional[int] = Field(
        default=None,
        ge=0,
        description="Optional non-negative start offset under the Hub contract",
    )
    search: Optional[str] = Field(
        default=None,
        min_length=1,
        description="Optional search text filter under the Hub contract",
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


class A2AExtensionQueryPageInfo(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    has_more_before: bool = Field(..., alias="hasMoreBefore")
    next_before: Optional[str] = Field(default=None, alias="nextBefore")


class A2AExtensionQueryResult(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    items: List[Dict[str, Any]]
    pagination: A2AExtensionQueryPagination
    page_info: Optional[A2AExtensionQueryPageInfo] = Field(
        default=None,
        alias="pageInfo",
    )
    raw: Optional[Any] = None


class A2AExtensionQueryResponse(A2AExtensionResponse):
    result: Optional[A2AExtensionQueryResult] = None


class A2AExtensionSessionMessagesQueryRequest(A2AExtensionQueryRequest):
    before: Optional[str] = Field(
        default=None,
        min_length=1,
        description=(
            "Opaque cursor for loading older session messages when the runtime "
            "declares cursor pagination support"
        ),
    )


class A2AExtensionSessionListQueryRequest(A2AExtensionQueryRequest):
    filters: Optional[A2AExtensionSessionListFilters] = Field(
        default=None,
        description="Optional typed session list filters under the Hub contract",
    )


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


class A2AExtensionPermissionsReplyRequest(BaseModel):
    request_id: str = Field(..., min_length=1, description="Interrupt request id")
    permissions: Dict[str, Any] = Field(
        ...,
        description="Granted permissions subset object forwarded to upstream",
    )
    scope: Optional[Literal["turn", "session"]] = Field(
        default=None,
        description="Optional permission persistence scope",
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional extension metadata object forwarded to upstream",
    )


class A2AExtensionElicitationReplyRequest(BaseModel):
    request_id: str = Field(..., min_length=1, description="Interrupt request id")
    action: Literal["accept", "decline", "cancel"] = Field(
        ...,
        description="Elicitation reply action",
    )
    content: Any = Field(
        default=None,
        description="Structured elicitation response payload when accepted",
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional extension metadata object forwarded to upstream",
    )

    @model_validator(mode="after")
    def validate_content_for_action(self) -> "A2AExtensionElicitationReplyRequest":
        if self.action in {"decline", "cancel"} and self.content is not None:
            raise ValueError("content must be null when action is decline or cancel")
        return self


class A2AExtensionPromptAsyncRequest(BaseModel):
    request: Dict[str, Any] = Field(
        ...,
        description="Shared session control payload forwarded to upstream",
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional extension metadata object forwarded to upstream",
    )


class A2AExtensionInterruptRecoveryRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    session_id: Optional[str] = Field(
        default=None,
        alias="sessionId",
        min_length=1,
        description=(
            "Optional upstream external session id used by the hub to narrow "
            "recovered interrupts to the current session"
        ),
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


class A2AInvokeMetadataFieldResponse(BaseModel):
    name: str
    required: bool
    description: Optional[str] = None


class A2AInvokeMetadataCapabilitiesResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    declared: bool
    consumed_by_hub: bool = Field(..., alias="consumedByHub")
    metadata_field: Optional[str] = Field(default=None, alias="metadataField")
    applies_to_methods: List[str] = Field(
        default_factory=list, alias="appliesToMethods"
    )
    fields: List[A2AInvokeMetadataFieldResponse] = Field(default_factory=list)


class A2AWireContractConditionalMethodResponse(BaseModel):
    reason: str
    toggle: Optional[str] = None


class A2AWireContractUnsupportedMethodErrorResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    code: int
    type: str
    data_fields: List[str] = Field(default_factory=list, alias="dataFields")


class A2AWireContractCapabilitiesResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    declared: bool
    consumed_by_hub: bool = Field(..., alias="consumedByHub")
    status: Literal["supported", "unsupported", "invalid"]
    protocol_version: Optional[str] = Field(default=None, alias="protocolVersion")
    preferred_transport: Optional[str] = Field(default=None, alias="preferredTransport")
    additional_transports: List[str] = Field(
        default_factory=list,
        alias="additionalTransports",
    )
    all_jsonrpc_methods: List[str] = Field(
        default_factory=list,
        alias="allJsonrpcMethods",
    )
    extension_uris: List[str] = Field(default_factory=list, alias="extensionUris")
    conditional_methods: Dict[str, A2AWireContractConditionalMethodResponse] = Field(
        default_factory=dict,
        alias="conditionalMethods",
    )
    unsupported_method_error: Optional[
        A2AWireContractUnsupportedMethodErrorResponse
    ] = Field(default=None, alias="unsupportedMethodError")
    error: Optional[str] = None


class A2AInterruptRecoveryItemResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    request_id: str = Field(..., alias="requestId")
    session_id: str = Field(..., alias="sessionId")
    type: Literal["permission", "question", "permissions", "elicitation"]
    details: Dict[str, Any] = Field(default_factory=dict)
    task_id: Optional[str] = Field(default=None, alias="taskId")
    context_id: Optional[str] = Field(default=None, alias="contextId")
    expires_at: Optional[float] = Field(default=None, alias="expiresAt")
    source: Literal["recovery"] = "recovery"


class A2AInterruptRecoveryResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: List[A2AInterruptRecoveryItemResponse] = Field(default_factory=list)


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
    interrupt_recovery: bool = Field(
        ...,
        alias="interruptRecovery",
        description="Whether the agent exposes Hub-consumed interrupt recovery support",
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
    invoke_metadata: A2AInvokeMetadataCapabilitiesResponse = Field(
        ...,
        alias="invokeMetadata",
        description="Hub-stable invoke metadata declaration and consumption contract.",
    )
    wire_contract: A2AWireContractCapabilitiesResponse = Field(
        ...,
        alias="wireContract",
        description=(
            "Declared wire-contract summary consumed by the hub for method "
            "availability preflight and diagnostics."
        ),
    )
    compatibility_profile: A2ACompatibilityProfileDiagnostic = Field(
        ...,
        alias="compatibilityProfile",
        description=(
            "Declared compatibility-profile extension summary consumed by the hub "
            "for compatibility diagnostics."
        ),
    )
    runtime_status: A2ARuntimeStatusContractResponse = Field(
        ...,
        alias="runtimeStatus",
        description="Canonical runtime status contract advertised by the hub.",
    )


__all__ = [
    "A2AExtensionInterruptRecoveryRequest",
    "A2AInvokeMetadataCapabilitiesResponse",
    "A2AInvokeMetadataFieldResponse",
    "A2AWireContractCapabilitiesResponse",
    "A2AWireContractConditionalMethodResponse",
    "A2AWireContractUnsupportedMethodErrorResponse",
    "A2AExtensionPromptAsyncRequest",
    "A2AExtensionSessionCommandRequest",
    "A2AExtensionSessionListFilters",
    "A2AExtensionSessionListQueryRequest",
    "A2AExtensionSessionMessagesQueryRequest",
    "A2AExtensionCapabilitiesResponse",
    "A2AInterruptRecoveryItemResponse",
    "A2AInterruptRecoveryResponse",
    "A2ASessionControlCapabilitiesResponse",
    "A2ASessionControlMethodResponse",
    "A2AModelDiscoveryRequest",
    "A2AExtensionPermissionReplyRequest",
    "A2AExtensionPermissionsReplyRequest",
    "A2ARuntimeStatusContractResponse",
    "A2AExtensionQueryPagination",
    "A2AExtensionQueryResponse",
    "A2AExtensionQueryRequest",
    "A2AExtensionQueryResult",
    "A2AExtensionElicitationReplyRequest",
    "A2AExtensionQuestionRejectRequest",
    "A2AExtensionQuestionReplyRequest",
    "A2AExtensionResponse",
]
