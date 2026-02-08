"""Pydantic schemas for agent registry endpoints."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from app.schemas.pagination import ListResponse, Pagination


class ToolArgumentSummary(BaseModel):
    name: str
    type_hint: str
    required: bool
    description_zh: str
    description_en: str
    default: Optional[str] = None


class ToolGuideSummary(BaseModel):
    name: str
    purpose_zh: str
    purpose_en: str
    arguments: List[ToolArgumentSummary] = Field(default_factory=list)
    example: str
    triggers_zh: List[str] = Field(default_factory=list)
    triggers_en: List[str] = Field(default_factory=list)


class AgentProfileSummary(BaseModel):
    name: str = Field(..., description="Agent identifier")
    description: str = Field(..., description="Agent description")
    tools: List[str] = Field(
        default_factory=list, description="Explicitly assigned tools"
    )
    allow_unassigned_tools: bool = Field(
        False, description="Whether the agent can access unassigned tools"
    )
    system_prompt_en: Optional[str] = Field(
        None, description="Default English system prompt"
    )
    prompt_version: str = Field(
        "unknown",
        description="Version of the prompt template used to build the system prompt",
    )
    tool_guides: List[ToolGuideSummary] = Field(
        default_factory=list, description="Structured documentation for each tool"
    )


class AgentRegistryPagination(Pagination):
    """Pagination metadata for agent registry listings."""


class AgentRegistryListMeta(BaseModel):
    """Additional list metadata for agent registry listings."""

    source: Optional[str] = Field(None, description="Registry source label")


class AgentRegistryListResponse(
    ListResponse[AgentProfileSummary, AgentRegistryListMeta]
):
    """Schema for agent registry list response."""

    items: List[AgentProfileSummary]
    pagination: AgentRegistryPagination
    meta: AgentRegistryListMeta


__all__ = [
    "AgentProfileSummary",
    "ToolGuideSummary",
    "ToolArgumentSummary",
    "AgentRegistryPagination",
    "AgentRegistryListMeta",
    "AgentRegistryListResponse",
]
