"""Schemas for the swival-driven self-management built-in agent."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SelfManagementBuiltInAgentToolResponse(BaseModel):
    """One exposed tool on the built-in self-management agent surface."""

    operation_id: str
    tool_name: str
    description: str
    confirmation_policy: str


class SelfManagementBuiltInAgentProfileResponse(BaseModel):
    """Static metadata for the swival-driven built-in self-management agent."""

    id: str
    name: str
    description: str
    runtime: str
    configured: bool
    resources: list[str]
    tools: list[SelfManagementBuiltInAgentToolResponse]


class SelfManagementBuiltInAgentRunRequest(BaseModel):
    """One user prompt routed to the built-in self-management agent."""

    conversation_id: str = Field(alias="conversationId", min_length=1)
    message: str = Field(min_length=1)
    user_message_id: UUID | None = Field(alias="userMessageId", default=None)
    agent_message_id: UUID | None = Field(alias="agentMessageId", default=None)
    allow_write_tools: bool = False

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class SelfManagementBuiltInAgentInterruptDetails(BaseModel):
    """Display-safe details for a built-in agent permission interrupt."""

    permission: str | None = None
    patterns: list[str] = Field(default_factory=list)
    display_message: str | None = Field(alias="displayMessage", default=None)

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class SelfManagementBuiltInAgentInterrupt(BaseModel):
    """One interrupt emitted by the built-in self-management agent."""

    request_id: str = Field(alias="requestId")
    type: Literal["permission"]
    phase: Literal["asked"]
    details: SelfManagementBuiltInAgentInterruptDetails

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class SelfManagementBuiltInAgentContinuation(BaseModel):
    """One accepted built-in continuation scheduled after an interrupt reply."""

    phase: Literal["running"]
    agent_message_id: UUID = Field(alias="agentMessageId")

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class SelfManagementBuiltInAgentRunResponse(BaseModel):
    """One completed or interrupted built-in self-management agent run."""

    status: Literal["accepted", "completed", "interrupted"]
    answer: str | None
    exhausted: bool
    runtime: str
    resources: list[str]
    tools: list[str]
    write_tools_enabled: bool
    interrupt: SelfManagementBuiltInAgentInterrupt | None = None
    continuation: SelfManagementBuiltInAgentContinuation | None = None

    model_config = ConfigDict(extra="forbid")


class SelfManagementBuiltInAgentInterruptReplyRequest(BaseModel):
    """Permission interrupt reply payload for the built-in self-management agent."""

    request_id: str = Field(alias="requestId", min_length=1)
    reply: Literal["once", "always", "reject"]
    agent_message_id: UUID | None = Field(alias="agentMessageId", default=None)

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class SelfManagementBuiltInAgentInterruptRecoveryRequest(BaseModel):
    """Conversation-scoped recovery request for persisted built-in interrupts."""

    conversation_id: str = Field(alias="conversationId", min_length=1)

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class SelfManagementBuiltInAgentRecoveredInterrupt(BaseModel):
    """One unresolved built-in permission interrupt restored from durable history."""

    request_id: str = Field(alias="requestId")
    session_id: str = Field(alias="sessionId")
    type: Literal["permission"]
    phase: Literal["asked"]
    details: SelfManagementBuiltInAgentInterruptDetails

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class SelfManagementBuiltInAgentInterruptRecoveryResponse(BaseModel):
    """Recovered unresolved built-in permission interrupts for one conversation."""

    items: list[SelfManagementBuiltInAgentRecoveredInterrupt]

    model_config = ConfigDict(extra="forbid")
