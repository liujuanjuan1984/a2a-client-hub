"""
Actual Events API Router

This module contains all API endpoints for managing actual events (footprints).
Routers call into the service layer and map business exceptions to HTTP errors.
"""

import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.inspection import inspect

from app.api.deps import get_async_db, get_current_user
from app.api.routing import StrictAPIRouter
from app.core.config import settings
from app.core.logging import get_logger, log_exception
from app.db.models.user import User
from app.handlers import actual_events as actual_events_service
from app.handlers.actual_events import (
    DEFAULT_MAX_SEARCH_DAYS,
    DEFAULT_MAX_SEARCH_RESULTS,
    ActualEventNotDeletedError,
    ActualEventNotFoundError,
    ActualEventResultTooLargeError,
    AssociatedTaskNotFoundError,
    DeprecatedFieldError,
)
from app.schemas.actual_event import (
    ActualEventAdvancedSearchRequest,
    ActualEventBatchCreateRequest,
    ActualEventBatchCreateResponse,
    ActualEventBatchDeleteRequest,
    ActualEventBatchDeleteResponse,
    ActualEventBatchUpdateRequest,
    ActualEventBatchUpdateResponse,
    ActualEventCreate,
    ActualEventListResponse,
    ActualEventResponse,
    ActualEventSearchResponse,
    ActualEventUpdate,
    ActualEventWithEnergyResponse,
)
from app.serialization.entities import build_note_response, serialize_dimension_summary

logger = get_logger(__name__)

router = StrictAPIRouter(
    prefix="/actual-events",
    tags=["actual-events"],
    responses={404: {"description": "Not found"}},
    dependencies=[Depends(get_current_user)],
)
collection_router = StrictAPIRouter(tags=["actual-events"])
resource_router = StrictAPIRouter(prefix="/{event_id:uuid}", tags=["actual-events"])


def _build_actual_event_response(
    event: Any,
    *,
    person_summaries: List[Dict[str, Any]],
    task_summary: Optional[Dict[str, Any]],
    linked_notes: Optional[List[Dict[str, Any]]] = None,
    linked_notes_count: Optional[int] = None,
) -> ActualEventResponse:
    if isinstance(event, dict):
        base_payload: Dict[str, Any] = dict(event)
    else:
        try:
            mapper = inspect(event).mapper
            base_payload = {
                column.key: getattr(event, column.key, None)
                for column in mapper.columns
            }
        except Exception:  # noqa: BLE001
            base_payload = {
                key: getattr(event, key)
                for key in dir(event)
                if not key.startswith("_")
            }

    linked_notes_payload = linked_notes
    if linked_notes_payload is None:
        linked_notes_payload = [
            {
                "id": note_payload["id"],
                "content": note_payload["content"],
                "created_at": note_payload.get("created_at"),
                "updated_at": note_payload.get("updated_at"),
            }
            for note_payload in (
                build_note_response(note, include_timelogs=False).model_dump(
                    mode="json"
                )
                for note in getattr(event, "associated_notes", []) or []
            )
        ]

    notes_count = linked_notes_count
    if notes_count is None:
        notes_count = len(linked_notes_payload or [])

    payload = {
        **base_payload,
        "persons": person_summaries,
        "task": task_summary,
        "linked_notes": linked_notes_payload,
        "linked_notes_count": notes_count,
        "dimension_summary": serialize_dimension_summary(
            getattr(event, "dimension", None)
        ),
    }

    return ActualEventResponse.model_validate(payload)


