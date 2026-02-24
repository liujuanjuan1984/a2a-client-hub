"""REST endpoints for user-configurable scheduled A2A tasks."""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.routing import StrictAPIRouter
from app.db.models.user import User
from app.schemas.a2a_schedule import (
    A2AScheduleExecutionListResponse,
    A2AScheduleExecutionResponse,
    A2AScheduleManualFailRequest,
    A2AScheduleTaskCreate,
    A2AScheduleTaskListResponse,
    A2AScheduleTaskResponse,
    A2AScheduleTaskUpdate,
    A2AScheduleToggleResponse,
)
from app.services.a2a_schedule_service import (
    A2AScheduleConflictError,
    A2AScheduleNotFoundError,
    A2AScheduleQuotaError,
    A2AScheduleValidationError,
    a2a_schedule_service,
)

router = StrictAPIRouter(prefix="/me/a2a/schedules", tags=["a2a-schedules"])


@router.post(
    "", response_model=A2AScheduleTaskResponse, status_code=status.HTTP_201_CREATED
)
async def create_schedule_task(
    payload: A2AScheduleTaskCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> A2AScheduleTaskResponse:
    try:
        task = await a2a_schedule_service.create_task(
            db,
            user_id=current_user.id,
            is_superuser=current_user.is_superuser,
            name=payload.name,
            agent_id=payload.agent_id,
            prompt=payload.prompt,
            timezone=(
                payload.timezone if "timezone" in payload.model_fields_set else None
            ),
            cycle_type=payload.cycle_type,
            time_point=payload.time_point,
            enabled=payload.enabled,
        )
    except A2AScheduleQuotaError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except A2AScheduleValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return A2AScheduleTaskResponse.model_validate(task)


@router.get("", response_model=A2AScheduleTaskListResponse)
async def list_schedule_tasks(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> A2AScheduleTaskListResponse:
    items, total = await a2a_schedule_service.list_tasks(
        db,
        user_id=current_user.id,
        page=page,
        size=size,
    )
    pages = (total + size - 1) // size if size else 0
    return A2AScheduleTaskListResponse(
        items=[A2AScheduleTaskResponse.model_validate(item) for item in items],
        pagination={
            "page": page,
            "size": size,
            "total": total,
            "pages": pages,
        },
        meta={},
    )


@router.get("/{task_id}", response_model=A2AScheduleTaskResponse)
async def get_schedule_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> A2AScheduleTaskResponse:
    try:
        task = await a2a_schedule_service.get_task(
            db,
            user_id=current_user.id,
            task_id=task_id,
        )
    except A2AScheduleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return A2AScheduleTaskResponse.model_validate(task)


@router.patch("/{task_id}", response_model=A2AScheduleTaskResponse)
async def patch_schedule_task(
    task_id: UUID,
    payload: A2AScheduleTaskUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> A2AScheduleTaskResponse:
    """
    Partially update a schedule task.

    NOTE: This endpoint is the only supported partial update API.
    """
    try:
        task = await a2a_schedule_service.update_task(
            db,
            user_id=current_user.id,
            task_id=task_id,
            is_superuser=current_user.is_superuser,
            name=payload.name,
            agent_id=payload.agent_id,
            prompt=payload.prompt,
            timezone=payload.timezone,
            cycle_type=payload.cycle_type,
            time_point=payload.time_point,
            enabled=payload.enabled,
        )
    except A2AScheduleQuotaError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except A2AScheduleConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except A2AScheduleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except A2AScheduleValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return A2AScheduleTaskResponse.model_validate(task)


@router.delete(
    "/{task_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
async def delete_schedule_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    try:
        await a2a_schedule_service.delete_task(
            db,
            user_id=current_user.id,
            task_id=task_id,
        )
    except A2AScheduleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{task_id}/enable", response_model=A2AScheduleToggleResponse)
async def enable_schedule_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> A2AScheduleToggleResponse:
    try:
        task = await a2a_schedule_service.set_enabled(
            db,
            user_id=current_user.id,
            task_id=task_id,
            enabled=True,
            is_superuser=current_user.is_superuser,
        )
    except A2AScheduleQuotaError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except A2AScheduleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except A2AScheduleValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return A2AScheduleToggleResponse(
        id=task.id,
        enabled=bool(task.enabled),
        next_run_at=task.next_run_at,
    )


@router.post("/{task_id}/disable", response_model=A2AScheduleToggleResponse)
async def disable_schedule_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> A2AScheduleToggleResponse:
    try:
        task = await a2a_schedule_service.set_enabled(
            db,
            user_id=current_user.id,
            task_id=task_id,
            enabled=False,
            is_superuser=current_user.is_superuser,
        )
    except A2AScheduleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return A2AScheduleToggleResponse(
        id=task.id,
        enabled=bool(task.enabled),
        next_run_at=task.next_run_at,
    )


@router.post("/{task_id}/mark-failed", response_model=A2AScheduleTaskResponse)
async def mark_schedule_task_failed(
    task_id: UUID,
    payload: A2AScheduleManualFailRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> A2AScheduleTaskResponse:
    try:
        task = await a2a_schedule_service.mark_task_failed_manually(
            db,
            user_id=current_user.id,
            task_id=task_id,
            marked_by_user_id=current_user.id,
            reason=payload.reason,
        )
    except A2AScheduleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except A2AScheduleValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return A2AScheduleTaskResponse.model_validate(task)


@router.get("/{task_id}/executions", response_model=A2AScheduleExecutionListResponse)
async def list_schedule_executions(
    task_id: UUID,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> A2AScheduleExecutionListResponse:
    try:
        items, total = await a2a_schedule_service.list_executions(
            db,
            user_id=current_user.id,
            task_id=task_id,
            page=page,
            size=size,
        )
    except A2AScheduleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    pages = (total + size - 1) // size if size else 0
    return A2AScheduleExecutionListResponse(
        items=[A2AScheduleExecutionResponse.model_validate(item) for item in items],
        pagination={
            "page": page,
            "size": size,
            "total": total,
            "pages": pages,
        },
        meta={"task_id": task_id},
    )
