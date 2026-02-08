"""System notifications API routes."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.schemas.notifications import (
    MarkNotificationsReadRequest,
    MarkNotificationsReadResponse,
    SystemNotification,
    SystemNotificationListResponse,
    SystemNotificationUnreadCountResponse,
)
from app.services import notifications as notification_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


async def _resolve_system_session_id(
    db: AsyncSession, user_id: UUID, session_id: Optional[UUID]
) -> Optional[UUID]:
    """Use provided session_id or fallback to the user's system notification session."""

    if session_id:
        return session_id
    session = await notification_service.get_system_session(db, user_id=user_id)
    return session.id if session else None


def _build_notification_item(
    message,
    read_at,
) -> SystemNotification:
    metadata_source = message.message_metadata or {}
    if not isinstance(metadata_source, dict):
        metadata_source = {}

    title = metadata_source.get("title")
    payload = metadata_source.get("payload")
    if not isinstance(payload, dict):
        payload = {}

    return SystemNotification(
        id=message.id,
        session_id=message.session_id,
        title=title,
        body=message.content,
        severity=message.severity,
        metadata=payload,
        created_at=message.created_at,
        read_at=read_at,
        unread=read_at is None,
    )


@router.get("/system", response_model=SystemNotificationListResponse)
async def list_system_notifications(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    session_id: Optional[UUID] = Query(None),
    db: AsyncSession = Depends(deps.get_async_db),
    current_user=Depends(deps.get_current_user),
) -> SystemNotificationListResponse:
    resolved_session_id = await _resolve_system_session_id(
        db, current_user.id, session_id
    )

    if not resolved_session_id:
        return SystemNotificationListResponse(
            items=[],
            pagination={
                "page": page,
                "size": size,
                "total": 0,
                "pages": 0,
            },
            meta={"unread_count": 0},
        )

    offset = (page - 1) * size
    total, rows = await notification_service.list_system_notifications(
        db,
        user_id=current_user.id,
        session_id=resolved_session_id,
        limit=size,
        offset=offset,
    )
    unread_count = await notification_service.count_unread_system_notifications(
        db, user_id=current_user.id, session_id=resolved_session_id
    )

    items = [
        _build_notification_item(message=message, read_at=read_at)
        for message, read_at in rows
    ]

    pages = (total + size - 1) // size if size else 0

    return SystemNotificationListResponse(
        items=items,
        pagination={
            "page": page,
            "size": size,
            "total": total,
            "pages": pages,
        },
        meta={"unread_count": unread_count},
    )


@router.get(
    "/system/unread-count", response_model=SystemNotificationUnreadCountResponse
)
async def get_system_unread_count(
    session_id: Optional[UUID] = Query(None),
    db: AsyncSession = Depends(deps.get_async_db),
    current_user=Depends(deps.get_current_user),
) -> SystemNotificationUnreadCountResponse:
    resolved_session_id = await _resolve_system_session_id(
        db, current_user.id, session_id
    )
    if not resolved_session_id:
        return SystemNotificationUnreadCountResponse(unread_count=0)

    unread_count = await notification_service.count_unread_system_notifications(
        db, user_id=current_user.id, session_id=resolved_session_id
    )
    return SystemNotificationUnreadCountResponse(unread_count=unread_count)


@router.post(
    "/system/mark-read", response_model=MarkNotificationsReadResponse, status_code=200
)
async def mark_system_notifications_read(
    payload: MarkNotificationsReadRequest,
    db: AsyncSession = Depends(deps.get_async_db),
    current_user=Depends(deps.get_current_user),
) -> MarkNotificationsReadResponse:
    if payload.mark_all:
        target_session_id = await _resolve_system_session_id(
            db, current_user.id, payload.session_id
        )
        if not target_session_id:
            return MarkNotificationsReadResponse(updated=0, unread_count=0)
        updated = await notification_service.mark_all_notifications_read(
            db,
            user_id=current_user.id,
            session_id=target_session_id,
        )
    else:
        message_ids = payload.message_ids or []
        if not message_ids:
            raise HTTPException(status_code=400, detail="message_ids is required")
        updated = await notification_service.mark_notifications_read(
            db,
            user_id=current_user.id,
            message_ids=message_ids,
        )
        target_session_id = await _resolve_system_session_id(
            db, current_user.id, payload.session_id
        )

    unread_count = await notification_service.count_unread_system_notifications(
        db,
        user_id=current_user.id,
        session_id=target_session_id if target_session_id else None,
    )

    return MarkNotificationsReadResponse(updated=updated, unread_count=unread_count)
