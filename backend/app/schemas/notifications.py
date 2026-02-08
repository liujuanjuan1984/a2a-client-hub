"""Schemas for system notification APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.schemas.pagination import ListResponse, Pagination


class SystemNotification(BaseModel):
    """Single system notification item."""

    id: UUID
    session_id: UUID
    title: Optional[str] = None
    body: str
    severity: str = Field(default="info")
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    read_at: Optional[datetime] = None
    unread: bool


class SystemNotificationPagination(Pagination):
    """Pagination metadata for system notifications."""


class SystemNotificationListMeta(BaseModel):
    """Additional list metadata for system notifications."""

    unread_count: int


class SystemNotificationListResponse(
    ListResponse[SystemNotification, SystemNotificationListMeta]
):
    """Paginated system notification response."""

    items: list[SystemNotification]
    pagination: SystemNotificationPagination
    meta: SystemNotificationListMeta


class SystemNotificationUnreadCountResponse(BaseModel):
    """Unread counter response."""

    unread_count: int


class MarkNotificationsReadRequest(BaseModel):
    """Request payload for marking notifications as read."""

    message_ids: Optional[list[UUID]] = None
    mark_all: bool = False
    session_id: Optional[UUID] = None

    @model_validator(mode="after")
    def validate_payload(self) -> "MarkNotificationsReadRequest":
        if self.mark_all:
            return self
        if not self.message_ids:
            raise ValueError("message_ids must be provided when mark_all is false")
        return self


class MarkNotificationsReadResponse(BaseModel):
    """Result of a mark-read operation."""

    updated: int
    unread_count: int
