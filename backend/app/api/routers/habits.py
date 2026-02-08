"""
Habit API Router

This module contains all API endpoints for managing habits.
Routers call into the service layer and map business exceptions to HTTP errors.
"""

from datetime import date
from typing import Dict, Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.routing import StrictAPIRouter
from app.db.models.user import User
from app.handlers import habits as habits_service
from app.handlers.habits import (
    HabitActionNotFoundError,
    HabitNotFoundError,
    InvalidOperationError,
    ValidationError,
)
from app.schemas.habit import (
    HabitActionListResponse,
    HabitActionResponse,
    HabitActionUpdate,
    HabitActionWithHabitListResponse,
    HabitCreate,
    HabitListResponse,
    HabitOverviewListResponse,
    HabitOverviewResponse,
    HabitResponse,
    HabitStatsResponse,
    HabitTaskAssociationsResponse,
    HabitUpdate,
)

router = StrictAPIRouter(
    prefix="/habits",
    tags=["habits"],
    dependencies=[Depends(get_current_user)],
)
collection_router = StrictAPIRouter(tags=["habits"])
resource_router = StrictAPIRouter(prefix="/{habit_id:uuid}", tags=["habits"])


@collection_router.get("/", response_model=HabitListResponse)
async def get_habits(
    page: int = Query(1, ge=1),
    size: int = Query(100, ge=1, le=200),
    status_filter: Optional[str] = None,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> HabitListResponse:
    """
    Get list of habits with optional filtering

    Args:
        page: Page number (1-indexed)
        size: Maximum number of records to return
        status_filter: Filter by status
        db: Database session

    Returns:
        List of habits with total count
    """
    try:
        skip = (page - 1) * size
        habits, total = await habits_service.list_habits(
            db=db,
            user_id=current_user.id,
            skip=skip,
            limit=size,
            status_filter=status_filter,
        )
        pages = (total + size - 1) // size if size else 0
        return HabitListResponse(
            items=habits,
            pagination={
                "page": page,
                "size": size,
                "total": total,
                "pages": pages,
            },
            meta={"status_filter": status_filter},
        )
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred.",
        )


@collection_router.get("/overviews", response_model=HabitOverviewListResponse)
async def get_habit_overviews(
    page: int = Query(1, ge=1),
    size: int = Query(100, ge=1, le=200),
    status_filter: Optional[str] = None,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> HabitOverviewListResponse:
    """Get list of habits with their statistics."""

    try:
        skip = (page - 1) * size
        overviews, total = await habits_service.list_habit_overviews(
            db=db,
            user_id=current_user.id,
            skip=skip,
            limit=size,
            status_filter=status_filter,
        )
        pages = (total + size - 1) // size if size else 0
        return HabitOverviewListResponse(
            items=[
                HabitOverviewResponse(
                    habit=HabitResponse.model_validate(entry["habit"]),
                    stats=HabitStatsResponse(**entry["stats"]),
                )
                for entry in overviews
            ],
            pagination={
                "page": page,
                "size": size,
                "total": total,
                "pages": pages,
            },
            meta={"status_filter": status_filter},
        )
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred.",
        )


@collection_router.post("/", response_model=HabitResponse)
async def create_habit(
    habit: HabitCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> HabitResponse:
    """
    Create a new habit

    Args:
        habit: Habit creation data
        db: Database session

    Returns:
        Created habit
    """
    try:
        db_habit = await habits_service.create_habit(
            db=db, user_id=current_user.id, habit_in=habit
        )
        return HabitResponse.model_validate(db_habit)
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred.",
        )


