"""Pydantic schemas for A2A invocation."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class A2AAgentInvokeRequest(BaseModel):
    query: str = Field(..., min_length=1, description="User query to forward")
    conversation_id: Optional[str] = Field(
        default=None,
        alias="conversationId",
        description="Optional conversation identifier for server-side history tracking.",
    )
    context_id: Optional[str] = Field(
        default=None,
        alias="contextId",
        description="Optional A2A context identifier",
    )
    user_message_id: Optional[str] = Field(
        default=None,
        alias="userMessageId",
        description="Optional client-stable user message identifier",
    )
    client_agent_message_id: Optional[str] = Field(
        default=None,
        alias="clientAgentMessageId",
        description="Optional client-side placeholder agent message identifier",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Optional A2A metadata forwarded with the message",
    )

    model_config = {"populate_by_name": True}


class A2AAgentInvokeResponse(BaseModel):
    success: bool
    content: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    agent_name: Optional[str] = None
    agent_url: Optional[str] = None


__all__ = ["A2AAgentInvokeRequest", "A2AAgentInvokeResponse"]
