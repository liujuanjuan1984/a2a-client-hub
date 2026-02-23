"""Schemas for shortcut quick-prompt APIs."""

from __future__ import annotations

from typing import Any, ClassVar, List
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.schemas.pagination import ListResponse, Pagination

_MAX_TITLE_LENGTH: ClassVar[int] = 120
_MAX_PROMPT_LENGTH: ClassVar[int] = 4000


def _strip_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


class ShortcutCreateRequest(BaseModel):
    """Payload for creating a shortcut."""

    title: str = Field(min_length=1, max_length=_MAX_TITLE_LENGTH)
    prompt: str = Field(min_length=1, max_length=_MAX_PROMPT_LENGTH)
    order: int | None = Field(default=None, ge=0)
    agent_id: UUID | None = Field(
        default=None, description="If set, binds this shortcut to a specific agent."
    )

    @model_validator(mode="after")
    def _normalize_fields(self: "ShortcutCreateRequest") -> "ShortcutCreateRequest":
        normalized_title = _strip_text(self.title)
        normalized_prompt = _strip_text(self.prompt)
        if normalized_title is None or normalized_prompt is None:
            raise ValueError("title and prompt cannot be empty")
        self.title = normalized_title
        self.prompt = normalized_prompt
        return self


class ShortcutUpdateRequest(BaseModel):
    """Payload for updating a shortcut."""

    title: str | None = Field(default=None, min_length=1, max_length=_MAX_TITLE_LENGTH)
    prompt: str | None = Field(
        default=None, min_length=1, max_length=_MAX_PROMPT_LENGTH
    )
    order: int | None = Field(default=None, ge=0)
    agent_id: UUID | None = Field(
        default=None, description="If set, binds this shortcut to a specific agent."
    )
    clear_agent: bool = Field(
        default=False,
        description="If True, removes the agent binding to make it general.",
    )

    @model_validator(mode="after")
    def _normalize_fields(self: "ShortcutUpdateRequest") -> "ShortcutUpdateRequest":
        self.title = _strip_text(self.title)
        self.prompt = _strip_text(self.prompt)

        if (
            self.title is None
            and self.prompt is None
            and self.order is None
            and self.agent_id is None
            and not self.clear_agent
        ):
            raise ValueError("at least one field must be provided")
        return self


class ShortcutResponse(BaseModel):
    id: UUID
    title: str = Field(max_length=120)
    prompt: str = Field(max_length=4000)
    is_default: bool = Field(default=False)
    order: int
    agent_id: UUID | None = Field(default=None)


class ShortcutListMeta(BaseModel):
    """Additional list metadata for shortcuts endpoint."""


class ShortcutListPagination(Pagination):
    """Pagination metadata for shortcut lists."""


class ShortcutListResponse(ListResponse[ShortcutResponse, ShortcutListMeta]):
    items: List[ShortcutResponse]
    pagination: ShortcutListPagination
    meta: ShortcutListMeta


__all__ = [
    "ShortcutCreateRequest",
    "ShortcutListMeta",
    "ShortcutListPagination",
    "ShortcutListResponse",
    "ShortcutResponse",
    "ShortcutUpdateRequest",
]