@resource_router.get("", response_model=HabitResponse)
async def get_habit(
    habit_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get a specific habit by ID

    Args:
        habit_id: Habit ID
        db: Database session

    Returns:
        Habit details
    """
    try:
        habit = await habits_service.get_habit(
            db=db, user_id=current_user.id, habit_id=habit_id
        )
        if not habit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Habit not found"
            )
        return HabitResponse.model_validate(habit)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred.",
        )


@resource_router.get("/overview", response_model=HabitOverviewResponse)
async def get_habit_overview(
    habit_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> HabitOverviewResponse:
    """Get a single habit with statistics included."""

    try:
        overview = await habits_service.get_habit_overview(
            db=db,
            user_id=current_user.id,
            habit_id=habit_id,
        )
        return HabitOverviewResponse(
            habit=HabitResponse.model_validate(overview["habit"]),
            stats=HabitStatsResponse(**overview["stats"]),
        )
    except HabitNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred.",
        )


@resource_router.put("", response_model=HabitResponse)
async def update_habit(
    habit_id: UUID,
    habit_update: HabitUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> HabitResponse:
    """
    Update a habit

    Args:
        habit_id: Habit ID
        habit_update: Habit update data
        db: Database session

    Returns:
        Updated habit
    """
    try:
        habit = await habits_service.update_habit(
            db=db,
            user_id=current_user.id,
            habit_id=habit_id,
            habit_update=habit_update,
        )
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred.",
        )

    if not habit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Habit not found"
        )

    return HabitResponse.model_validate(habit)


@resource_router.delete("")
async def delete_habit(
    habit_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, str]:
    """Delete a habit."""
    try:
        success = await habits_service.delete_habit(
            db=db,
            user_id=current_user.id,
            habit_id=habit_id,
            hard_delete=False,
        )
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Habit not found"
            )
        return {"message": "Habit deleted successfully"}
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred.",
        )


@resource_router.get("/actions", response_model=HabitActionListResponse)
async def get_habit_actions(
    habit_id: UUID,
    page: int = Query(1, ge=1),
    size: int = Query(100, ge=1, le=200),
    status_filter: Optional[str] = None,
    center_date: Optional[date] = Query(
        None, description="Reference date for windowed queries (YYYY-MM-DD)"
    ),
    days_before: Optional[int] = Query(
        None,
        ge=0,
        le=100,
        description="Number of days before the reference date to include (default 5)",
    ),
    days_after: Optional[int] = Query(
        None,
        ge=0,
        le=100,
        description="Number of days after the reference date to include (default same as days_before)",
    ),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> HabitActionListResponse:
    """
    Get actions for a specific habit

    Args:
        habit_id: Habit ID
        page: Page number (1-indexed)
        size: Maximum number of records to return
        status_filter: Filter by status
        db: Database session

    Returns:
        List of habit actions
    """
    try:
        skip = (page - 1) * size
        actions, total = await habits_service.get_habit_actions(
            db=db,
            user_id=current_user.id,
            habit_id=habit_id,
            skip=skip,
            limit=size,
            status_filter=status_filter,
            center_date=center_date,
            days_before=days_before,
            days_after=days_after,
        )
        pages = (total + size - 1) // size if size else 0
        return HabitActionListResponse(
            items=actions,
            pagination={
                "page": page,
                "size": size,
                "total": total,
                "pages": pages,
            },
            meta={
                "status_filter": status_filter,
                "center_date": center_date,
                "days_before": days_before,
                "days_after": days_after,
            },
        )
    except HabitNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred.",
        )


@resource_router.put("/actions/{action_id:uuid}", response_model=HabitActionResponse)
async def update_habit_action(
    habit_id: UUID,
    action_id: UUID,
    action_update: HabitActionUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> HabitActionResponse:
    """
    Update a habit action

    Args:
        habit_id: Habit ID
        action_id: Action ID
        action_update: Action update data
        db: Database session

    Returns:
        Updated action
    """
    try:
        action = await habits_service.update_habit_action(
            db=db,
            user_id=current_user.id,
            habit_id=habit_id,
            action_id=action_id,
            action_update=action_update,
        )
        if not action:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Action not found"
            )
        return HabitActionResponse.model_validate(action)
    except HabitNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except HabitActionNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except InvalidOperationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred.",
        )


@resource_router.get("/stats", response_model=HabitStatsResponse)
async def get_habit_stats(
    habit_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> HabitStatsResponse:
    """
    Get statistics for a habit

    Args:
        habit_id: Habit ID
        db: Database session

    Returns:
        Habit statistics
    """
    try:
        stats = await habits_service.get_habit_stats(
            db=db,
            user_id=current_user.id,
            habit_id=habit_id,
        )
        return HabitStatsResponse(**stats)
    except HabitNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred.",
        )


@collection_router.get(
    "/actions/by-date/{action_date}",
    response_model=HabitActionWithHabitListResponse,
)
async def get_habit_actions_by_date(
    action_date: date,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> HabitActionWithHabitListResponse:
    """
    Get all habit actions for a specific date with habit information

    Args:
        action_date: The date to get actions for (YYYY-MM-DD)
        db: Database session

    Returns:
        List of habit actions with habit details
    """
    try:
        actions = await habits_service.get_habit_actions_by_date(
            db=db,
            user_id=current_user.id,
            action_date=action_date,
        )
        total = len(actions)
        pages = 1 if total > 0 else 0
        return HabitActionWithHabitListResponse(
            items=actions,
            pagination={
                "page": 1,
                "size": total,
                "total": total,
                "pages": pages,
            },
            meta={"action_date": action_date},
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred.",
        )


@collection_router.get(
    "/habit-task-associations/", response_model=HabitTaskAssociationsResponse
)
async def get_habit_task_associations(
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> HabitTaskAssociationsResponse:
    """
    Get all habit-task associations for the current user

    Returns a dictionary mapping task_id to habit list for all habits
    that are associated with tasks.

    Args:
        db: Database session

    Returns:
        Dictionary mapping task_id to habit list
    """
    try:
        associations = await habits_service.get_habit_task_associations(
            db=db, user_id=current_user.id
        )
        return HabitTaskAssociationsResponse(associations=associations)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred.",
        )


router.include_router(collection_router)
router.include_router(resource_router)
