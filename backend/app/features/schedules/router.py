"""Schedule feature API router."""

from __future__ import annotations

from typing import Any, Awaitable, TypeVar, cast
from uuid import UUID

from fastapi import Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.retry_after import db_busy_retry_after_headers
from app.api.routing import StrictAPIRouter
from app.db.models.user import User
from app.features.schedules.schemas import (
    A2AScheduleExecutionListMeta,
    A2AScheduleExecutionListResponse,
    A2AScheduleExecutionResponse,
    A2AScheduleManualFailRequest,
    A2AScheduleStatusSummary,
    A2AScheduleTaskCreate,
    A2AScheduleTaskListMeta,
    A2AScheduleTaskListResponse,
    A2AScheduleTaskResponse,
    A2AScheduleTaskUpdate,
    A2AScheduleToggleResponse,
)
from app.features.schedules.service import (
    A2AScheduleConflictError,
    A2AScheduleNotFoundError,
    A2AScheduleQuotaError,
    A2AScheduleServiceBusyError,
    A2AScheduleValidationError,
    a2a_schedule_service,
)
from app.utils.pagination import build_pagination_meta
from app.utils.timezone_util import TimezoneNotFoundError, validate_user_timezone

router = StrictAPIRouter(prefix="/me/a2a/schedules", tags=["a2a-schedules"])
_ScheduleT = TypeVar("_ScheduleT")


def _validate_timezone(
    user_timezone: str | None, requested_timezone: str | None = None
) -> str:
    try:
        return validate_user_timezone(
            user_timezone=user_timezone, requested_timezone=requested_timezone
        )
    except (ValueError, TimezoneNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


_SCHEDULE_ERROR_STATUS_MAP = {
    A2AScheduleQuotaError: status.HTTP_403_FORBIDDEN,
    A2AScheduleConflictError: status.HTTP_409_CONFLICT,
    A2AScheduleNotFoundError: status.HTTP_404_NOT_FOUND,
    A2AScheduleValidationError: status.HTTP_400_BAD_REQUEST,
}


async def _call_schedule(coro: Awaitable[_ScheduleT]) -> _ScheduleT:
    try:
        return await coro
    except A2AScheduleServiceBusyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
            headers=db_busy_retry_after_headers(),
        ) from exc
    except (
        A2AScheduleQuotaError,
        A2AScheduleConflictError,
        A2AScheduleNotFoundError,
        A2AScheduleValidationError,
    ) as exc:
        for error_type, status_code in _SCHEDULE_ERROR_STATUS_MAP.items():
            if isinstance(exc, error_type):
                raise HTTPException(status_code=status_code, detail=str(exc)) from exc
        raise exc


