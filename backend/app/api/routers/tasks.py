"""
Task API routes

This module contains all API routes for task management.
Routers call into the service layer and map business exceptions to HTTP errors.
"""

import logging
import time
from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.routing import StrictAPIRouter
from app.core.config import settings
from app.db.models.user import User
from app.handlers import tasks as task_service
from app.handlers.tasks import (
    CircularReferenceError,
    InvalidOperationError,
    InvalidPlanningCycleError,
    InvalidStatusError,
    InvalidTaskDepthError,
    ParentTaskNotFoundError,
    TaskCannotBeCompletedError,
    TaskNotFoundError,
    VisionNotFoundError,
)
from app.schemas.actual_event import ActualEventListResponse
from app.schemas.task import (
    TaskCreate,
    TaskHierarchy,
    TaskListResponse,
    TaskMoveRequest,
    TaskMoveResponse,
    TaskQueryRequest,
    TaskReorderRequest,
    TaskResponse,
    TaskStatsResponse,
    TaskStatusUpdate,
    TaskUpdate,
    TaskWithSubtasks,
)

router = StrictAPIRouter(
    prefix="/tasks",
    tags=["tasks"],
    responses={404: {"description": "Not found"}},
    dependencies=[Depends(get_current_user)],
)
collection_router = StrictAPIRouter(tags=["tasks"])
resource_router = StrictAPIRouter(prefix="/{task_id:uuid}", tags=["tasks"])
logger = logging.getLogger(__name__)


