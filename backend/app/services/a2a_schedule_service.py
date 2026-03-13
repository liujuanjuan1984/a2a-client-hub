"""Facade for user-configurable A2A schedules."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.a2a_schedule_execution import A2AScheduleExecution
from app.db.models.a2a_schedule_task import A2AScheduleTask
from app.services.a2a_schedule_common import (
    A2A_MANUAL_SOURCE,
    A2A_SCHEDULE_SOURCE,
    A2AScheduleConflictError,
    A2AScheduleError,
    A2AScheduleNotFoundError,
    A2AScheduleQuotaError,
    A2AScheduleServiceBusyError,
    A2AScheduleValidationError,
    ClaimedA2AScheduleTask,
)
from app.services.a2a_schedule_crud import A2AScheduleCrudService
from app.services.a2a_schedule_dispatch import A2AScheduleDispatchService
from app.services.a2a_schedule_projection import A2AScheduleProjectionService
from app.services.a2a_schedule_support import A2AScheduleSupport
from app.services.a2a_schedule_time import A2AScheduleTimeHelper


class A2AScheduleService:
    """Stable façade for schedule CRUD, dispatch, and projection workflows."""

    def __init__(self) -> None:
        self._support = A2AScheduleSupport()
        self._time_helper = A2AScheduleTimeHelper()
        self._projection = A2AScheduleProjectionService(
            support=self._support,
            time_helper=self._time_helper,
        )
        self._crud = A2AScheduleCrudService(
            support=self._support,
            time_helper=self._time_helper,
            projection=self._projection,
        )
        self._dispatch = A2AScheduleDispatchService(
            support=self._support,
            time_helper=self._time_helper,
            projection=self._projection,
        )

    async def list_tasks(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        page: int,
        size: int,
    ) -> tuple[list[A2AScheduleTask], int]:
        return await self._crud.list_tasks(db, user_id=user_id, page=page, size=size)

    async def get_task(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        task_id: UUID,
    ) -> A2AScheduleTask:
        return await self._crud.get_task(db, user_id=user_id, task_id=task_id)

    async def create_task(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        is_superuser: bool,
        timezone_str: str,
        name: str,
        agent_id: UUID,
        prompt: str,
        cycle_type: str,
        time_point: dict[str, Any],
        enabled: bool,
        conversation_policy: str = A2AScheduleTask.POLICY_NEW,
    ) -> A2AScheduleTask:
        return await self._crud.create_task(
            db,
            user_id=user_id,
            is_superuser=is_superuser,
            timezone_str=timezone_str,
            name=name,
            agent_id=agent_id,
            prompt=prompt,
            cycle_type=cycle_type,
            time_point=time_point,
            enabled=enabled,
            conversation_policy=conversation_policy,
        )

    async def update_task(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        task_id: UUID,
        is_superuser: bool,
        timezone_str: str,
        name: str | None = None,
        agent_id: UUID | None = None,
        prompt: str | None = None,
        cycle_type: str | None = None,
        time_point: dict[str, Any] | None = None,
        enabled: bool | None = None,
        conversation_policy: str | None = None,
    ) -> A2AScheduleTask:
        return await self._crud.update_task(
            db,
            user_id=user_id,
            task_id=task_id,
            is_superuser=is_superuser,
            timezone_str=timezone_str,
            name=name,
            agent_id=agent_id,
            prompt=prompt,
            cycle_type=cycle_type,
            time_point=time_point,
            enabled=enabled,
            conversation_policy=conversation_policy,
        )

    async def set_enabled(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        task_id: UUID,
        enabled: bool,
        is_superuser: bool,
        timezone_str: str,
    ) -> A2AScheduleTask:
        return await self._crud.set_enabled(
            db,
            user_id=user_id,
            task_id=task_id,
            enabled=enabled,
            is_superuser=is_superuser,
            timezone_str=timezone_str,
        )

    async def delete_task(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        task_id: UUID,
    ) -> None:
        await self._crud.delete_task(db, user_id=user_id, task_id=task_id)

    async def mark_task_failed_manually(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        task_id: UUID,
        marked_by_user_id: UUID,
        reason: str | None = None,
        marked_at: datetime | None = None,
    ) -> A2AScheduleTask:
        return await self._crud.mark_task_failed_manually(
            db,
            user_id=user_id,
            task_id=task_id,
            marked_by_user_id=marked_by_user_id,
            reason=reason,
            marked_at=marked_at,
        )

    async def list_executions(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        task_id: UUID,
        page: int,
        size: int,
    ) -> tuple[list[A2AScheduleExecution], int]:
        return await self._projection.list_executions(
            db,
            user_id=user_id,
            task_id=task_id,
            page=page,
            size=size,
        )

    async def enqueue_due_tasks(
        self,
        db: AsyncSession,
        *,
        now: datetime | None = None,
        batch_size: int = 20,
    ) -> int:
        return await self._dispatch.enqueue_due_tasks(
            db,
            now=now,
            batch_size=batch_size,
        )

    async def claim_next_pending_execution(
        self,
        db: AsyncSession,
        *,
        now: datetime | None = None,
    ) -> ClaimedA2AScheduleTask | None:
        return await self._dispatch.claim_next_pending_execution(db, now=now)

    async def recover_stale_running_tasks(
        self,
        db: AsyncSession,
        *,
        now: datetime | None = None,
        timeout_seconds: int = 600,
        hard_timeout_seconds: int | None = None,
    ) -> int:
        return await self._dispatch.recover_stale_running_tasks(
            db,
            now=now,
            timeout_seconds=timeout_seconds,
            hard_timeout_seconds=hard_timeout_seconds,
        )

    async def finalize_task_run(
        self,
        db: AsyncSession,
        *,
        task_id: UUID,
        user_id: UUID,
        run_id: UUID,
        final_status: str,
        finished_at: datetime,
        conversation_id: UUID | None = None,
        response_content: str | None = None,
        error_message: str | None = None,
        user_message_id: UUID | None = None,
        agent_message_id: UUID | None = None,
    ) -> bool:
        return await self._dispatch.finalize_task_run(
            db,
            task_id=task_id,
            user_id=user_id,
            run_id=run_id,
            final_status=final_status,
            finished_at=finished_at,
            conversation_id=conversation_id,
            response_content=response_content,
            error_message=error_message,
            user_message_id=user_message_id,
            agent_message_id=agent_message_id,
        )

    def format_local_datetime(
        self,
        value: datetime | None,
        *,
        timezone_str: str,
    ) -> str | None:
        return self._time_helper.format_local_datetime(
            value,
            timezone_str=timezone_str,
        )

    def serialize_time_point_for_response(
        self,
        *,
        cycle_type: str,
        time_point: dict[str, Any] | None,
        timezone_str: str,
    ) -> dict[str, Any]:
        return self._time_helper.serialize_time_point_for_response(
            cycle_type=cycle_type,
            time_point=time_point,
            timezone_str=timezone_str,
        )

    def compute_next_run_at(
        self,
        *,
        cycle_type: str,
        time_point: dict[str, Any],
        timezone_str: str,
        after_utc: datetime,
        not_before_utc: datetime | None = None,
        is_superuser: bool = False,
    ) -> datetime:
        return self._time_helper.compute_next_run_at(
            cycle_type=cycle_type,
            time_point=time_point,
            timezone_str=timezone_str,
            after_utc=after_utc,
            not_before_utc=not_before_utc,
            is_superuser=is_superuser,
        )


a2a_schedule_service = A2AScheduleService()

__all__ = [
    "A2A_MANUAL_SOURCE",
    "A2A_SCHEDULE_SOURCE",
    "A2AScheduleConflictError",
    "A2AScheduleError",
    "A2AScheduleNotFoundError",
    "A2AScheduleQuotaError",
    "A2AScheduleServiceBusyError",
    "A2AScheduleService",
    "A2AScheduleValidationError",
    "ClaimedA2AScheduleTask",
    "a2a_schedule_service",
]
