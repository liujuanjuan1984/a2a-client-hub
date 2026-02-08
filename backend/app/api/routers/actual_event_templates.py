"""API routes for managing actual event quick templates."""

from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.routing import StrictAPIRouter
from app.db.models.actual_event_quick_template import ActualEventQuickTemplate
from app.db.models.user import User
from app.handlers import actual_event_quick_templates as service
from app.handlers.actual_event_quick_templates import (
    ActualEventQuickTemplateAlreadyExistsError,
    ActualEventQuickTemplateNotFoundError,
)
from app.schemas.actual_event_quick_template import (
    ActualEventQuickTemplateBulkCreateRequest,
    ActualEventQuickTemplateCreate,
    ActualEventQuickTemplateListResponse,
    ActualEventQuickTemplateReorderRequest,
    ActualEventQuickTemplateResponse,
    ActualEventQuickTemplateUpdate,
)
from app.utils.timezone_util import utc_now

router = StrictAPIRouter(
    prefix="/actual-events/templates",
    tags=["actual-event-templates"],
    responses={404: {"description": "Template not found"}},
)
collection_router = StrictAPIRouter(tags=["actual-event-templates"])
resource_router = StrictAPIRouter(
    prefix="/{template_id:uuid}", tags=["actual-event-templates"]
)


def _serialize_template(
    template: ActualEventQuickTemplate,
) -> ActualEventQuickTemplateResponse:
    dimension = template.dimension
    persons_summary = list(getattr(template, "persons", []))
    person_ids = getattr(template, "person_ids", None)
    if person_ids is None:
        person_ids = [
            getattr(person, "id", None)
            for person in persons_summary
            if getattr(person, "id", None) is not None
        ]
    payload = {
        "id": template.id,
        "user_id": template.user_id,
        "title": template.title,
        "dimension_id": template.dimension_id,
        "dimension_name": getattr(dimension, "name", None),
        "dimension_color": getattr(dimension, "color", None),
        "person_ids": person_ids,
        "persons": persons_summary,
        "default_duration_minutes": template.default_duration_minutes,
        "position": template.position,
        "usage_count": template.usage_count or 0,
        "last_used_at": template.last_used_at,
        "created_at": template.created_at,
        "updated_at": template.updated_at,
    }
    return ActualEventQuickTemplateResponse.model_validate(payload)


@collection_router.get("/", response_model=ActualEventQuickTemplateListResponse)
async def list_actual_event_templates(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=100),
    order_by: str = Query(
        "position",
        pattern="^(position|usage|recent)$",
        description="Sorting strategy",
    ),
) -> ActualEventQuickTemplateListResponse:
    offset = (page - 1) * size
    items, total = await service.list_templates(
        db,
        user_id=current_user.id,
        limit=size,
        offset=offset,
        order_by=order_by,
    )
    serialized: List[ActualEventQuickTemplateResponse] = [
        _serialize_template(item) for item in items
    ]
    pages = (total + size - 1) // size if total else 0
    return ActualEventQuickTemplateListResponse(
        items=serialized,
        pagination={
            "page": page,
            "size": size,
            "total": total,
            "pages": pages,
        },
        meta={"order_by": order_by},
    )


@collection_router.post(
    "/",
    response_model=ActualEventQuickTemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_actual_event_template(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    template_in: ActualEventQuickTemplateCreate,
) -> ActualEventQuickTemplateResponse:
    try:
        template = await service.create_template(
            db,
            user_id=current_user.id,
            template_in=template_in,
        )
    except ActualEventQuickTemplateAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return _serialize_template(template)


@collection_router.post(
    "/bulk",
    response_model=ActualEventQuickTemplateListResponse,
    status_code=status.HTTP_201_CREATED,
)
async def bulk_create_actual_event_templates(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    request: ActualEventQuickTemplateBulkCreateRequest,
) -> ActualEventQuickTemplateListResponse:
    created: List[ActualEventQuickTemplateResponse] = []
    for item in request.items:
        try:
            template = await service.create_template(
                db, user_id=current_user.id, template_in=item
            )
            created.append(_serialize_template(template))
        except ActualEventQuickTemplateAlreadyExistsError:
            continue
    total = len(created)
    return ActualEventQuickTemplateListResponse(
        items=created,
        pagination={
            "page": 1,
            "size": total,
            "total": total,
            "pages": 1 if total else 0,
        },
        meta={"order_by": None},
    )


@resource_router.put(
    "",
    response_model=ActualEventQuickTemplateResponse,
)
async def update_actual_event_template(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    template_id: UUID,
    update_in: ActualEventQuickTemplateUpdate,
) -> ActualEventQuickTemplateResponse:
    try:
        template = await service.update_template(
            db,
            user_id=current_user.id,
            template_id=template_id,
            update_in=update_in,
        )
    except ActualEventQuickTemplateNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ActualEventQuickTemplateAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return _serialize_template(template)


@resource_router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_actual_event_template(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    template_id: UUID,
) -> None:
    try:
        await service.delete_template(
            db,
            user_id=current_user.id,
            template_id=template_id,
        )
    except ActualEventQuickTemplateNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@collection_router.patch("/reorder", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_actual_event_templates(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    request: ActualEventQuickTemplateReorderRequest,
) -> None:
    order_pairs = [(item.id, item.position) for item in request.items]
    try:
        await service.reorder_templates(
            db,
            user_id=current_user.id,
            order_pairs=order_pairs,
        )
    except ActualEventQuickTemplateNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@resource_router.post(
    "/bump-usage",
    response_model=ActualEventQuickTemplateResponse,
)
async def bump_actual_event_template_usage(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    template_id: UUID,
) -> ActualEventQuickTemplateResponse:
    try:
        template = await service.bump_template_usage(
            db,
            user_id=current_user.id,
            template_id=template_id,
            when=utc_now(),
        )
    except ActualEventQuickTemplateNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return _serialize_template(template)


router.include_router(collection_router)
router.include_router(resource_router)