def _build_task_response(
    task: Any,
    *,
    schedule_timezone: str,
) -> A2AScheduleTaskResponse:
    return A2AScheduleTaskResponse(
        id=task.id,
        name=task.name,
        agent_id=task.agent_id,
        prompt=task.prompt,
        cycle_type=task.cycle_type,
        time_point=a2a_schedule_service.serialize_time_point_for_response(
            cycle_type=task.cycle_type,
            time_point=dict(task.time_point or {}),
            timezone_str=schedule_timezone,
        ),
        schedule_timezone=schedule_timezone,
        conversation_id=task.conversation_id,
        conversation_policy=task.conversation_policy,
        enabled=bool(task.enabled),
        is_running=bool(getattr(task, "is_running", False)),
        next_run_at_utc=task.next_run_at,
        next_run_at_local=a2a_schedule_service.format_local_datetime(
            task.next_run_at,
            timezone_str=schedule_timezone,
        ),
        last_run_at=task.last_run_at,
        last_run_status=task.last_run_status,
        consecutive_failures=int(task.consecutive_failures or 0),
        status_summary=A2AScheduleStatusSummary.model_validate(
            getattr(task, "status_summary", {"state": "idle"})
        ),
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


async def _set_schedule_task_enabled(
    *,
    task_id: UUID,
    enabled: bool,
    db: AsyncSession,
    current_user: User,
) -> A2AScheduleToggleResponse:
    current_user_timezone = cast(str | None, current_user.timezone)
    current_user_id = cast(UUID, current_user.id)
    current_user_is_superuser = cast(bool, current_user.is_superuser)
    schedule_timezone = _validate_timezone(user_timezone=current_user_timezone)
    task = await _call_schedule(
        a2a_schedule_service.set_enabled(
            db,
            user_id=current_user_id,
            task_id=task_id,
            enabled=enabled,
            is_superuser=current_user_is_superuser,
            timezone_str=schedule_timezone,
        )
    )
    task_id_value = cast(UUID, task.id)
    task_next_run_at = cast(object | None, task.next_run_at)
    return A2AScheduleToggleResponse(
        id=task_id_value,
        schedule_timezone=schedule_timezone,
        enabled=bool(task.enabled),
        next_run_at_utc=cast(Any, task_next_run_at),
        next_run_at_local=a2a_schedule_service.format_local_datetime(
            cast(Any, task_next_run_at),
            timezone_str=schedule_timezone,
        ),
    )


@router.post(
    "", response_model=A2AScheduleTaskResponse, status_code=status.HTTP_201_CREATED
)
async def create_schedule_task(
    payload: A2AScheduleTaskCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> A2AScheduleTaskResponse:
    current_user_timezone = cast(str | None, current_user.timezone)
    current_user_id = cast(UUID, current_user.id)
    current_user_is_superuser = cast(bool, current_user.is_superuser)
    schedule_timezone = _validate_timezone(
        user_timezone=current_user_timezone,
        requested_timezone=payload.schedule_timezone,
    )
    task = await _call_schedule(
        a2a_schedule_service.create_task(
            db,
            user_id=current_user_id,
            is_superuser=current_user_is_superuser,
            timezone_str=schedule_timezone,
            name=payload.name,
            agent_id=payload.agent_id,
            prompt=payload.prompt,
            cycle_type=payload.cycle_type,
            time_point=payload.time_point,
            enabled=payload.enabled,
            conversation_policy=payload.conversation_policy,
        )
    )
    return _build_task_response(task, schedule_timezone=schedule_timezone)


@router.get("", response_model=A2AScheduleTaskListResponse)
async def list_schedule_tasks(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> A2AScheduleTaskListResponse:
    current_user_timezone = cast(str | None, current_user.timezone)
    current_user_id = cast(UUID, current_user.id)
    schedule_timezone = _validate_timezone(user_timezone=current_user_timezone)
    items, total = await _call_schedule(
        a2a_schedule_service.list_tasks(
            db,
            user_id=current_user_id,
            page=page,
            size=size,
        )
    )
    return A2AScheduleTaskListResponse(
        items=[
            _build_task_response(item, schedule_timezone=schedule_timezone)
            for item in items
        ],
        pagination=build_pagination_meta(total=total, page=page, size=size),
        meta=A2AScheduleTaskListMeta(),
    )


@router.get("/{task_id}", response_model=A2AScheduleTaskResponse)
async def get_schedule_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> A2AScheduleTaskResponse:
    current_user_timezone = cast(str | None, current_user.timezone)
    current_user_id = cast(UUID, current_user.id)
    schedule_timezone = _validate_timezone(user_timezone=current_user_timezone)
    task = await _call_schedule(
        a2a_schedule_service.get_task(
            db,
            user_id=current_user_id,
            task_id=task_id,
        )
    )
    return _build_task_response(task, schedule_timezone=schedule_timezone)


@router.patch("/{task_id}", response_model=A2AScheduleTaskResponse)
async def patch_schedule_task(
    task_id: UUID,
    payload: A2AScheduleTaskUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> A2AScheduleTaskResponse:
    current_user_timezone = cast(str | None, current_user.timezone)
    current_user_id = cast(UUID, current_user.id)
    current_user_is_superuser = cast(bool, current_user.is_superuser)
    schedule_timezone = _validate_timezone(
        user_timezone=current_user_timezone,
        requested_timezone=payload.schedule_timezone,
    )
    task = await _call_schedule(
        a2a_schedule_service.update_task(
            db,
            user_id=current_user_id,
            task_id=task_id,
            is_superuser=current_user_is_superuser,
            timezone_str=schedule_timezone,
            name=payload.name,
            agent_id=payload.agent_id,
            prompt=payload.prompt,
            cycle_type=payload.cycle_type,
            time_point=payload.time_point,
            enabled=payload.enabled,
            conversation_policy=payload.conversation_policy,
        )
    )

    return _build_task_response(task, schedule_timezone=schedule_timezone)


@router.delete(
    "/{task_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
async def delete_schedule_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    current_user_id = cast(UUID, current_user.id)
    await _call_schedule(
        a2a_schedule_service.delete_task(
            db,
            user_id=current_user_id,
            task_id=task_id,
        )
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{task_id}/enable", response_model=A2AScheduleToggleResponse)
async def enable_schedule_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> A2AScheduleToggleResponse:
    return await _set_schedule_task_enabled(
        task_id=task_id,
        enabled=True,
        db=db,
        current_user=current_user,
    )


@router.post("/{task_id}/disable", response_model=A2AScheduleToggleResponse)
async def disable_schedule_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> A2AScheduleToggleResponse:
    return await _set_schedule_task_enabled(
        task_id=task_id,
        enabled=False,
        db=db,
        current_user=current_user,
    )


@router.post("/{task_id}/mark-failed", response_model=A2AScheduleTaskResponse)
async def mark_schedule_task_failed(
    task_id: UUID,
    payload: A2AScheduleManualFailRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> A2AScheduleTaskResponse:
    current_user_timezone = cast(str | None, current_user.timezone)
    current_user_id = cast(UUID, current_user.id)
    schedule_timezone = _validate_timezone(user_timezone=current_user_timezone)
    task = await _call_schedule(
        a2a_schedule_service.mark_task_failed_manually(
            db,
            user_id=current_user_id,
            task_id=task_id,
            marked_by_user_id=current_user_id,
            reason=payload.reason,
        )
    )
    return _build_task_response(task, schedule_timezone=schedule_timezone)


@router.get("/{task_id}/executions", response_model=A2AScheduleExecutionListResponse)
async def list_schedule_executions(
    task_id: UUID,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> A2AScheduleExecutionListResponse:
    current_user_id = cast(UUID, current_user.id)
    items, total = await _call_schedule(
        a2a_schedule_service.list_executions(
            db,
            user_id=current_user_id,
            task_id=task_id,
            page=page,
            size=size,
        )
    )
    return A2AScheduleExecutionListResponse(
        items=[A2AScheduleExecutionResponse.model_validate(item) for item in items],
        pagination=build_pagination_meta(total=total, page=page, size=size),
        meta=A2AScheduleExecutionListMeta(task_id=task_id),
    )
