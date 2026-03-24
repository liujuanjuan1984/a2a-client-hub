"""Pydantic schemas for A2A invocation."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, model_validator


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


class A2AAgentInvokeRequest(BaseModel):
    query: str = Field(..., min_length=1, description="User query to forward")
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
    session_binding: Optional[A2AAgentInvokeSessionBinding] = Field(
        default=None,
        alias="sessionBinding",
        description="Optional hub-internal session binding intent. Not forwarded upstream as-is.",
    )

    model_config = {"populate_by_name": True}

    @model_validator(mode="before")
    @classmethod
    def reject_client_owned_context_id(cls, value: Any) -> Any:
        if isinstance(value, dict) and ("contextId" in value or "context_id" in value):
            raise ValueError("contextId is server-managed and must not be provided")
        return value


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


__all__ = [
    "A2AAgentInvokeRequest",
    "A2AAgentInvokeResponse",
    "A2AAgentInvokeSessionBinding",
]
