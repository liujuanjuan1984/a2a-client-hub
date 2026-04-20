"""Schemas for the Hub Assistant."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class HubAssistantToolResponse(BaseModel):
    """One exposed tool on the Hub Assistant surface."""

    operation_id: str
    tool_name: str
    description: str
    confirmation_policy: str


class HubAssistantProfileResponse(BaseModel):
    """Static metadata for the Hub Assistant."""

    id: str
    name: str
    description: str
    runtime: str
    configured: bool
    resources: list[str]
    tools: list[HubAssistantToolResponse]


class HubAssistantRunRequest(BaseModel):
    """One user prompt routed to the Hub Assistant."""

    conversation_id: str = Field(alias="conversationId", min_length=1)
    message: str = Field(min_length=1)
    user_message_id: UUID | None = Field(alias="userMessageId", default=None)
    agent_message_id: UUID | None = Field(alias="agentMessageId", default=None)
    allow_write_tools: bool = False

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class HubAssistantInterruptDetails(BaseModel):
    """Display-safe details for a Hub Assistant permission interrupt."""

    permission: str | None = None
    patterns: list[str] = Field(default_factory=list)
    display_message: str | None = Field(alias="displayMessage", default=None)

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class HubAssistantInterrupt(BaseModel):
    """One interrupt emitted by the Hub Assistant."""

    request_id: str = Field(alias="requestId")
    type: Literal["permission"]
    phase: Literal["asked"]
    details: HubAssistantInterruptDetails

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class HubAssistantContinuation(BaseModel):
    """One accepted Hub Assistant continuation scheduled after an interrupt reply."""

    phase: Literal["running"]
    agent_message_id: UUID = Field(alias="agentMessageId")

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class HubAssistantRunResponse(BaseModel):
    """One completed or interrupted Hub Assistant run."""

    status: Literal["accepted", "completed", "interrupted"]
    answer: str | None
    exhausted: bool
    runtime: str
    resources: list[str]
    tools: list[str]
    write_tools_enabled: bool
    interrupt: HubAssistantInterrupt | None = None
    continuation: HubAssistantContinuation | None = None

    model_config = ConfigDict(extra="forbid")


class HubAssistantInterruptReplyRequest(BaseModel):
    """Permission interrupt reply payload for the Hub Assistant."""

    request_id: str = Field(alias="requestId", min_length=1)
    reply: Literal["once", "always", "reject"]
    agent_message_id: UUID | None = Field(alias="agentMessageId", default=None)

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class HubAssistantInterruptRecoveryRequest(BaseModel):
    """Conversation-scoped recovery request for persisted Hub Assistant interrupts."""

    conversation_id: str = Field(alias="conversationId", min_length=1)

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class HubAssistantRecoveredInterrupt(BaseModel):
    """One unresolved Hub Assistant permission interrupt restored from durable history."""

    request_id: str = Field(alias="requestId")
    session_id: str = Field(alias="sessionId")
    type: Literal["permission"]
    phase: Literal["asked"]
    details: HubAssistantInterruptDetails

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class HubAssistantInterruptRecoveryResponse(BaseModel):
    """Recovered unresolved Hub Assistant permission interrupts for one conversation."""

    items: list[HubAssistantRecoveredInterrupt]

    model_config = ConfigDict(extra="forbid")
