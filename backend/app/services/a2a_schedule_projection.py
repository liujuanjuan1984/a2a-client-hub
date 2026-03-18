"""Projection helpers for A2A schedule task state."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.a2a_schedule_execution import A2AScheduleExecution
from app.db.models.a2a_schedule_task import A2AScheduleTask
from app.services.a2a_schedule_common import A2AScheduleValidationError
from app.services.a2a_schedule_runtime_summary import build_schedule_status_summary
from app.services.a2a_schedule_support import A2AScheduleSupport
from app.services.a2a_schedule_time import A2AScheduleTimeHelper
from app.utils.timezone_util import ensure_utc


class A2AScheduleProjectionService:
    """Read-model and terminal state projection helpers."""

    def __init__(
        self,
        *,
        support: A2AScheduleSupport,
        time_helper: A2AScheduleTimeHelper,
    ) -> None:
        self._support = support
        self._time_helper = time_helper

    async def get_running_execution(
        self,
        db: AsyncSession,
        *,
        task_id: UUID,
        user_id: UUID,
        for_update: bool = False,
    ) -> A2AScheduleExecution | None:
        stmt = (
            select(A2AScheduleExecution)
            .where(
                and_(
                    A2AScheduleExecution.task_id == task_id,
                    A2AScheduleExecution.user_id == user_id,
                    A2AScheduleExecution.status == A2AScheduleExecution.STATUS_RUNNING,
                )
            )
            .order_by(A2AScheduleExecution.id.asc())
            .limit(1)
        )
        if for_update:
            stmt = stmt.with_for_update(nowait=True)
        return await db.scalar(stmt)

    async def set_task_running_projection(
        self,
        db: AsyncSession,
        *,
        task: A2AScheduleTask,
    ) -> A2AScheduleTask:
        running_execution = await self.get_running_execution(
            db,
            task_id=task.id,
            user_id=task.user_id,
        )
        setattr(task, "is_running", running_execution is not None)
        latest_execution = await self._get_latest_execution(
            db,
            task_id=task.id,
            user_id=task.user_id,
        )
        setattr(
            task,
            "status_summary",
            build_schedule_status_summary(
                running_execution=running_execution,
                latest_execution=latest_execution,
            ),
        )
        return task

    async def set_tasks_running_projection(
        self,
        db: AsyncSession,
        *,
        tasks: list[A2AScheduleTask],
    ) -> None:
        if not tasks:
            return

        task_ids = [task.id for task in tasks]
        running_executions = {
            execution.task_id: execution
            for execution in (
                await db.scalars(
                    select(A2AScheduleExecution)
                    .where(
                        A2AScheduleExecution.task_id.in_(task_ids),
                        A2AScheduleExecution.user_id == tasks[0].user_id,
                        A2AScheduleExecution.status
                        == A2AScheduleExecution.STATUS_RUNNING,
                    )
                    .order_by(
                        A2AScheduleExecution.started_at.asc(),
                        A2AScheduleExecution.id.asc(),
                    )
                )
            ).all()
        }
        latest_executions = await self._get_latest_executions_for_tasks(
            db,
            user_id=tasks[0].user_id,
            task_ids=task_ids,
        )
        for task in tasks:
            running_execution = running_executions.get(task.id)
            setattr(task, "is_running", running_execution is not None)
            setattr(
                task,
                "status_summary",
                build_schedule_status_summary(
                    running_execution=running_execution,
                    latest_execution=latest_executions.get(task.id),
                ),
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
        await self._support.get_task(db, user_id=user_id, task_id=task_id)

        offset = (page - 1) * size
        stmt = (
            select(A2AScheduleExecution)
            .where(
                A2AScheduleExecution.user_id == user_id,
                A2AScheduleExecution.task_id == task_id,
            )
            .order_by(
                A2AScheduleExecution.started_at.desc(),
                A2AScheduleExecution.id.desc(),
            )
            .offset(offset)
            .limit(size)
        )
        rows = await db.execute(stmt)
        items = list(rows.scalars().all())

        count_stmt = select(func.count(A2AScheduleExecution.id)).where(
            A2AScheduleExecution.user_id == user_id,
            A2AScheduleExecution.task_id == task_id,
        )
        total = int(await db.scalar(count_stmt) or 0)
        return items, total

    async def _get_latest_execution(
        self,
        db: AsyncSession,
        *,
        task_id: UUID,
        user_id: UUID,
    ) -> A2AScheduleExecution | None:
        stmt = (
            select(A2AScheduleExecution)
            .where(
                A2AScheduleExecution.user_id == user_id,
                A2AScheduleExecution.task_id == task_id,
            )
            .order_by(
                func.coalesce(
                    A2AScheduleExecution.started_at,
                    A2AScheduleExecution.scheduled_for,
                ).desc(),
                A2AScheduleExecution.id.desc(),
            )
            .limit(1)
        )
        return await db.scalar(stmt)

    async def _get_latest_executions_for_tasks(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        task_ids: list[UUID],
    ) -> dict[UUID, A2AScheduleExecution]:
        if not task_ids:
            return {}

        ranked_executions = (
            select(
                A2AScheduleExecution.id.label("execution_id"),
                A2AScheduleExecution.task_id.label("task_id"),
                func.row_number()
                .over(
                    partition_by=A2AScheduleExecution.task_id,
                    order_by=(
                        func.coalesce(
                            A2AScheduleExecution.started_at,
                            A2AScheduleExecution.scheduled_for,
                        ).desc(),
                        A2AScheduleExecution.id.desc(),
                    ),
                )
                .label("row_number"),
            )
            .where(
                A2AScheduleExecution.user_id == user_id,
                A2AScheduleExecution.task_id.in_(task_ids),
            )
            .subquery()
        )
        stmt = (
            select(A2AScheduleExecution)
            .join(
                ranked_executions,
                ranked_executions.c.execution_id == A2AScheduleExecution.id,
            )
            .where(ranked_executions.c.row_number == 1)
        )
        return {
            execution.task_id: execution for execution in (await db.scalars(stmt)).all()
        }

    def apply_task_terminal_projection(
        self,
        task: A2AScheduleTask,
        *,
        final_status: str,
        finished_at: datetime,
        failure_threshold: int,
        conversation_id: UUID | None = None,
    ) -> None:
        finished_at_utc = ensure_utc(finished_at)
        task.last_run_status = final_status
        task.last_run_at = finished_at_utc
        if conversation_id is not None:
            task.conversation_id = conversation_id

        if final_status == A2AScheduleTask.STATUS_SUCCESS:
            task.consecutive_failures = 0
        elif final_status == A2AScheduleTask.STATUS_FAILED:
            task.consecutive_failures = (task.consecutive_failures or 0) + 1
            if task.consecutive_failures >= failure_threshold:
                task.enabled = False
        else:
            raise A2AScheduleValidationError("Unsupported final status for task run")

        if task.delete_requested_at is not None:
            task.soft_delete()
            task.enabled = False
            task.next_run_at = None
            task.delete_requested_at = None
        elif task.cycle_type == A2AScheduleTask.CYCLE_SEQUENTIAL:
            if task.enabled:
                task.next_run_at = self._time_helper.compute_sequential_next_run_at(
                    time_point=dict(task.time_point or {}),
                    after_utc=finished_at_utc,
                )
            else:
                task.next_run_at = None
