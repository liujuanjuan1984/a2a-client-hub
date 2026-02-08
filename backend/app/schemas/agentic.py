from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class AgenticTextResult(BaseModel):
    """
    Agent-friendly response shape optimized for direct LLM consumption.

    `content` is intentionally narrative-first text, while `metadata`/`params`
    provide structured context for grounding and tool-chaining.
    """

    module: str = Field(..., description="Source module (e.g. timelog/notes/planning).")
    content: str = Field(..., description="Narrative-first text content.")
    content_type: str = Field(
        default="text/plain", description="MIME type of the content."
    )
    params: Optional[Dict[str, Any]] = Field(
        default=None, description="Echo of request parameters (structured)."
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None, description="Optional structured statistics/extra info."
    )
