"""
Vision API Router

This module contains all API endpoints for managing visions.
Routers call into the service layer and map business exceptions to HTTP errors.
"""

from types import SimpleNamespace
from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.routing import StrictAPIRouter
from app.core.config import settings
from app.db.models.user import User
from app.handlers import visions as vision_service
from app.handlers.visions import (
    InvalidVisionExperienceRateError,
    InvalidVisionStatusError,
    VisionAlreadyExistsError,
    VisionNotFoundError,
    VisionNotReadyForHarvestError,
)
from app.schemas.task import TaskResponse
from app.schemas.vision import (
    VisionCreate,
    VisionExperienceRateBulkUpdateRequest,
    VisionExperienceRateBulkUpdateResponse,
    VisionExperienceUpdate,
    VisionHarvestRequest,
    VisionListResponse,
    VisionResponse,
    VisionStatsResponse,
    VisionUpdate,
    VisionWithTasks,
)
from app.serialization.entities import build_vision_response

router = StrictAPIRouter(
    prefix="/visions",
    tags=["visions"],
    responses={404: {"description": "Not found"}},
    dependencies=[Depends(get_current_user)],
)
collection_router = StrictAPIRouter(tags=["visions"])
resource_router = StrictAPIRouter(prefix="/{vision_id:uuid}", tags=["visions"])


