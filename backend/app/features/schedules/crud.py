"""CRUD-oriented operations for A2A schedules."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.a2a_schedule_execution import A2AScheduleExecution
from app.db.models.a2a_schedule_task import A2AScheduleTask
from app.db.transaction import commit_safely
from app.features.schedules.common import (
    A2AScheduleConflictError,
    A2AScheduleNotFoundError,
    A2AScheduleValidationError,
    map_retryable_db_errors,
)
from app.features.schedules.projection import A2AScheduleProjectionService
from app.features.schedules.support import A2AScheduleSupport
from app.features.schedules.time import A2AScheduleTimeHelper
from app.utils.timezone_util import ensure_utc, utc_now

_MANUAL_FAILURE_MESSAGE = "Stopped by user as failed"
_MANUAL_FAILURE_ERROR_CODE = "manual_failed"


class A2AScheduleCrudService:
    """Task CRUD, validation, and quota enforcement."""

    def __init__(
        self,
        *,
        support: A2AScheduleSupport,
        time_helper: A2AScheduleTimeHelper,
        projection: A2AScheduleProjectionService,
    ) -> None:
        self._support = support
        self._time_helper = time_helper
        self._projection = projection

    @map_retryable_db_errors("Schedule task list")
    async def list_tasks(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        page: int,
        size: int,
    ) -> tuple[list[A2AScheduleTask], int]:
        return await self._projection.list_tasks_with_status_summary(
            db,
            user_id=user_id,
            page=page,
            size=size,
        )

    @map_retryable_db_errors("Schedule task read")
    async def get_task(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        task_id: UUID,
    ) -> A2AScheduleTask:
        task = await self._support.get_task(db, user_id=user_id, task_id=task_id)
        return await self._projection.set_task_status_projection(db, task=task)

    @map_retryable_db_errors("Schedule task creation")
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
        await self._support.apply_nowait_write_timeouts(db)
        await self._support.ensure_agent_owned(db, user_id=user_id, agent_id=agent_id)
        if enabled:
            await self._support.lock_user_row_for_quota(db, user_id=user_id)
            await self._support.ensure_active_quota(
                db, user_id=user_id, is_superuser=is_superuser
            )

        normalized_name = self._time_helper.normalize_name(name)
        normalized_prompt = self._time_helper.normalize_prompt(prompt)
        normalized_cycle = self._time_helper.normalize_cycle_type(cycle_type)
        normalized_conversation_policy = (
            self._time_helper.normalize_conversation_policy(conversation_policy)
        )
        timezone_value = self._time_helper.normalize_timezone_str(timezone_str)
        normalized_point = self._time_helper.normalize_time_point(
            cycle_type=normalized_cycle,
            time_point=time_point,
            is_superuser=is_superuser,
            timezone_str=timezone_value,
        )

        next_run_at: datetime | None = None
        if enabled:
            next_run_at = self._time_helper.compute_next_run_at(
                cycle_type=normalized_cycle,
                time_point=normalized_point,
                timezone_str=timezone_value,
                after_utc=utc_now(),
                is_superuser=is_superuser,
            )

        task = A2AScheduleTask(
            user_id=user_id,
            name=normalized_name,
            agent_id=agent_id,
            prompt=normalized_prompt,
            cycle_type=normalized_cycle,
            time_point=normalized_point,
            conversation_policy=normalized_conversation_policy,
            enabled=enabled,
            next_run_at=next_run_at,
            last_run_status=A2AScheduleTask.STATUS_IDLE,
        )
        db.add(task)
        await commit_safely(db)
        await db.refresh(task)
        return await self._projection.set_task_status_projection(db, task=task)

    @map_retryable_db_errors("Schedule task update")
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
        await self._support.apply_nowait_write_timeouts(db)
        await self._support.lock_user_row_for_quota(db, user_id=user_id)
        task = await self._support.get_task_for_update(
            db, user_id=user_id, task_id=task_id
        )
        timezone_value = self._time_helper.normalize_timezone_str(timezone_str)
        task_id_value = cast(UUID, task.id)
        task_user_id = cast(UUID, task.user_id)

        if (
            await self._projection.get_running_execution(
                db,
                task_id=task_id_value,
                user_id=task_user_id,
            )
            is not None
        ):
            raise A2AScheduleConflictError(
                "Task is currently running and cannot be edited."
            )

        if enabled is True and not cast(bool, task.enabled):
            await self._support.ensure_active_quota(
                db, user_id=user_id, is_superuser=is_superuser
            )

        if name is not None:
            setattr(task, "name", self._time_helper.normalize_name(name))

        if prompt is not None:
            setattr(task, "prompt", self._time_helper.normalize_prompt(prompt))

        if agent_id is not None:
            await self._support.ensure_agent_owned(
                db, user_id=user_id, agent_id=agent_id
            )
            setattr(task, "agent_id", agent_id)

        next_cycle_type = cast(str, task.cycle_type)
        next_time_point = dict(cast(dict[str, Any] | None, task.time_point) or {})

        if cycle_type is not None:
            next_cycle_type = self._time_helper.normalize_cycle_type(cycle_type)

        if time_point is not None:
            next_time_point = dict(time_point)

        schedule_changed = (cycle_type is not None) or (time_point is not None)
        if schedule_changed:
            normalized_point = self._time_helper.normalize_time_point(
                cycle_type=next_cycle_type,
                time_point=next_time_point,
                is_superuser=is_superuser,
                timezone_str=timezone_value,
            )
            setattr(task, "cycle_type", next_cycle_type)
            setattr(task, "time_point", normalized_point)

        if enabled is not None:
            setattr(task, "enabled", enabled)

        if conversation_policy is not None:
            setattr(
                task,
                "conversation_policy",
                self._time_helper.normalize_conversation_policy(conversation_policy),
            )

        should_recompute = False
        if cast(bool, task.enabled) and (schedule_changed or enabled is True):
            should_recompute = True
        if not cast(bool, task.enabled):
            setattr(task, "next_run_at", None)

        if should_recompute:
            setattr(
                task,
                "next_run_at",
                self._time_helper.compute_next_run_at(
                    cycle_type=cast(str, task.cycle_type),
                    time_point=dict(cast(dict[str, Any] | None, task.time_point) or {}),
                    timezone_str=timezone_value,
                    after_utc=utc_now(),
                    is_superuser=is_superuser,
                ),
            )

        await commit_safely(db)
        await db.refresh(task)
        setattr(task, "is_running", False)
        return task

    @map_retryable_db_errors("Schedule task toggle")
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
        await self._support.apply_nowait_write_timeouts(db)
        await self._support.lock_user_row_for_quota(db, user_id=user_id)
        task = await self._support.get_task_for_update(
            db, user_id=user_id, task_id=task_id
        )
        if enabled and not cast(bool, task.enabled):
            await self._support.ensure_active_quota(
                db, user_id=user_id, is_superuser=is_superuser
            )

        setattr(task, "enabled", enabled)
        if enabled:
            timezone_value = self._time_helper.normalize_timezone_str(timezone_str)
            setattr(
                task,
                "next_run_at",
                self._time_helper.compute_next_run_at(
                    cycle_type=cast(str, task.cycle_type),
                    time_point=dict(cast(dict[str, Any] | None, task.time_point) or {}),
                    timezone_str=timezone_value,
                    after_utc=utc_now(),
                    is_superuser=is_superuser,
                ),
            )
        else:
            setattr(task, "next_run_at", None)

        await commit_safely(db)
        await db.refresh(task)
        return await self._projection.set_task_status_projection(db, task=task)

    @map_retryable_db_errors("Schedule task deletion")
    async def delete_task(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        task_id: UUID,
    ) -> None:
        await self._support.apply_nowait_write_timeouts(db)
        task = await self._support.get_task_for_update(
            db, user_id=user_id, task_id=task_id
        )
        task_id_value = cast(UUID, task.id)
        task_user_id = cast(UUID, task.user_id)
        running_execution = await self._projection.get_running_execution(
            db,
            task_id=task_id_value,
            user_id=task_user_id,
        )
        if running_execution is not None:
            setattr(task, "delete_requested_at", utc_now())
            setattr(task, "enabled", False)
            setattr(task, "next_run_at", None)
        else:
            task.soft_delete()
            setattr(task, "enabled", False)
            setattr(task, "next_run_at", None)
            setattr(task, "delete_requested_at", None)
        await commit_safely(db)

    @map_retryable_db_errors("Schedule task manual fail")
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
        del marked_by_user_id

        await self._support.apply_nowait_write_timeouts(db)
        now_utc = ensure_utc(marked_at or utc_now())
        manual_error_message = self.build_manual_failure_reason(reason=reason)

        stmt = (
            select(A2AScheduleTask)
            .where(
                and_(
                    A2AScheduleTask.id == task_id,
                    A2AScheduleTask.user_id == user_id,
                    A2AScheduleTask.deleted_at.is_(None),
                    A2AScheduleTask.delete_requested_at.is_(None),
                )
            )
            .with_for_update(nowait=True)
            .limit(1)
        )
        task = cast(A2AScheduleTask | None, await db.scalar(stmt))
        if task is None:
            raise A2AScheduleNotFoundError("Schedule task not found")

        task_id_value = cast(UUID, task.id)
        task_user_id = cast(UUID, task.user_id)
        execution = await self._projection.get_running_execution(
            db,
            task_id=task_id_value,
            user_id=task_user_id,
            for_update=True,
        )
        if execution is None:
            if cast(str, task.last_run_status) == A2AScheduleTask.STATUS_FAILED:
                return await self._projection.set_task_status_projection(db, task=task)
            raise A2AScheduleValidationError(
                "Only running tasks can be manually marked as failed"
            )

        finished_at = cast(datetime | None, execution.finished_at)
        if finished_at is None:
            setattr(execution, "finished_at", now_utc)
        setattr(execution, "status", A2AScheduleExecution.STATUS_FAILED)
        setattr(execution, "error_message", manual_error_message)
        setattr(execution, "error_code", _MANUAL_FAILURE_ERROR_CODE)
        conversation_id = cast(UUID | None, execution.conversation_id)
        if conversation_id is None:
            setattr(
                execution, "conversation_id", cast(UUID | None, task.conversation_id)
            )

        threshold = max(int(settings.a2a_schedule_task_failure_threshold), 1)
        self._projection.apply_task_terminal_projection(
            task,
            final_status=A2AScheduleTask.STATUS_FAILED,
            finished_at=now_utc,
            failure_threshold=threshold,
        )

        await commit_safely(db)
        await db.refresh(task)
        return await self._projection.set_task_status_projection(db, task=task)

    @staticmethod
    def build_manual_failure_reason(
        *,
        reason: str | None,
    ) -> str:
        normalized_reason = (reason or "").strip()
        return normalized_reason or _MANUAL_FAILURE_MESSAGE
