"""Endpoints for exposing Cardbox conversation data to clients."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.routing import StrictAPIRouter
from app.cardbox.async_bridge import run_cardbox_io
from app.cardbox.context_service import context_box_manager
from app.cardbox.service import cardbox_service
from app.core.logging import get_logger
from app.db.models.user import User
from app.handlers import agent_session as session_handler
from app.handlers.agent_session import SessionHandlerError
from app.schemas.cardbox import (
    CardboxSessionListResponse,
    ContextBoxCreateRequest,
    ContextBoxCreateResponse,
    ContextBoxItem,
    ContextBoxListResponse,
    ContextBoxPreviewResponse,
    ContextBoxSummary,
)

router = StrictAPIRouter(tags=["cardbox"])
logger = get_logger(__name__)


@router.get(
    "/cardbox/session/{session_id}/messages", response_model=CardboxSessionListResponse
)
async def list_session_messages(
    session_id: UUID,
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(20, ge=1, le=100, description="Page size"),
    user_id: Optional[UUID] = Query(
        None, description="Target user; defaults to current user"
    ),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """Return recent chat messages mirrored in Cardbox."""

    target_user = _resolve_user(user_id, current_user)

    try:
        session = await session_handler.get_session(
            db,
            session_id=session_id,
            user_id=target_user,
        )
    except SessionHandlerError as exc:  # pragma: no cover - defensive logging
        logger.exception(
            "Failed to load session for cardbox messages",
            extra={"session_id": str(session_id), "user_id": str(target_user)},
        )
        raise HTTPException(
            status_code=500, detail="Failed to load Cardbox messages"
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception(
            "Unexpected error while loading cardbox session",
            extra={"session_id": str(session_id), "user_id": str(target_user)},
        )
        raise HTTPException(
            status_code=500, detail="Failed to load Cardbox messages"
        ) from exc

    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        # For session messages, we often want "recent" first, but list_session_messages
        # might have internal logic. We adapt it to page/size.
        offset = (page - 1) * size
        messages = await run_cardbox_io(
            cardbox_service.list_session_messages,
            user_id=target_user,
            session_id=session_id,
            limit=None,  # Load all and slice for now if underlying service doesn't support offset
            include_types=["message"],
        )
        total = len(messages)
        sliced = messages[offset : offset + size]
        pages = (total + size - 1) // size if size else 0

        return CardboxSessionListResponse(
            items=sliced,
            pagination={
                "page": page,
                "size": size,
                "total": total,
                "pages": pages,
            },
            meta={},
        )
    except Exception as exc:  # pragma: no cover
        logger.exception(
            "Cardbox message retrieval failed",
            extra={"session_id": str(session_id), "user_id": str(target_user)},
        )
        raise HTTPException(
            status_code=500, detail="Failed to load Cardbox messages"
        ) from exc


@router.get(
    "/cardbox/session/{session_id}/tools", response_model=CardboxSessionListResponse
)
async def list_session_tool_results(
    session_id: UUID,
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(20, ge=1, le=100, description="Page size"),
    user_id: Optional[UUID] = Query(None),
    success: Optional[bool] = Query(None),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """Return recent tool result cards for the session."""

    target_user = _resolve_user(user_id, current_user)
    try:
        session = await session_handler.get_session(
            db,
            session_id=session_id,
            user_id=target_user,
        )
    except SessionHandlerError as exc:  # pragma: no cover - defensive logging
        logger.exception(
            "Failed to load session for cardbox tools",
            extra={"session_id": str(session_id), "user_id": str(target_user)},
        )
        raise HTTPException(
            status_code=500, detail="Failed to load Cardbox tools"
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception(
            "Unexpected error while loading cardbox session",
            extra={"session_id": str(session_id), "user_id": str(target_user)},
        )
        raise HTTPException(
            status_code=500, detail="Failed to load Cardbox tools"
        ) from exc

    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    cards = await run_cardbox_io(
        cardbox_service.list_session_messages,
        user_id=target_user,
        session_id=session_id,
        limit=None,
        include_types=["tool_result"],
    )
    if success is not None:
        cards = [card for card in cards if card["metadata"].get("success") == success]

    total = len(cards)
    offset = (page - 1) * size
    sliced = cards[offset : offset + size]
    pages = (total + size - 1) // size if size else 0

    return CardboxSessionListResponse(
        items=sliced,
        pagination={
            "page": page,
            "size": size,
            "total": total,
            "pages": pages,
        },
        meta={},
    )


def _record_to_summary(record) -> ContextBoxSummary:
    return ContextBoxSummary(
        box_id=record.box_id,
        name=record.name,
        module=record.module,
        display_name=record.display_name,
        card_count=record.card_count,
        updated_at=record.updated_at,
        metadata=record.manifest_metadata,
    )


def _card_to_item(card) -> ContextBoxItem:
    text = ""
    try:
        text = card.text()
    except Exception:  # pragma: no cover - defensive
        if isinstance(getattr(card, "content", None), str):
            text = card.content
        elif getattr(card, "content", None) and hasattr(card.content, "text"):
            text = card.content.text
    metadata = getattr(card, "metadata", {}) or {}
    return ContextBoxItem(
        card_id=str(getattr(card, "card_id", "")),
        content=text or "",
        metadata=metadata,
    )


@router.get("/cardbox/context/list", response_model=ContextBoxListResponse)
async def list_context_boxes(current_user: User = Depends(get_current_user)):
    records = await run_cardbox_io(
        context_box_manager.list_context_boxes, user_id=current_user.id
    )
    summaries = [_record_to_summary(record) for record in records]
    total = len(summaries)
    return ContextBoxListResponse(
        items=summaries,
        pagination={
            "page": 1,
            "size": total,
            "total": total,
            "pages": 1 if total else 0,
        },
        meta={"source": "cardbox"},
    )


@router.post(
    "/cardbox/context/create",
    response_model=ContextBoxCreateResponse,
    status_code=201,
)
async def create_context_box(
    payload: ContextBoxCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    try:
        record = await context_box_manager.create_context_box(
            db,
            user_id=current_user.id,
            module=payload.module,
            filters=payload.filters,
            display_name=payload.name,
            overwrite=payload.overwrite,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("Failed to create context CardBox")
        raise HTTPException(
            status_code=500, detail="Failed to create context CardBox"
        ) from exc
    return ContextBoxCreateResponse(box=_record_to_summary(record))


@router.delete("/cardbox/context/{box_id}")
async def delete_context_box(
    box_id: int,
    current_user: User = Depends(get_current_user),
):
    success = await run_cardbox_io(
        context_box_manager.delete_box_by_id,
        user_id=current_user.id,
        box_id=box_id,
    )
    if not success:
        raise HTTPException(status_code=404, detail="CardBox not found")
    return {"status": "ok"}


@router.get(
    "/cardbox/context/{box_id}/items",
    response_model=ContextBoxPreviewResponse,
)
async def preview_context_box(
    box_id: int,
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(20, ge=1, le=100, description="Page size"),
    current_user: User = Depends(get_current_user),
):
    record = await run_cardbox_io(
        context_box_manager.get_record_by_id,
        user_id=current_user.id,
        box_id=box_id,
    )
    if record is None:
        raise HTTPException(status_code=404, detail="CardBox not found")

    offset = (page - 1) * size
    limit = size

    # We want to know total count if possible, or at least enough to know if there's a next page
    cards = await run_cardbox_io(
        context_box_manager.load_box_cards,
        user_id=current_user.id,
        box_name=record.name,
        skip_manifest=True,
        limit=None,  # Load all for now to get total count
    )
    total = len(cards)
    sliced = cards[offset : offset + limit]
    items = [_card_to_item(card) for card in sliced]
    pages = (total + size - 1) // size if size else 0

    return ContextBoxPreviewResponse(
        box=_record_to_summary(record),
        items=items,
        pagination={
            "page": page,
            "size": size,
            "total": total,
            "pages": pages,
        },
        meta={},
    )


def _resolve_user(
    requested: Optional[UUID], current_user: Optional[User] = None
) -> UUID:
    if requested is None:
        if current_user is None:
            raise HTTPException(status_code=401, detail="Unauthorized")
        return current_user.id

    if current_user and requested != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return requested