@collection_router.get("/", response_model=VisionListResponse)
async def get_visions(
    page: int = 1,
    size: int = 100,
    status_filter: Optional[str] = None,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> VisionListResponse:
    """
    Get all visions

    Args:
        page: Page number (1-indexed)
        size: Number of records per page
        status_filter: Filter by vision status ('active', 'archived', 'fruit')
        db: Database session

    Returns:
        Paginated list of visions
    """
    try:
        offset = (page - 1) * size
        visions, total = await vision_service.list_visions_with_total(
            db,
            user_id=current_user.id,
            skip=offset,
            limit=size,
            status_filter=status_filter,
        )
        items = [build_vision_response(vision) for vision in visions]
        pages = (total + size - 1) // size if size else 0
        return VisionListResponse(
            items=items,
            pagination={
                "page": page,
                "size": size,
                "total": total,
                "pages": pages,
            },
            meta={
                "status_filter": status_filter,
            },
        )
    except InvalidVisionStatusError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException as exc:
        raise exc
    except Exception:
        if settings.debug:
            raise
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@resource_router.get("", response_model=VisionResponse)
async def get_vision(
    vision_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> VisionResponse:
    """
    Get a specific vision by ID

    Args:
        vision_id: Vision ID
        db: Database session
        current_user: Current authenticated user

    Returns:
        Vision details
    """
    try:
        vision = await vision_service.get_vision(
            db, user_id=current_user.id, vision_id=vision_id
        )
        if vision is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Vision not found"
            )
        return build_vision_response(vision)
    except HTTPException as exc:
        raise exc
    except Exception:
        if settings.debug:
            raise
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@resource_router.get("/with-tasks", response_model=VisionWithTasks)
async def get_vision_with_tasks(
    vision_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> VisionWithTasks:
    """
    Get a vision with all its tasks

    Args:
        vision_id: Vision ID
        db: Database session

    Returns:
        Vision with tasks
    """
    try:
        vision_payload = await vision_service.get_vision_with_tasks(
            db,
            user_id=current_user.id,
            vision_id=vision_id,
        )
        if vision_payload is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Vision not found"
            )
        if isinstance(vision_payload, VisionWithTasks):
            return vision_payload

        tasks_data = []
        base_source: object
        if isinstance(vision_payload, dict):
            tasks_data = vision_payload.get("tasks", []) or []
            base_source = SimpleNamespace(
                **{k: v for k, v in vision_payload.items() if k != "tasks"}
            )
        else:
            base_source = vision_payload
            tasks_data = getattr(vision_payload, "tasks", []) or []

        base_response = build_vision_response(base_source)
        task_models = [
            (
                task
                if isinstance(task, TaskResponse)
                else TaskResponse.model_validate(task)
            )
            for task in tasks_data
        ]

        return VisionWithTasks(
            **base_response.model_dump(mode="python"),
            tasks=task_models,
        )
    except HTTPException as exc:
        raise exc
    except Exception:
        if settings.debug:
            raise
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@collection_router.post(
    "/", response_model=VisionResponse, status_code=status.HTTP_201_CREATED
)
async def create_vision(
    vision_data: VisionCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> VisionResponse:
    """
    Create a new vision

    Args:
        vision_data: Vision creation data
        db: Database session

    Returns:
        Created vision
    """
    try:
        vision = await vision_service.create_vision(
            db,
            user_id=current_user.id,
            vision_in=vision_data,
        )
        return build_vision_response(vision)
    except VisionAlreadyExistsError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except VisionNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException as exc:
        raise exc
    except Exception:
        if settings.debug:
            raise
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@collection_router.put(
    "/experience-rates", response_model=VisionExperienceRateBulkUpdateResponse
)
async def bulk_update_experience_rates(
    request: VisionExperienceRateBulkUpdateRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> VisionExperienceRateBulkUpdateResponse:
    """
    Bulk update experience rates for multiple visions.
    """
    try:
        updated = await vision_service.bulk_update_vision_experience_rates(
            db,
            user_id=current_user.id,
            updates=request.items,
        )
        return VisionExperienceRateBulkUpdateResponse(
            items=[build_vision_response(v) for v in updated]
        )
    except VisionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except InvalidVisionExperienceRateError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except HTTPException as exc:
        raise exc
    except Exception:
        if settings.debug:
            raise
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@resource_router.put("", response_model=VisionResponse)
async def update_vision(
    vision_id: UUID,
    vision_data: VisionUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> VisionResponse:
    """
    Update a vision

    Args:
        vision_id: Vision ID
        vision_data: Vision update data
        db: Database session

    Returns:
        Updated vision
    """
    try:
        vision = await vision_service.update_vision(
            db,
            user_id=current_user.id,
            vision_id=vision_id,
            update_in=vision_data,
        )
        if vision is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Vision not found"
            )
        return build_vision_response(vision)
    except VisionAlreadyExistsError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException as exc:
        raise exc
    except Exception:
        if settings.debug:
            raise
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@resource_router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vision(
    vision_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete a vision."""
    try:
        success = await vision_service.delete_vision(
            db,
            user_id=current_user.id,
            vision_id=vision_id,
            hard_delete=False,
        )
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Vision not found"
            )
    except HTTPException as exc:
        raise exc
    except Exception:
        if settings.debug:
            raise
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@resource_router.post("/add-experience", response_model=VisionResponse)
async def add_experience_to_vision(
    vision_id: UUID,
    experience_data: VisionExperienceUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> VisionResponse:
    """
    Add experience points to a vision

    Args:
        vision_id: Vision ID
        experience_data: Experience points to add
        db: Database session

    Returns:
        Updated vision with new stage if evolved
    """
    try:
        vision = await vision_service.add_experience_to_vision(
            db,
            user_id=current_user.id,
            vision_id=vision_id,
            experience_data=experience_data,
        )
        if vision is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Vision not found"
            )
        return build_vision_response(vision)
    except InvalidVisionStatusError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException as exc:
        raise exc
    except Exception:
        if settings.debug:
            raise
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@resource_router.post("/sync-experience", response_model=VisionResponse)
async def sync_vision_experience(
    vision_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> VisionResponse:
    """
    Synchronize vision experience points with actual effort totals

    This ensures the vision's experience points always reflect the current
    time investment in root tasks (1 minute = 1 experience point).

    Args:
        vision_id: Vision ID
        db: Database session

    Returns:
        Updated vision with synced experience and stage
    """
    try:
        vision = await vision_service.sync_vision_experience(
            db,
            user_id=current_user.id,
            vision_id=vision_id,
        )
        if vision is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Vision not found"
            )
        return build_vision_response(vision)
    except HTTPException as exc:
        raise exc
    except Exception:
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@resource_router.post("/harvest", response_model=VisionResponse)
async def harvest_vision(
    vision_id: UUID,
    harvest_data: VisionHarvestRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> VisionResponse:
    """
    Harvest a mature vision (convert to fruit)

    Args:
        vision_id: Vision ID
        harvest_data: Harvest request data
        db: Database session

    Returns:
        Harvested vision
    """
    try:
        vision = await vision_service.harvest_vision(
            db,
            user_id=current_user.id,
            vision_id=vision_id,
            harvest_data=harvest_data,
        )
        if vision is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Vision not found"
            )
        return build_vision_response(vision)
    except VisionNotReadyForHarvestError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException as exc:
        raise exc
    except Exception:
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@resource_router.get("/stats", response_model=VisionStatsResponse)
async def get_vision_stats(
    vision_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> VisionStatsResponse:
    """
    Get statistics for a vision

    Args:
        vision_id: Vision ID
        db: Database session

    Returns:
        Vision statistics
    """
    try:
        stats = await vision_service.get_vision_stats(
            db,
            user_id=current_user.id,
            vision_id=vision_id,
        )
        if stats is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Vision not found"
            )
        return stats
    except HTTPException as exc:
        raise exc
    except Exception:
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


router.include_router(collection_router)
router.include_router(resource_router)
