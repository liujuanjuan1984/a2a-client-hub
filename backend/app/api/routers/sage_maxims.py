"""API endpoints for Sage Maxims feature."""

from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.routing import StrictAPIRouter
from app.db.models.user import User
from app.handlers.sage_maxims import (
    SageMaximNotFoundError,
    SageMaximReactionError,
    create_sage_maxim,
    list_sage_maxims,
    remove_reaction,
    set_reaction,
)
from app.schemas.sage_maxim import (
    SageMaximCreate,
    SageMaximListResponse,
    SageMaximReactionRequest,
    SageMaximResponse,
)

router = StrictAPIRouter(
    prefix="/sage-maxims",
    tags=["sage_maxims"],
    responses={404: {"description": "Maxim not found"}},
)


def _to_response(model, viewer_reaction: Optional[str]) -> SageMaximResponse:
    return SageMaximResponse(
        id=model.id,
        content=model.content,
        language=model.language,
        like_count=model.like_count,
        dislike_count=model.dislike_count,
        created_at=model.created_at,
        updated_at=model.updated_at,
        author={
            "id": model.user_id,
            "name": getattr(model.author, "name", "Unknown"),
        },
        viewer_reaction=viewer_reaction,
    )


@router.get("/", response_model=SageMaximListResponse)
async def get_sage_maxims(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    sort: str = Query(
        "random",
        description="Sort mode: random | latest | top",
    ),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=50),
) -> SageMaximListResponse:
    """List sage maxims with the viewer's reaction state."""

    if sort not in {"random", "latest", "top"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported sort mode"
        )

    offset = (page - 1) * size
    items, total, reaction_map, page_size = await list_sage_maxims(
        db,
        viewer_id=current_user.id,
        sort=sort,
        limit=size,
        offset=offset,
    )
    responses = [_to_response(item, reaction_map.get(item.id)) for item in items]
    pages = (total + page_size - 1) // page_size if page_size else 0
    return SageMaximListResponse(
        items=responses,
        pagination={
            "page": page,
            "size": page_size,
            "total": total,
            "pages": pages,
        },
        meta={"sort": sort},
    )


@router.post(
    "/",
    response_model=SageMaximResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_sage_maxim_entry(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    payload: SageMaximCreate,
) -> SageMaximResponse:
    """Create a new sage maxim."""

    maxim = await create_sage_maxim(
        db,
        author=current_user,
        content=payload.content,
        language=payload.language,
    )
    return _to_response(maxim, viewer_reaction=None)


@router.post(
    "/{maxim_id}/reaction",
    response_model=SageMaximResponse,
)
async def react_to_sage_maxim(
    *,
    maxim_id: UUID,
    body: SageMaximReactionRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> SageMaximResponse:
    """Add or update the viewer's reaction for the target maxim."""

    try:
        maxim = await set_reaction(
            db,
            maxim_id=maxim_id,
            user_id=current_user.id,
            reaction_type=body.action,
        )
    except SageMaximNotFoundError as exc:  # pragma: no cover - simple mapping
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except SageMaximReactionError as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return _to_response(maxim, viewer_reaction=body.action)


@router.delete(
    "/{maxim_id}/reaction",
    response_model=SageMaximResponse,
)
async def delete_sage_maxim_reaction(
    *,
    maxim_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> SageMaximResponse:
    """Remove the viewer's reaction from a maxim."""

    try:
        maxim = await remove_reaction(
            db,
            maxim_id=maxim_id,
            user_id=current_user.id,
        )
    except SageMaximNotFoundError as exc:  # pragma: no cover - simple mapping
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    return _to_response(maxim, viewer_reaction=None)
