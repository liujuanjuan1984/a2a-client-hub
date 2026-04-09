"""Schemas for the swival-driven self-management built-in agent."""

from __future__ import annotations

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

    message: str = Field(min_length=1)


class SelfManagementBuiltInAgentRunResponse(BaseModel):
    """One completed built-in self-management agent run."""

    answer: str | None
    exhausted: bool
    runtime: str
    resources: list[str]
    tools: list[str]

    model_config = ConfigDict(extra="forbid")
