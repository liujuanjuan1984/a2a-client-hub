"""Pydantic schemas for A2A invocation."""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from app.features.working_directory import merge_working_directory_metadata


class A2AAgentInvokeSessionBinding(BaseModel):
    provider: Optional[str] = Field(
        default=None,
        description="Optional upstream provider hint for a bound external session.",
    )
    external_session_id: Optional[str] = Field(
        default=None,
        alias="externalSessionId",
        description="Optional upstream external session identifier.",
    )

    model_config = {"populate_by_name": True}


class A2AAgentInvokeSessionControl(BaseModel):
    intent: Literal["append", "preempt"] = Field(
        ...,
        description="Stable hub-managed send intent for active session control.",
    )

    model_config = {"populate_by_name": True}


class A2AAgentInvokeSessionControlResult(BaseModel):
    intent: Literal["append", "preempt"] = Field(
        ...,
        description="Resolved session-control intent handled by the hub.",
    )
    status: Literal[
        "accepted",
        "completed",
        "no_inflight",
        "unavailable",
        "failed",
    ] = Field(
        ...,
        description="Outcome of the resolved session-control operation.",
    )
    session_id: Optional[str] = Field(
        default=None,
        alias="sessionId",
        description="Resolved upstream session identifier after session control.",
    )

    model_config = {"populate_by_name": True}


class A2AAgentInvokeRequest(BaseModel):
    query: str = Field(
        default="",
        description="User query to forward. May be empty for preempt-only session control.",
    )
    conversation_id: Optional[str] = Field(
        default=None,
        alias="conversationId",
        description="Optional conversation identifier for server-side history tracking.",
    )
    user_message_id: Optional[str] = Field(
        default=None,
        alias="userMessageId",
        description="Optional client-stable user message identifier",
    )
    agent_message_id: Optional[str] = Field(
        default=None,
        alias="agentMessageId",
        description="Optional client-stable agent message identifier",
    )
    resume_from_sequence: Optional[int] = Field(
        default=None,
        alias="resumeFromSequence",
        description="Optional sequence number to resume streaming from after a disconnect",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Optional A2A metadata forwarded with the message",
    )
    working_directory: Optional[str] = Field(
        default=None,
        alias="workingDirectory",
        description="Optional hub-stable working directory for provider adaptation.",
    )
    session_binding: Optional[A2AAgentInvokeSessionBinding] = Field(
        default=None,
        alias="sessionBinding",
        description="Optional hub-internal session binding intent. Not forwarded upstream as-is.",
    )
    session_control: Optional[A2AAgentInvokeSessionControl] = Field(
        default=None,
        alias="sessionControl",
        description="Optional hub-managed send intent for active session control.",
    )

    model_config = {"populate_by_name": True}

    @model_validator(mode="before")
    @classmethod
    def reject_client_owned_context_id(cls, value: Any) -> Any:
        if isinstance(value, dict) and ("contextId" in value or "context_id" in value):
            raise ValueError("contextId is server-managed and must not be provided")
        return value

    @model_validator(mode="after")
    def normalize_working_directory(self) -> "A2AAgentInvokeRequest":
        if self.working_directory is None:
            return self
        self.metadata = merge_working_directory_metadata(
            self.metadata,
            self.working_directory,
        )
        self.working_directory = None
        return self

    @model_validator(mode="after")
    def validate_query_for_session_control(self) -> "A2AAgentInvokeRequest":
        if (
            self.session_control is not None
            and self.session_control.intent == "preempt"
        ):
            return self
        if not self.query.strip():
            raise ValueError("query must not be empty")
        return self


class A2AAgentInvokeResponse(BaseModel):
    success: bool
    content: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    source: Optional[str] = None
    jsonrpc_code: Optional[int] = None
    missing_params: Optional[list[dict[str, Any]]] = None
    upstream_error: Optional[Dict[str, Any]] = None
    agent_name: Optional[str] = None
    agent_url: Optional[str] = None
    session_control: Optional[A2AAgentInvokeSessionControlResult] = Field(
        default=None,
        alias="sessionControl",
    )


__all__ = [
    "A2AAgentInvokeRequest",
    "A2AAgentInvokeResponse",
    "A2AAgentInvokeSessionBinding",
    "A2AAgentInvokeSessionControl",
    "A2AAgentInvokeSessionControlResult",
]
