"""
Planned Events API Router

This module contains all API endpoints for managing planned events (compass needle).
Routers call into the service layer and map business exceptions to HTTP errors.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.routing import StrictAPIRouter
from app.core.config import settings
from app.db.models.user import User
from app.handlers import planned_events as planned_events_service
from app.handlers.planned_events import (
    InvalidDeleteTypeError,
    InvalidPlannedEventStatusError,
    InvalidUpdateScopeError,
    PlannedEventNotFoundError,
)
from app.schemas.planned_event import (
    PlannedEventCreate,
    PlannedEventListResponse,
    PlannedEventRangeListResponse,
    PlannedEventResponse,
    PlannedEventUpdate,
)

router = StrictAPIRouter(
    prefix="/planned-events",
    tags=["planned-events"],
    responses={404: {"description": "Not found"}},
    dependencies=[Depends(get_current_user)],
)
collection_router = StrictAPIRouter(tags=["planned-events"])
resource_router = StrictAPIRouter(prefix="/{event_id:uuid}", tags=["planned-events"])


@collection_router.post("/", response_model=PlannedEventResponse, status_code=201)
async def create_planned_event(
    event: PlannedEventCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> PlannedEventResponse:
    """
    Create a new planned event

    Args:
        event: Planned event data
        db: Database session

    Returns:
        Created planned event
    """
    try:
        db_event = await planned_events_service.create_planned_event(
            db,
            user_id=current_user.id,
            event_in=event,
        )
        return PlannedEventResponse.model_validate(db_event)
    except Exception:
        if settings.debug:
            raise
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@collection_router.get("/", response_model=PlannedEventRangeListResponse)
async def read_planned_events(
    start: datetime = Query(..., description="Start of time range (required)"),
    end: datetime = Query(..., description="End of time range (required)"),
    status: Optional[str] = Query(None, description="Filter by status"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> PlannedEventRangeListResponse:
    """
    Retrieve planned events within a time range, including recurring instances

    This is the core API for calendar views. It returns both:
    1. Non-recurring events that fall within the time range
    2. Computed instances of recurring events that fall within the time range

    The response includes a mix of original events and generated recurring instances,
    all expanded and ready for calendar rendering.

    Args:
        start: Start of the time range (required for calendar views)
        end: End of the time range (required for calendar views)
        status: Filter by event status
        db: Database session

    Returns:
        List of events (mix of original and recurring instances) as dictionaries
    """
    try:
        events = await planned_events_service.list_planned_events_in_range(
            db,
            user_id=current_user.id,
            start=start,
            end=end,
            status=status,
        )
        total = len(events)
        return PlannedEventRangeListResponse(
            items=events,
            pagination={
                "page": 1,
                "size": total,
                "total": total,
                "pages": 1 if total else 0,
            },
            meta={
                "start": start,
                "end": end,
                "status": status,
            },
        )
    except InvalidPlannedEventStatusError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        if settings.debug:
            raise
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@collection_router.get("/raw", response_model=PlannedEventListResponse)
async def read_planned_events_raw(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    size: int = Query(100, ge=1, le=1000, description="Number of records per page"),
    status: Optional[str] = Query(None, description="Filter by status"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> PlannedEventListResponse:
    """
    Retrieve raw planned events (master events only, no recurring instances)

    This endpoint returns the original planned events as stored in the database,
    without computing recurring instances. Useful for editing and management.

    Args:
        skip: Number of records to skip for pagination
        limit: Maximum number of records to return
        status: Filter by event status
        db: Database session

    Returns:
        List of raw planned events (master events only)
    """
    try:
        offset = (page - 1) * size
        events, total = await planned_events_service.list_planned_events_with_total(
            db,
            user_id=current_user.id,
            skip=offset,
            limit=size,
            status=status,
        )
        items = [PlannedEventResponse.model_validate(event) for event in events]
        pages = (total + size - 1) // size if size else 0
        return PlannedEventListResponse(
            items=items,
            pagination={
                "page": page,
                "size": size,
                "total": total,
                "pages": pages,
            },
            meta={
                "status": status,
            },
        )
    except InvalidPlannedEventStatusError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@resource_router.get("", response_model=PlannedEventResponse)
async def read_planned_event(
    event_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> PlannedEventResponse:
    """
    Retrieve a specific planned event by ID

    Args:
        event_id: Planned event ID
        db: Database session

    Returns:
        Planned event details

    Raises:
        HTTPException: If event not found
    """
    try:
        db_event = await planned_events_service.get_planned_event(
            db,
            user_id=current_user.id,
            event_id=event_id,
        )
        return PlannedEventResponse.model_validate(db_event)
    except PlannedEventNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@resource_router.put("", response_model=PlannedEventResponse)
async def update_planned_event(
    event_id: UUID,
    event: PlannedEventUpdate,
    update_type: str = Query(
        "all", description="Update scope: 'single', 'all_future', or 'all'"
    ),
    instance_id: Optional[UUID] = Query(
        None, description="Occurrence identifier for scoped updates"
    ),
    instance_start: Optional[datetime] = Query(
        None,
        description="Occurrence start timestamp when editing a single instance or future instances",
    ),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> PlannedEventResponse:
    """
    Update a specific planned event

    Args:
        event_id: Planned event ID
        event: Updated event data
        db: Database session

    Returns:
        Updated planned event

    Raises:
        HTTPException: If event not found
    """
    try:
        db_event = await planned_events_service.update_planned_event(
            db,
            user_id=current_user.id,
            event_id=event_id,
            update_in=event,
            update_scope=update_type,
            instance_id=instance_id,
            instance_start=instance_start,
        )
        return PlannedEventResponse.model_validate(db_event)
    except PlannedEventNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidUpdateScopeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@collection_router.get("/by-task/{task_id}", response_model=PlannedEventListResponse)
async def get_events_by_task(
    task_id: UUID,
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    size: int = Query(100, ge=1, le=1000, description="Number of records per page"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> PlannedEventListResponse:
    """
    Get all planned events associated with a specific task

    Args:
        task_id: Task ID to filter by
        db: Database session

    Returns:
        List of planned events associated with the task
    """
    try:
        offset = (page - 1) * size
        events, total = await planned_events_service.list_planned_events_with_total(
            db,
            user_id=current_user.id,
            task_id=task_id,
            skip=offset,
            limit=size,
        )
        items = [PlannedEventResponse.model_validate(event) for event in events]
        pages = (total + size - 1) // size if size else 0
        return PlannedEventListResponse(
            items=items,
            pagination={
                "page": page,
                "size": size,
                "total": total,
                "pages": pages,
            },
            meta={
                "task_id": task_id,
            },
        )
    except Exception:
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@resource_router.delete("", status_code=204)
async def delete_planned_event(
    event_id: UUID,
    delete_type: str = Query(
        "single", description="Delete type: 'single', 'all_future', 'all'"
    ),
    instance_id: Optional[UUID] = Query(
        None,
        description="Instance identifier when deleting a single occurrence",
    ),
    instance_start: Optional[datetime] = Query(
        None,
        description="Occurrence start timestamp for instance-level deletions",
    ),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """
    Delete a specific planned event

    Args:
        event_id: Planned event ID
        delete_type: Delete type for recurring events:
            - 'single': Delete only this instance (default)
            - 'all_future': Delete this and all future instances
            - 'all': Delete all instances of this recurring event
        db: Database session

    Raises:
        HTTPException: If event not found or invalid delete type
    """
    try:
        await planned_events_service.delete_planned_event(
            db,
            user_id=current_user.id,
            event_id=event_id,
            delete_type=delete_type,
            instance_id=instance_id,
            instance_start=instance_start,
        )
    except InvalidDeleteTypeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PlannedEventNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


router.include_router(collection_router)
router.include_router(resource_router)