@collection_router.post(
    "/", response_model=ActualEventWithEnergyResponse, status_code=201
)
async def create_actual_event(
    event: ActualEventCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> ActualEventWithEnergyResponse:
    """
    Create a new actual event with optional task completion and energy injection

    Args:
        event: Actual event data
        db: Database session

    Returns:
        Created actual event with energy injection results
    """
    try:
        # Call service layer
        db_event, energy_injections = await actual_events_service.create_actual_event(
            db,
            user_id=current_user.id,
            event_in=event,
            run_async=True,
        )

        # Get relations for response using search_actual_events
        events_with_relations = await actual_events_service.search_actual_events(
            db,
            user_id=current_user.id,
            event_id=db_event.id,
        )

        # Extract the single event result
        if events_with_relations:
            event_obj, person_summaries, task_summary = events_with_relations[0]
            notes_summary = [
                {
                    "id": payload["id"],
                    "content": payload["content"],
                    "created_at": payload.get("created_at"),
                    "updated_at": payload.get("updated_at"),
                }
                for payload in (
                    build_note_response(note, include_timelogs=False).model_dump(
                        mode="json"
                    )
                    for note in getattr(event_obj, "associated_notes", []) or []
                )
            ]
        else:
            person_summaries, task_summary, notes_summary = [], None, []

        # Create response data
        response_data = _build_actual_event_response(
            db_event,
            person_summaries=person_summaries,
            task_summary=task_summary,
            linked_notes=notes_summary,
        )

        return ActualEventWithEnergyResponse(
            **response_data.model_dump(),
            energy_injections=energy_injections if energy_injections else None,
        )
    except DeprecatedFieldError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except AssociatedTaskNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log_exception(
            logger, f"Failed to create actual event: {str(e)}", sys.exc_info()
        )
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@collection_router.post(
    "/batch-create", response_model=ActualEventBatchCreateResponse, status_code=201
)
async def batch_create_actual_events(
    request: ActualEventBatchCreateRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> ActualEventBatchCreateResponse:
    """
    Create multiple actual events in a single operation

    Args:
        request: Batch create request containing list of events to create
        db: Database session

    Returns:
        Batch create response with success/failure information
    """
    # Call service layer
    (
        created_count,
        failed_count,
        created_events_with_relations,
        errors,
    ) = await actual_events_service.batch_create_actual_events(
        db,
        user_id=current_user.id,
        events_data=request.events,
        run_async=True,
    )

    # Convert service layer results to API response format
    created_events = []
    for db_event, person_summaries, task_summary in created_events_with_relations:
        notes_summary = [
            {
                "id": payload["id"],
                "content": payload["content"],
                "created_at": payload.get("created_at"),
                "updated_at": payload.get("updated_at"),
            }
            for payload in (
                build_note_response(note, include_timelogs=False).model_dump(
                    mode="json"
                )
                for note in getattr(db_event, "associated_notes", []) or []
            )
        ]
        response_data = _build_actual_event_response(
            db_event,
            person_summaries=person_summaries,
            task_summary=task_summary,
            linked_notes=notes_summary,
        )
        created_events.append(response_data)

    return ActualEventBatchCreateResponse(
        created_count=created_count,
        failed_count=failed_count,
        created_events=created_events,
        errors=errors,
    )


@collection_router.get("/", response_model=ActualEventListResponse)
async def read_actual_events(
    start: datetime = Query(..., description="Start of time range (required)"),
    end: datetime = Query(..., description="End of time range (required)"),
    tracking_method: Optional[str] = Query(
        None, description="Filter by tracking method"
    ),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> ActualEventListResponse:
    """
    Retrieve actual events within a specified time range

    This endpoint is designed to work with calendar views, returning all actual events
    that overlap with the specified time range. This provides the "footprints" data
    that shows what actually happened during a given period.

    Args:
        start: Start of the time range (required for calendar views)
        end: End of the time range (required for calendar views)
        tracking_method: Filter by tracking method
        db: Database session

    Returns:
        List of actual events within the time range
    """
    try:
        fetch_started = time.perf_counter()
        events_with_relations = await actual_events_service.search_actual_events(
            db,
            user_id=current_user.id,
            start_date=start,
            end_date=end,
            tracking_method=tracking_method,
            include_notes=False,
            max_results=DEFAULT_MAX_SEARCH_RESULTS,
            max_range_days=DEFAULT_MAX_SEARCH_DAYS,
        )
    except ActualEventResultTooLargeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    fetch_duration = time.perf_counter() - fetch_started
    if settings.debug:
        logger.info(
            "Stage timing",
            extra={
                "event": "stage_timing",
                "stage": "actual_events.fetch",
                "duration": round(fetch_duration, 6),
                "result_count": len(events_with_relations),
            },
        )

    serialize_started = time.perf_counter()
    result_events = []
    for event, person_summaries, task_summary in events_with_relations:
        notes_count = getattr(event, "associated_notes_count", 0)
        response_data = _build_actual_event_response(
            event,
            person_summaries=person_summaries,
            task_summary=task_summary,
            linked_notes=[],
            linked_notes_count=notes_count,
        )
        result_events.append(response_data)
    serialize_duration = time.perf_counter() - serialize_started
    if settings.debug:
        logger.info(
            "Stage timing",
            extra={
                "event": "stage_timing",
                "stage": "actual_events.serialize",
                "duration": round(serialize_duration, 6),
                "result_count": len(result_events),
            },
        )

    total = len(result_events)
    return ActualEventListResponse(
        items=result_events,
        pagination={
            "page": 1,
            "size": total,
            "total": total,
            "pages": 1 if total else 0,
        },
        meta={
            "start_date": start,
            "end_date": end,
            "tracking_method": tracking_method,
            "returned_count": total,
            "total_count": total,
            "truncated": False,
        },
    )


@collection_router.get("/raw", response_model=ActualEventListResponse)
async def read_actual_events_raw(
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(
        100, ge=1, le=1000, description="Page size / number of records to return"
    ),
    start_date: Optional[datetime] = Query(
        None, description="Filter events starting from this date"
    ),
    end_date: Optional[datetime] = Query(
        None, description="Filter events ending before this date"
    ),
    tracking_method: Optional[str] = Query(
        None, description="Filter by tracking method"
    ),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> ActualEventListResponse:
    """
    Retrieve actual events with pagination and flexible filtering

    This endpoint provides the traditional pagination-based access to actual events,
    useful for management interfaces and data export.

    Args:
        page: Page number (1-indexed)
        size: Maximum number of records to return
        start_date: Filter events starting from this date
        end_date: Filter events ending before this date
        tracking_method: Filter by tracking method
        db: Database session

    Returns:
        List of actual events
    """
    # Call service layer
    offset = (page - 1) * size
    (
        events_with_relations,
        total,
    ) = await actual_events_service.list_actual_events_paginated(
        db,
        user_id=current_user.id,
        skip=offset,
        limit=size,
        start_date=start_date,
        end_date=end_date,
        tracking_method=tracking_method,
    )

    # Convert to response format
    result_events = []
    for event, person_summaries, task_summary in events_with_relations:
        notes_summary = [
            {
                "id": payload["id"],
                "content": payload["content"],
                "created_at": payload.get("created_at"),
                "updated_at": payload.get("updated_at"),
            }
            for payload in (
                build_note_response(note, include_timelogs=False).model_dump(
                    mode="json"
                )
                for note in getattr(event, "associated_notes", []) or []
            )
        ]
        response_data = _build_actual_event_response(
            event,
            person_summaries=person_summaries,
            task_summary=task_summary,
            linked_notes=notes_summary,
        )
        result_events.append(response_data)

    pages = (total + size - 1) // size if size else 0
    return ActualEventListResponse(
        items=result_events,
        pagination={
            "page": page,
            "size": size,
            "total": total,
            "pages": pages,
        },
        meta={
            "start_date": start_date,
            "end_date": end_date,
            "tracking_method": tracking_method,
            "returned_count": len(result_events),
            "total_count": total,
            "truncated": False,
        },
    )


@collection_router.post("/advanced-search", response_model=ActualEventSearchResponse)
async def advanced_search_actual_events(
    request: ActualEventAdvancedSearchRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> ActualEventSearchResponse:
    """
    Advanced search for actual events with flexible filtering options

    This endpoint provides advanced search capabilities for time logs:
    - Date range filtering (start_date required, end_date optional)
    - Dimension filtering by exact name match
    - Keyword search in title and notes fields (supports multiple keywords with OR logic)
    - Task filtering (specific task, no task, or all tasks)

    Args:
        request: Search request containing all search parameters
        db: Database session

    Returns:
        List of actual events matching the search criteria

    Raises:
        HTTPException: If start_date is invalid or dimension not found
    """
    try:
        # Call service layer using unified search function
        task_id_field_set = "task_id" in request.model_fields_set
        limit_value = settings.actual_events_search_limit
        metadata: Dict[str, Any] = {}
        events_with_relations = await actual_events_service.search_actual_events(
            db,
            user_id=current_user.id,
            start_date=request.start_date,
            end_date=request.end_date,
            dimension_name=request.dimension_name,
            description_keyword=request.description_keyword,
            task_id=request.task_id,
            task_id_null_only=task_id_field_set and request.task_id is None,
            include_notes=False,
            max_results=limit_value,
            max_range_days=None,
            allow_result_truncation=True,
            result_metadata=metadata,
        )

        # Convert to response format
        result_events = []
        for event, person_summaries, task_summary in events_with_relations:
            notes_count = getattr(event, "associated_notes_count", 0)
            response_data = _build_actual_event_response(
                event,
                person_summaries=person_summaries,
                task_summary=task_summary,
                linked_notes=[],
                linked_notes_count=notes_count,
            )
            result_events.append(response_data)

        limit_used = int(metadata.get("limit", limit_value))
        total_count = int(metadata.get("total_count", len(result_events)))
        pages = (total_count + limit_used - 1) // limit_used if limit_used else 0
        return ActualEventSearchResponse(
            items=result_events,
            pagination={
                "page": 1,
                "size": limit_used,
                "total": total_count,
                "pages": pages,
            },
            meta={
                "start_date": request.start_date,
                "end_date": request.end_date,
                "dimension_name": request.dimension_name,
                "description_keyword": request.description_keyword,
                "task_id": request.task_id,
                "limit": limit_used,
                "returned_count": len(result_events),
                "total_count": total_count,
                "truncated": bool(metadata.get("truncated", False)),
            },
        )
    except ActualEventNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log_exception(
            logger, f"Failed to search actual events: {str(e)}", sys.exc_info()
        )
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@resource_router.get("", response_model=ActualEventResponse)
async def read_actual_event(
    event_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> ActualEventResponse:
    """
    Retrieve a specific actual event by ID

    Args:
        event_id: Actual event ID
        db: Database session

    Returns:
        Actual event details

    Raises:
        HTTPException: If event not found
    """
    try:
        # Call service layer using search_actual_events
        events_with_relations = await actual_events_service.search_actual_events(
            db,
            user_id=current_user.id,
            event_id=event_id,
        )

        # Extract the single event result
        if not events_with_relations:
            raise HTTPException(status_code=404, detail="Actual event not found")

        db_event, person_summaries, task_summary = events_with_relations[0]
        notes_summary = [
            {
                "id": payload["id"],
                "content": payload["content"],
                "created_at": payload.get("created_at"),
                "updated_at": payload.get("updated_at"),
            }
            for payload in (
                build_note_response(note, include_timelogs=False).model_dump(
                    mode="json"
                )
                for note in getattr(db_event, "associated_notes", []) or []
            )
        ]

        # Create response data
        response_data = _build_actual_event_response(
            db_event,
            person_summaries=person_summaries,
            task_summary=task_summary,
            linked_notes=notes_summary,
        )
        return response_data
    except ActualEventNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log_exception(
            logger, f"Failed to get actual event {event_id}: {str(e)}", sys.exc_info()
        )
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@resource_router.put("", response_model=ActualEventResponse)
async def update_actual_event(
    event_id: UUID,
    event: ActualEventUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> ActualEventResponse:
    """
    Update a specific actual event

    Args:
        event_id: Actual event ID
        event: Updated event data
        db: Database session

    Returns:
        Updated actual event

    Raises:
        HTTPException: If event not found
    """
    try:
        # Call service layer
        (
            db_event,
            person_summaries,
            task_summary,
        ) = await actual_events_service.update_actual_event(
            db,
            user_id=current_user.id,
            event_id=event_id,
            update_in=event,
            run_async=True,
        )

        notes_summary = [
            {
                "id": payload["id"],
                "content": payload["content"],
                "created_at": payload.get("created_at"),
                "updated_at": payload.get("updated_at"),
            }
            for payload in (
                build_note_response(note, include_timelogs=False).model_dump(
                    mode="json"
                )
                for note in getattr(db_event, "associated_notes", []) or []
            )
        ]

        # Create response data
        response_data = _build_actual_event_response(
            db_event,
            person_summaries=person_summaries,
            task_summary=task_summary,
            linked_notes=notes_summary,
        )

        return response_data
    except ActualEventNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except AssociatedTaskNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except DeprecatedFieldError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log_exception(
            logger,
            f"Failed to update actual event {event_id}: {str(e)}",
            sys.exc_info(),
        )
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@resource_router.delete("", status_code=204)
async def delete_actual_event(
    event_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete a specific actual event."""
    try:
        # Call service layer
        await actual_events_service.delete_actual_event(
            db,
            user_id=current_user.id,
            event_id=event_id,
            hard_delete=False,
            run_async=True,
        )
    except ActualEventNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log_exception(
            logger,
            f"Failed to delete actual event {event_id}: {str(e)}",
            sys.exc_info(),
        )
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@collection_router.post("/batch-delete", response_model=ActualEventBatchDeleteResponse)
async def batch_delete_actual_events(
    request: ActualEventBatchDeleteRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> ActualEventBatchDeleteResponse:
    """
    Delete multiple actual events in a single operation

    Returns:
        Batch delete response with success/failure information
    """
    # Call service layer
    (
        deleted_count,
        failed_ids,
        errors,
    ) = await actual_events_service.batch_delete_actual_events(
        db,
        user_id=current_user.id,
        event_ids=request.event_ids,
        hard_delete=False,
        run_async=True,
    )

    return ActualEventBatchDeleteResponse(
        deleted_count=deleted_count, failed_ids=failed_ids, errors=errors
    )


@resource_router.post("/quick-end", response_model=ActualEventResponse)
async def quick_end_actual_event(
    event_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> ActualEventResponse:
    """
    Quick action to end an ongoing actual event (set end_time to now)

    This is useful for "stop tracking" functionality in the UI.

    Args:
        event_id: Actual event ID
        db: Database session

    Returns:
        Updated actual event with end_time set

    Raises:
        HTTPException: If event not found or already ended
    """
    try:
        # Call service layer
        (
            db_event,
            person_summaries,
            task_summary,
        ) = await actual_events_service.quick_end_actual_event(
            db,
            user_id=current_user.id,
            event_id=event_id,
            run_async=True,
        )

        notes_summary = [
            {
                "id": payload["id"],
                "content": payload["content"],
                "created_at": payload.get("created_at"),
                "updated_at": payload.get("updated_at"),
            }
            for payload in (
                build_note_response(note, include_timelogs=False).model_dump(
                    mode="json"
                )
                for note in getattr(db_event, "associated_notes", []) or []
            )
        ]

        # Create response data
        response_data = _build_actual_event_response(
            db_event,
            person_summaries=person_summaries,
            task_summary=task_summary,
            linked_notes=notes_summary,
        )
        return response_data
    except ActualEventNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    # ActualEventAlreadyEndedError is no longer needed since end_time is always required
    except Exception as e:
        log_exception(
            logger,
            f"Failed to quick end actual event {event_id}: {str(e)}",
            sys.exc_info(),
        )
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@resource_router.post("/restore", response_model=ActualEventResponse)
async def restore_actual_event(
    event_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> ActualEventResponse:
    """
    Restore a soft deleted actual event

    Args:
        event_id: Actual event ID
        db: Database session

    Returns:
        Restored actual event

    Raises:
        HTTPException: If event not found or not deleted
    """
    try:
        # Call service layer
        (
            db_event,
            person_summaries,
            task_summary,
        ) = await actual_events_service.restore_actual_event(
            db,
            user_id=current_user.id,
            event_id=event_id,
            run_async=True,
        )

        notes_summary = [
            {
                "id": payload["id"],
                "content": payload["content"],
                "created_at": payload.get("created_at"),
                "updated_at": payload.get("updated_at"),
            }
            for payload in (
                build_note_response(note, include_timelogs=False).model_dump(
                    mode="json"
                )
                for note in getattr(db_event, "associated_notes", []) or []
            )
        ]

        # Create response data
        response_data = _build_actual_event_response(
            db_event,
            person_summaries=person_summaries,
            task_summary=task_summary,
            linked_notes=notes_summary,
        )
        return response_data
    except ActualEventNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ActualEventNotDeletedError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log_exception(
            logger,
            f"Failed to restore actual event {event_id}: {str(e)}",
            sys.exc_info(),
        )
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@collection_router.post("/batch-restore", response_model=ActualEventBatchDeleteResponse)
async def batch_restore_actual_events(
    request: ActualEventBatchDeleteRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> ActualEventBatchDeleteResponse:
    """
    Restore multiple soft deleted actual events

    Args:
        request: Batch restore request containing list of event IDs
        db: Database session

    Returns:
        Batch restore response with success/failure information
    """
    # Call service layer
    (
        restored_count,
        failed_ids,
        errors,
    ) = await actual_events_service.batch_restore_actual_events(
        db,
        user_id=current_user.id,
        event_ids=request.event_ids,
        run_async=True,
    )

    return ActualEventBatchDeleteResponse(
        deleted_count=restored_count,  # Reuse the same response structure
        failed_ids=failed_ids,
        errors=errors,
    )


@collection_router.post("/batch-update", response_model=ActualEventBatchUpdateResponse)
async def batch_update_actual_events(
    request: ActualEventBatchUpdateRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> ActualEventBatchUpdateResponse:
    """
    Batch update multiple actual events (persons or title)

    Args:
        request: Batch update request containing update configuration
        db: Database session

    Returns:
        Batch update response with success/failure information
    """
    # Call service layer
    (
        updated_count,
        failed_ids,
        errors,
    ) = await actual_events_service.batch_update_actual_events(
        db,
        user_id=current_user.id,
        event_ids=request.event_ids,
        update_type=request.update_type,
        persons=request.persons,
        title=request.title,
        task=request.task,
        dimension=request.dimension,
        run_async=True,
    )

    return ActualEventBatchUpdateResponse(
        updated_count=updated_count,
        failed_ids=failed_ids,
        errors=errors,
    )


router.include_router(collection_router)
router.include_router(resource_router)
