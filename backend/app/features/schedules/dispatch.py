"""Dispatch and recovery operations for A2A schedules."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.locking import to_retryable_db_lock_error
from app.db.models.a2a_schedule_execution import A2AScheduleExecution
from app.db.models.a2a_schedule_task import A2AScheduleTask
from app.db.models.user import User
from app.db.transaction import commit_safely
from app.features.schedules.common import (
    A2AScheduleValidationError,
    ClaimedA2AScheduleTask,
    map_retryable_db_errors,
)
from app.features.schedules.projection import A2AScheduleProjectionService
from app.features.schedules.support import A2AScheduleSupport
from app.features.schedules.time import A2AScheduleTimeHelper
from app.services.ops_metrics import ops_metrics
from app.utils.timezone_util import ensure_utc, utc_now

logger = get_logger(__name__)


class A2AScheduleDispatchService:
    """Claim, finalize, and recovery behavior for scheduled runs."""

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

    async def global_running_execution_count(
        self,
        db: AsyncSession,
    ) -> int:
        stmt = select(func.count(A2AScheduleExecution.id)).where(
            A2AScheduleExecution.status == A2AScheduleExecution.STATUS_RUNNING
        )
        return int((await db.scalar(stmt)) or 0)

    async def enqueue_due_tasks(
        self,
        db: AsyncSession,
        *,
        now: datetime | None = None,
        batch_size: int = 20,
    ) -> int:
        await self._support.apply_nowait_write_timeouts(db)
        now_utc = ensure_utc(now or utc_now())

        user_timezone_subquery = (
            select(User.timezone)
            .where(User.id == A2AScheduleTask.user_id)
            .limit(1)
            .scalar_subquery()
        )
        user_is_superuser_subquery = (
            select(User.is_superuser)
            .where(User.id == A2AScheduleTask.user_id)
            .limit(1)
            .scalar_subquery()
        )

        has_pending_subquery = (
            select(1)
            .where(
                and_(
                    A2AScheduleExecution.task_id == A2AScheduleTask.id,
                    A2AScheduleExecution.status.in_(
                        [
                            A2AScheduleExecution.STATUS_PENDING,
                            A2AScheduleExecution.STATUS_RUNNING,
                        ]
                    ),
                )
            )
            .limit(1)
            .scalar_subquery()
            .exists()
        )

        stmt = (
            select(
                A2AScheduleTask,
                user_timezone_subquery.label("user_timezone"),
                user_is_superuser_subquery.label("user_is_superuser"),
            )
            .where(
                and_(
                    A2AScheduleTask.deleted_at.is_(None),
                    A2AScheduleTask.delete_requested_at.is_(None),
                    A2AScheduleTask.enabled.is_(True),
                    A2AScheduleTask.next_run_at.is_not(None),
                    A2AScheduleTask.next_run_at <= now_utc,
                    ~has_pending_subquery,
                )
            )
            .order_by(A2AScheduleTask.next_run_at.asc(), A2AScheduleTask.id.asc())
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )

        rows = await db.execute(stmt)
        enqueued_count = 0

        for row in rows:
            selected_task = row[0]
            timezone_value = self._time_helper.normalize_timezone_str(row[1])
            is_superuser = bool(row[2])

            scheduled_for = ensure_utc(selected_task.next_run_at or now_utc)
            if selected_task.cycle_type == A2AScheduleTask.CYCLE_SEQUENTIAL:
                next_run_at = None
            else:
                next_run_at = self._time_helper.compute_next_run_at(
                    cycle_type=selected_task.cycle_type,
                    time_point=dict(selected_task.time_point or {}),
                    timezone_str=timezone_value,
                    after_utc=scheduled_for,
                    not_before_utc=now_utc,
                    is_superuser=is_superuser,
                )

            run_id = uuid4()
            selected_task.next_run_at = next_run_at

            db.add(
                A2AScheduleExecution(
                    user_id=selected_task.user_id,
                    task_id=selected_task.id,
                    run_id=run_id,
                    scheduled_for=scheduled_for,
                    started_at=None,
                    last_heartbeat_at=None,
                    status=A2AScheduleExecution.STATUS_PENDING,
                    conversation_id=selected_task.conversation_id,
                )
            )
            enqueued_count += 1
            logger.info("Task %s enqueued, run_id: %s", selected_task.id, run_id)

        await commit_safely(db)
        return enqueued_count

    async def claim_next_pending_execution(
        self,
        db: AsyncSession,
        *,
        now: datetime | None = None,
    ) -> ClaimedA2AScheduleTask | None:
        await self._support.apply_skip_locked_write_timeouts(db)
        now_utc = ensure_utc(now or utc_now())

        global_concurrency_limit = max(
            int(settings.a2a_schedule_global_concurrency_limit), 1
        )
        global_running_count = await self.global_running_execution_count(db)
        if global_running_count >= global_concurrency_limit:
            return None

        concurrency_limit = max(int(settings.a2a_schedule_agent_concurrency_limit), 1)

        from sqlalchemy.orm import aliased

        task_alias = aliased(A2AScheduleTask)
        exec_alias = aliased(A2AScheduleExecution)

        running_count_subquery = (
            select(func.count(exec_alias.id))
            .join(task_alias, task_alias.id == exec_alias.task_id)
            .where(
                and_(
                    task_alias.agent_id == A2AScheduleTask.agent_id,
                    exec_alias.status == A2AScheduleExecution.STATUS_RUNNING,
                )
            )
            .correlate(A2AScheduleTask)
            .scalar_subquery()
        )

        stmt = (
            select(A2AScheduleExecution)
            .join(A2AScheduleTask, A2AScheduleTask.id == A2AScheduleExecution.task_id)
            .where(
                and_(
                    A2AScheduleExecution.status == A2AScheduleExecution.STATUS_PENDING,
                    or_(
                        A2AScheduleTask.deleted_at.is_not(None),
                        A2AScheduleTask.enabled.is_(False),
                        running_count_subquery < concurrency_limit,
                    ),
                )
            )
            .order_by(
                A2AScheduleExecution.scheduled_for.asc(), A2AScheduleExecution.id.asc()
            )
            .limit(1)
            .with_for_update(of=A2AScheduleExecution, skip_locked=True)
        )
        execution = cast(A2AScheduleExecution | None, await db.scalar(stmt))
        if execution is None:
            return None

        task_stmt = (
            select(A2AScheduleTask)
            .where(A2AScheduleTask.id == execution.task_id)
            .with_for_update(nowait=True)
            .limit(1)
        )
        try:
            task = cast(A2AScheduleTask | None, await db.scalar(task_stmt))
        except DBAPIError as exc:
            if (
                to_retryable_db_lock_error(
                    exc,
                    lock_message="Schedule task row is locked by another operation.",
                )
                is not None
            ):
                await db.rollback()
                return None
            raise
        task_deleted_at = (
            cast(datetime | None, task.deleted_at) if task is not None else None
        )
        task_enabled = cast(bool, task.enabled) if task is not None else False
        if task is None or task_deleted_at is not None or not task_enabled:
            setattr(execution, "status", A2AScheduleExecution.STATUS_FAILED)
            setattr(execution, "finished_at", now_utc)
            setattr(
                execution,
                "error_message",
                "Task disabled or deleted before execution started",
            )
            await commit_safely(db)
            return None

        setattr(execution, "status", A2AScheduleExecution.STATUS_RUNNING)
        setattr(execution, "started_at", now_utc)
        setattr(execution, "last_heartbeat_at", now_utc)

        await commit_safely(db)

        return ClaimedA2AScheduleTask(
            task_id=cast(UUID, task.id),
            user_id=cast(UUID, task.user_id),
            agent_id=cast(UUID, task.agent_id),
            conversation_id=cast(UUID | None, execution.conversation_id)
            or cast(UUID | None, task.conversation_id),
            name=cast(str, task.name),
            prompt=cast(str, task.prompt),
            cycle_type=cast(str, task.cycle_type),
            time_point=dict(cast(dict[str, Any] | None, task.time_point) or {}),
            scheduled_for=cast(datetime, execution.scheduled_for),
            run_id=cast(UUID, execution.run_id),
        )

    async def recover_stale_running_tasks(
        self,
        db: AsyncSession,
        *,
        now: datetime | None = None,
        timeout_seconds: int = 600,
        hard_timeout_seconds: int | None = None,
    ) -> int:
        now_utc = ensure_utc(now or utc_now())
        timeout_seconds = max(int(timeout_seconds or 0), 1)
        cutoff = now_utc - timedelta(seconds=timeout_seconds)
        hard_timeout = (
            max(int(hard_timeout_seconds or 0), 1) if hard_timeout_seconds else None
        )
        hard_cutoff = (
            now_utc - timedelta(seconds=hard_timeout)
            if hard_timeout is not None
            else None
        )
        failure_threshold = max(int(settings.a2a_schedule_task_failure_threshold), 1)

        stale_predicates = [
            func.coalesce(
                A2AScheduleExecution.last_heartbeat_at,
                A2AScheduleExecution.started_at,
            )
            <= cutoff
        ]
        if hard_cutoff is not None:
            stale_predicates.append(A2AScheduleExecution.started_at <= hard_cutoff)

        error_message = "Execution marked as failed by recovery: stale running task exceeded timeout"
        error_code = "timeout"
        recovered_count = 0
        while True:
            await self._support.apply_skip_locked_write_timeouts(db)
            stale_where = and_(
                A2AScheduleExecution.status == A2AScheduleExecution.STATUS_RUNNING,
                A2AScheduleTask.deleted_at.is_(None),
                or_(*stale_predicates),
            )
            stmt = (
                select(A2AScheduleExecution)
                .join(
                    A2AScheduleTask, A2AScheduleTask.id == A2AScheduleExecution.task_id
                )
                .where(stale_where)
                .order_by(
                    A2AScheduleExecution.started_at.asc(),
                    A2AScheduleExecution.id.asc(),
                )
                .limit(1)
                .with_for_update(of=A2AScheduleExecution, skip_locked=True)
            )
            execution = cast(A2AScheduleExecution | None, await db.scalar(stmt))
            if execution is None:
                stale_count_stmt = (
                    select(func.count(A2AScheduleExecution.id))
                    .join(
                        A2AScheduleTask,
                        A2AScheduleTask.id == A2AScheduleExecution.task_id,
                    )
                    .where(stale_where)
                )
                stale_remaining = int(await db.scalar(stale_count_stmt) or 0)
                if stale_remaining > 0:
                    ops_metrics.increment_schedule_recovery_lock_skipped_tasks(
                        stale_remaining
                    )
                    logger.warning(
                        "Skipped recovery for %d stale schedule task(s) due to row lock contention; retry next cycle.",
                        stale_remaining,
                        extra={
                            "phase": "recovery",
                            "stale_task_count": stale_remaining,
                        },
                    )
                break

            task_stmt = (
                select(A2AScheduleTask)
                .where(A2AScheduleTask.id == execution.task_id)
                .with_for_update(nowait=True)
            )
            try:
                task = cast(A2AScheduleTask | None, await db.scalar(task_stmt))
            except DBAPIError as exc:
                if (
                    to_retryable_db_lock_error(
                        exc,
                        lock_message="Schedule task row is locked during stale recovery.",
                    )
                    is not None
                ):
                    await db.rollback()
                    continue
                raise

            if task is None:
                await commit_safely(db)
                continue

            setattr(execution, "status", A2AScheduleExecution.STATUS_FAILED)
            setattr(execution, "finished_at", now_utc)
            setattr(execution, "error_message", error_message)
            setattr(execution, "error_code", error_code)
            conversation_id = cast(UUID | None, execution.conversation_id)
            if conversation_id is None:
                setattr(
                    execution,
                    "conversation_id",
                    cast(UUID | None, task.conversation_id),
                )

            self._projection.apply_task_terminal_projection(
                task,
                final_status=A2AScheduleTask.STATUS_FAILED,
                finished_at=now_utc,
                failure_threshold=failure_threshold,
                conversation_id=cast(UUID | None, execution.conversation_id),
            )
            recovered_count += 1

            await commit_safely(db)
        return recovered_count

    @map_retryable_db_errors("Schedule task finalize")
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
        error_code: str | None = None,
        user_message_id: UUID | None = None,
        agent_message_id: UUID | None = None,
    ) -> bool:
        await self._support.apply_nowait_write_timeouts(db)

        exec_stmt = (
            select(A2AScheduleExecution)
            .where(
                and_(
                    A2AScheduleExecution.task_id == task_id,
                    A2AScheduleExecution.user_id == user_id,
                    A2AScheduleExecution.run_id == run_id,
                    A2AScheduleExecution.status == A2AScheduleExecution.STATUS_RUNNING,
                )
            )
            .with_for_update(nowait=True)
            .limit(1)
        )
        execution = cast(A2AScheduleExecution | None, await db.scalar(exec_stmt))
        if execution is None:
            return False

        stmt = (
            select(A2AScheduleTask)
            .where(
                and_(
                    A2AScheduleTask.id == task_id,
                    A2AScheduleTask.user_id == user_id,
                )
            )
            .with_for_update(nowait=True)
            .limit(1)
        )
        task = cast(A2AScheduleTask | None, await db.scalar(stmt))
        if task is None:
            return False

        threshold = max(int(settings.a2a_schedule_task_failure_threshold), 1)
        if final_status not in {
            A2AScheduleTask.STATUS_SUCCESS,
            A2AScheduleTask.STATUS_FAILED,
        }:
            raise A2AScheduleValidationError("Unsupported final status for task run")

        setattr(execution, "status", final_status)
        setattr(execution, "finished_at", ensure_utc(finished_at))
        setattr(execution, "conversation_id", conversation_id)
        setattr(execution, "response_content", response_content)
        setattr(execution, "error_message", error_message)
        setattr(execution, "error_code", error_code)
        setattr(execution, "user_message_id", user_message_id)
        setattr(execution, "agent_message_id", agent_message_id)
        self._projection.apply_task_terminal_projection(
            task,
            final_status=final_status,
            finished_at=finished_at,
            failure_threshold=threshold,
            conversation_id=conversation_id,
        )

        logger.info(
            "Task %s finalized (run_id: %s) with status: %s, conv: %s",
            task_id,
            run_id,
            final_status,
            conversation_id,
        )

        return True
