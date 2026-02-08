"""Pydantic schemas for multi-agent operations."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class NoteSummaryRequest(BaseModel):
    """Incoming request to trigger a note summary task."""

    query: str = Field(
        ..., min_length=1, description="User's query for note summarization"
    )
    limit: int = Field(
        10, ge=1, le=50, description="Maximum number of notes to retrieve"
    )
    keyword: Optional[str] = Field(
        None,
        description="Optional keyword for filtering notes (default: inferred from query)",
    )


class NoteSummaryResponse(BaseModel):
    """Aggregated response returned after multi-agent execution."""

    task_id: UUID
    summary: str
    note_count: int
    notes: List[Dict[str, Any]]


class AgentInvocationRequest(BaseModel):
    """Request payload for invoking a specialist agent."""

    agent_name: str = Field(..., description="Name of the specialist agent to invoke")
    instruction: Optional[str] = Field(
        None, description="Optional instruction describing the current task objective"
    )
    tool_name: Optional[str] = Field(
        None, description="Optional specific tool name (default: agent auto-selects)"
    )
    tool_args: Optional[Dict[str, Any]] = Field(
        None, description="Parameters to pass to the tool (JSON object)"
    )


class AgentInvocationResponse(BaseModel):
    """Response returned after invoking a specialist agent."""

    task_id: UUID
    agent_name: str
    tool_name: str
    tool_args: Dict[str, Any]
    result: Dict[str, Any]


__all__ = [
    "NoteSummaryRequest",
    "NoteSummaryResponse",
    "AgentInvocationRequest",
    "AgentInvocationResponse",
]