@collection_router.get("/", response_model=TaskListResponse)
async def get_tasks(
    page: int = Query(1, ge=1),
    size: int = Query(100, ge=1),
    vision_id: Optional[UUID] = None,
    vision_in: Optional[str] = None,  # comma-separated list
    status_filter: Optional[str] = None,
    status_in: Optional[str] = None,  # comma-separated list
    exclude_status: Optional[str] = None,  # comma-separated list
    planning_cycle_type: Optional[str] = None,  # Filter by planning cycle type
    planning_cycle_start_date: Optional[
        str
    ] = None,  # Filter by planning cycle start date (YYYY-MM-DD)
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    fields: str = "basic",
) -> TaskListResponse:
    """
    Get all tasks with optional filtering

    Args:
        page: Page number (1-indexed)
        size: Maximum number of records to return
        vision_id: Filter by vision ID
        vision_in: Comma-separated list of vision IDs to include
        status_filter: Filter by task status
        status_in: Comma-separated list of statuses to include
        exclude_status: Comma-separated list of statuses to exclude
        planning_cycle_type: Filter by planning cycle type (year, month, week, day)
        planning_cycle_start_date: Filter by planning cycle start date (YYYY-MM-DD format)
        db: Database session

    Returns:
        List of tasks
    """
    try:
        if fields not in {"basic", "full"}:
            raise HTTPException(
                status_code=400, detail="fields must be 'basic' or 'full'"
            )

        requested_size = size
        # Enforce sane maximum to prevent heavy payloads from overwhelming low-spec hosts
        max_limit = max(1, settings.tasks_max_page_size)
        if size > max_limit:
            if settings.debug:
                logger.info(
                    "Clamping tasks limit",
                    extra={
                        "event": "tasks.limit_clamped",
                        "requested": requested_size,
                        "applied": max_limit,
                        "user_id": str(current_user.id),
                    },
                )
            size = max_limit
        elif size < 1:
            size = 1

        fetch_started = time.perf_counter()
        offset = (page - 1) * size
        tasks, total = await task_service.list_tasks_with_total(
            db=db,
            user_id=current_user.id,
            skip=offset,
            limit=size,
            vision_id=vision_id,
            vision_in=vision_in,
            status_filter=status_filter,
            status_in=status_in,
            exclude_status=exclude_status,
            planning_cycle_type=planning_cycle_type,
            planning_cycle_start_date=planning_cycle_start_date,
            include_details=fields == "full",
        )
        fetch_duration = time.perf_counter() - fetch_started
        if settings.debug:
            logger.info(
                "Stage timing",
                extra={
                    "event": "stage_timing",
                    "stage": "tasks.fetch",
                    "duration": round(fetch_duration, 6),
                    "result_count": len(tasks),
                },
            )

        serialize_started = time.perf_counter()
        response_payload = [TaskResponse.model_validate(t) for t in tasks]
        serialize_duration = time.perf_counter() - serialize_started
        if settings.debug:
            logger.info(
                "Stage timing",
                extra={
                    "event": "stage_timing",
                    "stage": "tasks.serialize",
                    "duration": round(serialize_duration, 6),
                    "result_count": len(response_payload),
                },
            )

        pages = (total + size - 1) // size if size else 0
        return TaskListResponse(
            items=response_payload,
            pagination={
                "page": page,
                "size": size,
                "total": total,
                "pages": pages,
            },
            meta={
                "vision_id": vision_id,
                "vision_in": vision_in,
                "status_filter": status_filter,
                "status_in": status_in,
                "exclude_status": exclude_status,
                "planning_cycle_type": planning_cycle_type,
                "planning_cycle_start_date": planning_cycle_start_date,
                "fields": fields,
            },
        )
    except InvalidStatusError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except InvalidOperationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception(
            "Failed to list tasks",
            extra={
                "user_id": str(current_user.id),
                "page": page,
                "size": size,
                "vision_id": str(vision_id) if vision_id else None,
                "status_filter": status_filter,
                "status_in": status_in,
                "exclude_status": exclude_status,
                "planning_cycle_type": planning_cycle_type,
                "planning_cycle_start_date": planning_cycle_start_date,
            },
        )
        if settings.debug:
            raise
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@collection_router.post("/query", response_model=TaskListResponse)
async def query_tasks(
    payload: TaskQueryRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> TaskListResponse:
    """
    Query tasks with filters via POST body
    """
    vision_in: Optional[str] = None
    status_in: Optional[str] = None
    exclude_status: Optional[str] = None
    planning_cycle_start_date: Optional[str] = None
    try:
        if payload.fields not in {"basic", "full"}:
            raise HTTPException(
                status_code=400, detail="fields must be 'basic' or 'full'"
            )
        if payload.vision_id and payload.vision_ids:
            raise HTTPException(
                status_code=400,
                detail="Provide either vision_id or vision_ids, not both",
            )

        requested_size = payload.size
        max_limit = max(1, settings.tasks_max_page_size)
        size = payload.size
        if size > max_limit:
            if settings.debug:
                logger.info(
                    "Clamping tasks limit",
                    extra={
                        "event": "tasks.limit_clamped",
                        "requested": requested_size,
                        "applied": max_limit,
                        "user_id": str(current_user.id),
                    },
                )
            size = max_limit
        elif size < 1:
            size = 1

        page = payload.page
        offset = (page - 1) * size

        vision_in = (
            ",".join(str(vid) for vid in payload.vision_ids)
            if payload.vision_ids
            else None
        )
        status_in = ",".join(payload.status_in) if payload.status_in else None
        exclude_status = (
            ",".join(payload.exclude_status) if payload.exclude_status else None
        )
        planning_cycle_start_date = (
            payload.planning_cycle_start_date.isoformat()
            if payload.planning_cycle_start_date
            else None
        )

        fetch_started = time.perf_counter()
        tasks, total = await task_service.list_tasks_with_total(
            db=db,
            user_id=current_user.id,
            skip=offset,
            limit=size,
            vision_id=payload.vision_id,
            vision_in=vision_in,
            status_filter=payload.status_filter,
            status_in=status_in,
            exclude_status=exclude_status,
            planning_cycle_type=payload.planning_cycle_type,
            planning_cycle_start_date=planning_cycle_start_date,
            include_details=payload.fields == "full",
        )
        fetch_duration = time.perf_counter() - fetch_started
        if settings.debug:
            logger.info(
                "Stage timing",
                extra={
                    "event": "stage_timing",
                    "stage": "tasks.fetch",
                    "duration": round(fetch_duration, 6),
                    "result_count": len(tasks),
                },
            )

        serialize_started = time.perf_counter()
        response_payload = [TaskResponse.model_validate(t) for t in tasks]
        serialize_duration = time.perf_counter() - serialize_started
        if settings.debug:
            logger.info(
                "Stage timing",
                extra={
                    "event": "stage_timing",
                    "stage": "tasks.serialize",
                    "duration": round(serialize_duration, 6),
                    "result_count": len(response_payload),
                },
            )

        pages = (total + size - 1) // size if size else 0
        return TaskListResponse(
            items=response_payload,
            pagination={
                "page": page,
                "size": size,
                "total": total,
                "pages": pages,
            },
            meta={
                "vision_id": payload.vision_id,
                "vision_in": vision_in,
                "status_filter": payload.status_filter,
                "status_in": status_in,
                "exclude_status": exclude_status,
                "planning_cycle_type": payload.planning_cycle_type,
                "planning_cycle_start_date": payload.planning_cycle_start_date,
                "fields": payload.fields,
            },
        )
    except InvalidStatusError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except InvalidOperationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        logger.exception(
            "Failed to query tasks",
            extra={
                "user_id": str(current_user.id),
                "page": payload.page,
                "size": payload.size,
                "vision_id": str(payload.vision_id) if payload.vision_id else None,
                "vision_in": vision_in,
                "status_filter": payload.status_filter,
                "status_in": status_in,
                "exclude_status": exclude_status,
                "planning_cycle_type": payload.planning_cycle_type,
                "planning_cycle_start_date": planning_cycle_start_date,
            },
        )
        if settings.debug:
            raise
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@collection_router.get("/vision/{vision_id}/hierarchy", response_model=TaskHierarchy)
async def get_vision_task_hierarchy(
    vision_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> TaskHierarchy:
    """
    Get hierarchical task structure for a vision

    Args:
    vision_id: Vision UUID
        db: Database session

    Returns:
        Hierarchical task structure
    """
    try:
        return await task_service.get_vision_task_hierarchy(
            db=db,
            user_id=current_user.id,
            vision_id=vision_id,
        )
    except VisionNotFoundError:
        raise HTTPException(status_code=404, detail="Vision not found")
    except Exception:
        logger.exception(
            "Failed to load vision task hierarchy",
            extra={
                "user_id": str(current_user.id),
                "vision_id": str(vision_id),
            },
        )
        if settings.debug:
            raise
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@resource_router.get("", response_model=TaskResponse)
async def get_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> TaskResponse:
    """
    Get a specific task by UUID

    Args:
        task_id: Task UUID
        db: Database session

    Returns:
        Task details
    """
    task = await task_service.get_task(db=db, user_id=current_user.id, task_id=task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return TaskResponse.model_validate(task)


@resource_router.get("/with-subtasks", response_model=TaskWithSubtasks)
async def get_task_with_subtasks(
    task_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> TaskWithSubtasks:
    """
    Get a task with all its subtasks

    Args:
        task_id: Task ID
        db: Database session

    Returns:
        Task with subtasks
    """
    try:
        result = await task_service.get_task_with_subtasks(
            db=db,
            user_id=current_user.id,
            task_id=task_id,
        )
        return TaskWithSubtasks.model_validate(result) if result else None
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="Task not found")
    except Exception:
        logger.exception(
            "Failed to get task with subtasks",
            extra={"user_id": str(current_user.id), "task_id": str(task_id)},
        )
        if settings.debug:
            raise
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@collection_router.post(
    "/", response_model=TaskResponse, status_code=status.HTTP_201_CREATED
)
async def create_task(
    task_data: TaskCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> TaskResponse:
    """
    Create a new task

    Args:
        task_data: Task creation data
        db: Database session

    Returns:
        Created task
    """
    try:
        task = await task_service.create_task(
            db,
            user_id=current_user.id,
            task_data=task_data,
            run_async=True,
        )
        return TaskResponse.model_validate(task)
    except VisionNotFoundError:
        raise HTTPException(status_code=404, detail="Vision not found")
    except ParentTaskNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidTaskDepthError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except InvalidPlanningCycleError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception(
            "Failed to create task",
            extra={
                "user_id": str(current_user.id),
                "vision_id": str(task_data.vision_id),
                "parent_task_id": (
                    str(task_data.parent_task_id) if task_data.parent_task_id else None
                ),
            },
        )
        if settings.debug:
            raise
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@resource_router.put("", response_model=TaskResponse)
async def update_task(
    task_id: UUID,
    task_data: TaskUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> TaskResponse:
    """
    Update a task

    Args:
        task_id: Task ID
        task_data: Task update data
        db: Database session

    Returns:
        Updated task
    """
    try:
        task = await task_service.update_task(
            db=db,
            user_id=current_user.id,
            task_id=task_id,
            task_data=task_data,
            run_async=True,
        )
        return TaskResponse.model_validate(task)
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="Task not found")
    except ParentTaskNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except CircularReferenceError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except InvalidTaskDepthError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except InvalidPlanningCycleError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception(
            "Failed to update task",
            extra={"user_id": str(current_user.id), "task_id": str(task_id)},
        )
        if settings.debug:
            raise
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@resource_router.patch("/status", response_model=TaskResponse)
async def update_task_status(
    task_id: UUID,
    status_data: TaskStatusUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> TaskResponse:
    """
    Update task status

    Args:
        task_id: Task ID
        status_data: New status data
        db: Database session

    Returns:
        Updated task
    """
    try:
        task = await task_service.update_task_status(
            db=db,
            user_id=current_user.id,
            task_id=task_id,
            status_data=status_data,
            run_async=True,
        )
        return TaskResponse.model_validate(task)
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="Task not found")
    except TaskCannotBeCompletedError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception(
            "Failed to update task status",
            extra={
                "user_id": str(current_user.id),
                "task_id": str(task_id),
                "status": status_data.status,
            },
        )
        if settings.debug:
            raise
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@resource_router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete a task."""
    try:
        await task_service.delete_task(
            db=db,
            user_id=current_user.id,
            task_id=task_id,
            hard_delete=False,
            run_async=True,
        )
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="Task not found")
    except Exception:
        logger.exception(
            "Failed to delete task",
            extra={
                "user_id": str(current_user.id),
                "task_id": str(task_id),
                "hard_delete": False,
            },
        )
        if settings.debug:
            raise
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@collection_router.post("/reorder", status_code=status.HTTP_200_OK)
async def reorder_tasks(
    reorder_data: TaskReorderRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """
    Reorder multiple tasks

    Args:
        reorder_data: Task reordering data
        db: Database session
    """
    try:
        await task_service.reorder_tasks(
            db=db,
            user_id=current_user.id,
            reorder_data=reorder_data,
        )
    except TaskNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception:
        logger.exception(
            "Failed to reorder tasks",
            extra={
                "user_id": str(current_user.id),
                "reorder_count": len(reorder_data.tasks),
            },
        )
        if settings.debug:
            raise
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@resource_router.post("/move", response_model=TaskMoveResponse)
async def move_task(
    task_id: UUID,
    move_data: TaskMoveRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> TaskResponse:
    """
    Move a task to a different parent or vision

    Args:
        task_id: Task ID
        move_data: Move operation data
        db: Database session

    Returns:
        Updated task
    """
    try:
        result = await task_service.move_task(
            db=db,
            user_id=current_user.id,
            task_id=task_id,
            move_data=move_data,
            run_async=True,
        )
        task_schema = TaskResponse.model_validate(result.task)
        descendant_schemas = [
            TaskResponse.model_validate(descendant)
            for descendant in result.updated_descendants
        ]
        return TaskMoveResponse(
            **task_schema.model_dump(),
            updated_descendants=descendant_schemas,
        )
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="Task not found")
    except VisionNotFoundError:
        raise HTTPException(status_code=404, detail="New vision not found")
    except ParentTaskNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except CircularReferenceError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except InvalidTaskDepthError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except InvalidOperationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception(
            "Failed to move task",
            extra={
                "user_id": str(current_user.id),
                "task_id": str(task_id),
                "target_parent": (
                    str(move_data.new_parent_task_id)
                    if move_data.new_parent_task_id
                    else None
                ),
                "target_vision": (
                    str(move_data.new_vision_id) if move_data.new_vision_id else None
                ),
            },
        )
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@resource_router.get("/stats", response_model=TaskStatsResponse)
async def get_task_stats(
    task_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> TaskStatsResponse:
    """
    Get statistics for a task

    Args:
        task_id: Task ID
        db: Database session

    Returns:
        Task statistics
    """
    try:
        return await task_service.get_task_stats(
            db=db, user_id=current_user.id, task_id=task_id
        )
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="Task not found")
    except Exception:
        logger.exception(
            "Failed to get task stats",
            extra={"user_id": str(current_user.id), "task_id": str(task_id)},
        )
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@resource_router.get("/actual-events", response_model=ActualEventListResponse)
async def get_task_actual_events(
    task_id: UUID,
    page: int = Query(1, ge=1),
    size: int = Query(100, ge=1, le=200),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> ActualEventListResponse:
    """
    Get all actual events associated with a specific task

    Args:
        task_id: Task ID
        db: Database session

    Returns:
        List of actual events associated with the task, ordered by start time (newest first)
    """
    try:
        offset = (page - 1) * size
        events, total = await task_service.get_task_actual_events_with_total(
            db=db,
            user_id=current_user.id,
            task_id=task_id,
            limit=size,
            offset=offset,
        )
        pages = (total + size - 1) // size if size else 0
        return ActualEventListResponse(
            items=events,
            pagination={
                "page": page,
                "size": size,
                "total": total,
                "pages": pages,
            },
            meta={
                "task_id": task_id,
                "limit": size,
                "returned_count": len(events),
                "total_count": total,
                "truncated": len(events) < total,
            },
        )
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="Task not found")
    except Exception:
        logger.exception(
            "Failed to get actual events for task",
            extra={"user_id": str(current_user.id), "task_id": str(task_id)},
        )
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


router.include_router(collection_router)
router.include_router(resource_router)
