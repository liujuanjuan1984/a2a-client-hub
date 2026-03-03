"""Business logic for user-configurable A2A schedules."""

from __future__ import annotations

import calendar
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from functools import wraps
from typing import Any, Dict, Optional, TypeVar
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.config import settings
from app.core.logging import get_logger
from app.db.locking import (
    set_postgres_local_timeouts,
    to_retryable_db_lock_error,
    to_retryable_db_query_timeout_error,
)
from app.db.models.a2a_agent import A2AAgent
from app.db.models.a2a_schedule_execution import A2AScheduleExecution
from app.db.models.a2a_schedule_task import A2AScheduleTask
from app.db.models.user import User
from app.db.transaction import commit_safely
from app.services.ops_metrics import ops_metrics
from app.utils.timezone_util import ensure_utc, resolve_timezone, utc_now

_MANUAL_FAILURE_MESSAGE = "Stopped by user as failed"
logger = get_logger(__name__)


class A2AScheduleError(RuntimeError):
    """Base error for A2A schedule operations."""


class A2AScheduleNotFoundError(A2AScheduleError):
    """Raised when a schedule cannot be located for the user."""


class A2AScheduleValidationError(A2AScheduleError):
    """Raised when schedule payload validation fails."""


class A2AScheduleQuotaError(A2AScheduleError):
    """Raised when a schedule task operation exceeds user quotas."""


class A2AScheduleConflictError(A2AScheduleError):
    """Raised when a schedule task operation is in conflict with its current state."""


class A2AScheduleServiceBusyError(A2AScheduleError):
    """Raised when a schedule operation times out due to transient DB pressure."""


_ScheduleResultT = TypeVar("_ScheduleResultT")


def _map_retryable_db_errors(
    operation: str,
) -> Callable[
    [Callable[..., Awaitable[_ScheduleResultT]]],
    Callable[..., Awaitable[_ScheduleResultT]],
]:
    def decorator(
        fn: Callable[..., Awaitable[_ScheduleResultT]],
    ) -> Callable[..., Awaitable[_ScheduleResultT]]:
        @wraps(fn)
        async def wrapper(
            self: "A2AScheduleService",
            *args: Any,
            **kwargs: Any,
        ) -> _ScheduleResultT:
            try:
                return await fn(self, *args, **kwargs)
            except DBAPIError as exc:
                retryable_lock_error = to_retryable_db_lock_error(
                    exc,
                    lock_message=(
                        f"{operation} is currently locked by another operation; retry shortly."
                    ),
                )
                if retryable_lock_error is not None:
                    raise A2AScheduleConflictError(str(retryable_lock_error)) from exc

                retryable_timeout_error = to_retryable_db_query_timeout_error(
                    exc,
                    timeout_message=f"{operation} timed out; service busy, retry shortly.",
                )
                if retryable_timeout_error is not None:
                    raise A2AScheduleServiceBusyError(
                        str(retryable_timeout_error)
                    ) from exc
                raise

        return wrapper

    return decorator


@dataclass(frozen=True)
class ClaimedA2AScheduleTask:
    """Snapshot describing a due task claimed by the scheduler."""

    task_id: UUID
    user_id: UUID
    agent_id: UUID
    conversation_id: Optional[UUID]
    name: str
    prompt: str
    cycle_type: str
    time_point: Dict[str, Any]
    scheduled_for: datetime
    run_id: UUID


class A2AScheduleService:
    """CRUD, validation, and dispatch helpers for A2A schedules."""

    _schedule_minutes_min = 5
    _schedule_minutes_max = 24 * 60
    _default_write_lock_timeout_ms = 500
    _default_write_statement_timeout_ms = 5000

    _allowed_cycle_types = {
        A2AScheduleTask.CYCLE_DAILY,
        A2AScheduleTask.CYCLE_WEEKLY,
        A2AScheduleTask.CYCLE_MONTHLY,
        A2AScheduleTask.CYCLE_INTERVAL,
        A2AScheduleTask.CYCLE_SEQUENTIAL,
    }

    @staticmethod
    def _normalize_timezone_str(timezone_str: str | None) -> str:
        return (timezone_str or "UTC").strip() or "UTC"

    async def _apply_default_write_timeouts(self, db: AsyncSession) -> None:
        await set_postgres_local_timeouts(
            db,
            lock_timeout_ms=self._default_write_lock_timeout_ms,
            statement_timeout_ms=self._default_write_statement_timeout_ms,
        )

    async def _apply_nowait_write_timeouts(self, db: AsyncSession) -> None:
        """Apply only statement timeout for NOWAIT lock paths.

        NOWAIT does not wait for row locks, so lock_timeout is redundant there.
        """

        await set_postgres_local_timeouts(
            db,
            statement_timeout_ms=self._default_write_statement_timeout_ms,
        )

    async def _apply_skip_locked_write_timeouts(self, db: AsyncSession) -> None:
        """Apply only statement timeout for SKIP LOCKED lock paths."""

        await set_postgres_local_timeouts(
            db,
            statement_timeout_ms=self._default_write_statement_timeout_ms,
        )

    async def _get_task_for_update(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        task_id: UUID,
    ) -> A2AScheduleTask:
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
        task = await db.scalar(stmt)
        if task is None:
            raise A2AScheduleNotFoundError("Schedule task not found")
        return task

    @_map_retryable_db_errors("Schedule task list")
    async def list_tasks(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        page: int,
        size: int,
    ) -> tuple[list[A2AScheduleTask], int]:
        offset = (page - 1) * size
        stmt = (
            select(A2AScheduleTask)
            .where(
                A2AScheduleTask.user_id == user_id,
                A2AScheduleTask.deleted_at.is_(None),
                A2AScheduleTask.delete_requested_at.is_(None),
            )
            .order_by(A2AScheduleTask.created_at.desc())
            .offset(offset)
            .limit(size)
        )
        rows = await db.execute(stmt)
        items = list(rows.scalars().all())

        count_stmt = select(func.count(A2AScheduleTask.id)).where(
            A2AScheduleTask.user_id == user_id,
            A2AScheduleTask.deleted_at.is_(None),
            A2AScheduleTask.delete_requested_at.is_(None),
        )
        total = int(await db.scalar(count_stmt) or 0)
        return items, total

    @_map_retryable_db_errors("Schedule task read")
    async def get_task(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        task_id: UUID,
    ) -> A2AScheduleTask:
        return await self._get_task(db, user_id=user_id, task_id=task_id)

    @_map_retryable_db_errors("Schedule task creation")
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
        time_point: Dict[str, Any],
        enabled: bool,
    ) -> A2AScheduleTask:
        await self._apply_default_write_timeouts(db)
        await self._ensure_agent_owned(db, user_id=user_id, agent_id=agent_id)
        if enabled:
            await self._ensure_active_quota(
                db, user_id=user_id, is_superuser=is_superuser
            )

        normalized_name = self._normalize_name(name)
        normalized_prompt = self._normalize_prompt(prompt)
        normalized_cycle = self._normalize_cycle_type(cycle_type)
        timezone_value = self._normalize_timezone_str(timezone_str)
        normalized_point = self._normalize_time_point(
            cycle_type=normalized_cycle,
            time_point=time_point,
            is_superuser=is_superuser,
            timezone_str=timezone_value,
        )

        next_run_at: Optional[datetime] = None
        if enabled:
            next_run_at = self.compute_next_run_at(
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
            enabled=enabled,
            next_run_at=next_run_at,
            last_run_status=A2AScheduleTask.STATUS_IDLE,
        )
        db.add(task)
        await commit_safely(db)
        await db.refresh(task)
        return task

    @_map_retryable_db_errors("Schedule task update")
    async def update_task(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        task_id: UUID,
        is_superuser: bool,
        timezone_str: str,
        name: Optional[str] = None,
        agent_id: Optional[UUID] = None,
        prompt: Optional[str] = None,
        cycle_type: Optional[str] = None,
        time_point: Optional[Dict[str, Any]] = None,
        enabled: Optional[bool] = None,
    ) -> A2AScheduleTask:
        await self._apply_default_write_timeouts(db)
        task = await self._get_task_for_update(db, user_id=user_id, task_id=task_id)
        timezone_value = self._normalize_timezone_str(timezone_str)

        if task.last_run_status == A2AScheduleTask.STATUS_RUNNING:
            raise A2AScheduleConflictError(
                "Task is currently running and cannot be edited."
            )

        if enabled is True and not task.enabled:
            await self._ensure_active_quota(
                db, user_id=user_id, is_superuser=is_superuser
            )

        if name is not None:
            task.name = self._normalize_name(name)

        if prompt is not None:
            task.prompt = self._normalize_prompt(prompt)

        if agent_id is not None:
            await self._ensure_agent_owned(db, user_id=user_id, agent_id=agent_id)
            task.agent_id = agent_id

        next_cycle_type = task.cycle_type
        next_time_point = dict(task.time_point or {})

        if cycle_type is not None:
            next_cycle_type = self._normalize_cycle_type(cycle_type)

        if time_point is not None:
            next_time_point = dict(time_point)

        schedule_changed = (cycle_type is not None) or (time_point is not None)
        if schedule_changed:
            normalized_point = self._normalize_time_point(
                cycle_type=next_cycle_type,
                time_point=next_time_point,
                is_superuser=is_superuser,
                timezone_str=timezone_value,
            )
            task.cycle_type = next_cycle_type
            task.time_point = normalized_point

        if enabled is not None:
            task.enabled = enabled

        should_recompute = False
        if task.enabled and (schedule_changed or enabled is True):
            should_recompute = True
        if not task.enabled:
            task.next_run_at = None

        if should_recompute:
            task.next_run_at = self.compute_next_run_at(
                cycle_type=task.cycle_type,
                time_point=dict(task.time_point or {}),
                timezone_str=timezone_value,
                after_utc=utc_now(),
                is_superuser=is_superuser,
            )

        await commit_safely(db)
        await db.refresh(task)
        return task

    @_map_retryable_db_errors("Schedule task toggle")
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
        await self._apply_default_write_timeouts(db)
        task = await self._get_task_for_update(db, user_id=user_id, task_id=task_id)
        if enabled and not task.enabled:
            await self._ensure_active_quota(
                db, user_id=user_id, is_superuser=is_superuser
            )

        task.enabled = enabled
        if enabled:
            timezone_value = self._normalize_timezone_str(timezone_str)
            task.next_run_at = self.compute_next_run_at(
                cycle_type=task.cycle_type,
                time_point=dict(task.time_point or {}),
                timezone_str=timezone_value,
                after_utc=utc_now(),
                is_superuser=is_superuser,
            )
        else:
            task.next_run_at = None

        await commit_safely(db)
        await db.refresh(task)
        return task

    @_map_retryable_db_errors("Schedule task deletion")
    async def delete_task(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        task_id: UUID,
    ) -> None:
        await self._apply_default_write_timeouts(db)
        task = await self._get_task_for_update(db, user_id=user_id, task_id=task_id)
        if (
            task.last_run_status == A2AScheduleTask.STATUS_RUNNING
            and task.current_run_id is not None
        ):
            # Keep the row alive until the current run reaches a terminal status.
            task.delete_requested_at = utc_now()
            task.enabled = False
            task.next_run_at = None
        else:
            task.soft_delete()
            task.enabled = False
            task.next_run_at = None
            task.delete_requested_at = None
        await commit_safely(db)

    @_map_retryable_db_errors("Schedule task manual fail")
    async def mark_task_failed_manually(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        task_id: UUID,
        marked_by_user_id: UUID,
        reason: Optional[str] = None,
        marked_at: Optional[datetime] = None,
    ) -> A2AScheduleTask:
        await self._apply_nowait_write_timeouts(db)
        now_utc = ensure_utc(marked_at or utc_now())
        manual_error_message = self._build_manual_failure_reason(
            reason=reason,
        )

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
        task = await db.scalar(stmt)
        if task is None:
            raise A2AScheduleNotFoundError("Schedule task not found")

        if (
            task.last_run_status == A2AScheduleTask.STATUS_FAILED
            and task.current_run_id is None
        ):
            return task

        if task.last_run_status != A2AScheduleTask.STATUS_RUNNING:
            raise A2AScheduleValidationError(
                "Only running tasks can be manually marked as failed"
            )

        run_id = task.current_run_id or uuid4()
        started_at = ensure_utc(task.running_started_at or now_utc)
        exec_stmt = (
            select(A2AScheduleExecution)
            .where(
                and_(
                    A2AScheduleExecution.task_id == task.id,
                    A2AScheduleExecution.user_id == task.user_id,
                    A2AScheduleExecution.run_id == run_id,
                )
            )
            .with_for_update(nowait=True)
            .limit(1)
        )
        execution = await db.scalar(exec_stmt)
        if execution is None:
            execution = A2AScheduleExecution(
                user_id=task.user_id,
                task_id=task.id,
                run_id=run_id,
                scheduled_for=started_at,
                started_at=started_at,
                finished_at=now_utc,
                status=A2AScheduleExecution.STATUS_FAILED,
                error_message=manual_error_message,
                conversation_id=task.conversation_id,
            )
            db.add(execution)
        else:
            if execution.status == A2AScheduleExecution.STATUS_RUNNING:
                execution.status = A2AScheduleExecution.STATUS_FAILED
            if execution.finished_at is None:
                execution.finished_at = now_utc
            execution.error_message = manual_error_message
            if execution.conversation_id is None:
                execution.conversation_id = task.conversation_id

        threshold = max(int(settings.a2a_schedule_task_failure_threshold), 1)
        task.last_run_status = A2AScheduleTask.STATUS_FAILED
        task.last_run_at = now_utc
        task.current_run_id = None
        task.running_started_at = None
        task.last_heartbeat_at = None
        task.consecutive_failures = (task.consecutive_failures or 0) + 1
        if task.consecutive_failures >= threshold:
            task.enabled = False
        if task.cycle_type == A2AScheduleTask.CYCLE_SEQUENTIAL:
            if task.enabled:
                task.next_run_at = self._compute_sequential_next_run_at(
                    time_point=dict(task.time_point or {}),
                    after_utc=now_utc,
                )
            else:
                task.next_run_at = None

        await commit_safely(db)
        await db.refresh(task)
        return task

    @_map_retryable_db_errors("Schedule execution list")
    async def list_executions(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        task_id: UUID,
        page: int,
        size: int,
    ) -> tuple[list[A2AScheduleExecution], int]:
        await self._get_task(db, user_id=user_id, task_id=task_id)

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

    async def _running_execution_count_for_agent(
        self,
        db: AsyncSession,
        *,
        agent_id: UUID,
    ) -> int:
        stmt = select(func.count(A2AScheduleTask.id)).where(
            and_(
                A2AScheduleTask.agent_id == agent_id,
                A2AScheduleTask.deleted_at.is_(None),
                A2AScheduleTask.last_run_status == A2AScheduleTask.STATUS_RUNNING,
                A2AScheduleTask.current_run_id.is_not(None),
            )
        )
        return int((await db.scalar(stmt)) or 0)

    async def _global_running_execution_count(
        self,
        db: AsyncSession,
    ) -> int:
        stmt = select(func.count(A2AScheduleTask.id)).where(
            and_(
                A2AScheduleTask.deleted_at.is_(None),
                A2AScheduleTask.last_run_status == A2AScheduleTask.STATUS_RUNNING,
                A2AScheduleTask.current_run_id.is_not(None),
            )
        )
        return int((await db.scalar(stmt)) or 0)

    async def claim_next_due_task(
        self,
        db: AsyncSession,
        *,
        now: Optional[datetime] = None,
    ) -> Optional[ClaimedA2AScheduleTask]:
        await self._apply_skip_locked_write_timeouts(db)
        now_utc = ensure_utc(now or utc_now())

        global_concurrency_limit = max(
            int(settings.a2a_schedule_global_concurrency_limit), 1
        )
        global_running_count = await self._global_running_execution_count(db)
        if global_running_count >= global_concurrency_limit:
            return None

        concurrency_limit = max(int(settings.a2a_schedule_agent_concurrency_limit), 1)

        running_task = aliased(A2AScheduleTask)
        running_count_for_agent = (
            select(func.count(running_task.id))
            .where(
                and_(
                    running_task.agent_id == A2AScheduleTask.agent_id,
                    running_task.deleted_at.is_(None),
                    running_task.last_run_status == A2AScheduleTask.STATUS_RUNNING,
                    running_task.current_run_id.is_not(None),
                )
            )
            .correlate(A2AScheduleTask)
            .scalar_subquery()
        )

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
                    A2AScheduleTask.current_run_id.is_(None),
                    running_count_for_agent < concurrency_limit,
                )
            )
            .order_by(A2AScheduleTask.next_run_at.asc(), A2AScheduleTask.id.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        selected_row = (await db.execute(stmt)).first()
        if selected_row is None:
            return None
        selected_task = selected_row[0]
        timezone_value = self._normalize_timezone_str(selected_row[1])
        is_superuser = bool(selected_row[2])

        scheduled_for = ensure_utc(selected_task.next_run_at or now_utc)
        if selected_task.cycle_type == A2AScheduleTask.CYCLE_SEQUENTIAL:
            # Sequential tasks are re-scheduled only after the current run completes.
            next_run_at = None
        else:
            next_run_at = self.compute_next_run_at(
                cycle_type=selected_task.cycle_type,
                time_point=dict(selected_task.time_point or {}),
                timezone_str=timezone_value,
                after_utc=scheduled_for,
                not_before_utc=now_utc,
                is_superuser=is_superuser,
            )

        run_id = uuid4()
        selected_task.next_run_at = next_run_at
        selected_task.last_run_status = A2AScheduleTask.STATUS_RUNNING
        selected_task.current_run_id = run_id
        selected_task.running_started_at = now_utc
        selected_task.last_heartbeat_at = now_utc
        db.add(
            A2AScheduleExecution(
                user_id=selected_task.user_id,
                task_id=selected_task.id,
                run_id=run_id,
                scheduled_for=scheduled_for,
                started_at=now_utc,
                status=A2AScheduleExecution.STATUS_RUNNING,
                conversation_id=selected_task.conversation_id,
            )
        )
        await commit_safely(db)

        return ClaimedA2AScheduleTask(
            task_id=selected_task.id,
            user_id=selected_task.user_id,
            agent_id=selected_task.agent_id,
            conversation_id=selected_task.conversation_id,
            name=selected_task.name,
            prompt=selected_task.prompt,
            cycle_type=selected_task.cycle_type,
            time_point=dict(selected_task.time_point or {}),
            scheduled_for=scheduled_for,
            run_id=run_id,
        )

    async def recover_stale_running_tasks(
        self,
        db: AsyncSession,
        *,
        now: Optional[datetime] = None,
        timeout_seconds: int = 600,
        hard_timeout_seconds: int | None = None,
    ) -> int:
        """Recover stale running tasks by run_id and close them deterministically."""

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
                A2AScheduleTask.last_heartbeat_at,
                A2AScheduleTask.running_started_at,
            )
            <= cutoff
        ]
        if hard_cutoff is not None:
            stale_predicates.append(A2AScheduleTask.running_started_at <= hard_cutoff)

        error_message = "Execution marked as failed by recovery: stale running task exceeded timeout"
        recovered_count = 0
        while True:
            # SET LOCAL timeouts are transaction-scoped; re-apply after each commit.
            await self._apply_skip_locked_write_timeouts(db)
            stale_where = and_(
                A2AScheduleTask.deleted_at.is_(None),
                A2AScheduleTask.last_run_status == A2AScheduleTask.STATUS_RUNNING,
                A2AScheduleTask.current_run_id.is_not(None),
                A2AScheduleTask.running_started_at.is_not(None),
                or_(*stale_predicates),
            )
            stmt = (
                select(A2AScheduleTask)
                .where(stale_where)
                .order_by(
                    A2AScheduleTask.running_started_at.asc(),
                    A2AScheduleTask.id.asc(),
                )
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            task = await db.scalar(stmt)
            if task is None:
                stale_count_stmt = select(func.count(A2AScheduleTask.id)).where(
                    stale_where
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
            if task.current_run_id is None:
                await commit_safely(db)
                continue
            run_id = task.current_run_id
            exec_stmt = (
                select(A2AScheduleExecution)
                .where(
                    A2AScheduleExecution.task_id == task.id,
                    A2AScheduleExecution.user_id == task.user_id,
                    A2AScheduleExecution.run_id == run_id,
                )
                .limit(1)
            )
            execution = await db.scalar(exec_stmt)
            final_task_status = A2AScheduleTask.STATUS_FAILED
            sequential_after_utc = now_utc

            if (
                execution is not None
                and execution.status == A2AScheduleExecution.STATUS_RUNNING
                and execution.finished_at is None
            ):
                execution.status = A2AScheduleExecution.STATUS_FAILED
                execution.finished_at = now_utc
                execution.error_message = error_message
                if execution.conversation_id is None:
                    execution.conversation_id = task.conversation_id
            elif execution is None:
                # No running execution row exists (e.g., crash before execution creation).
                started_at = ensure_utc(task.running_started_at or now_utc)
                await db.execute(
                    insert(A2AScheduleExecution)
                    .values(
                        user_id=task.user_id,
                        task_id=task.id,
                        run_id=run_id,
                        scheduled_for=started_at,
                        started_at=started_at,
                        finished_at=now_utc,
                        status=A2AScheduleExecution.STATUS_FAILED,
                        error_message=error_message,
                        conversation_id=task.conversation_id,
                    )
                    .on_conflict_do_nothing(
                        index_elements=["task_id", "run_id"],
                    )
                )
            elif execution.status == A2AScheduleExecution.STATUS_SUCCESS:
                final_task_status = A2AScheduleTask.STATUS_SUCCESS
                if execution.finished_at is not None:
                    sequential_after_utc = ensure_utc(execution.finished_at)
            elif execution.status == A2AScheduleExecution.STATUS_FAILED:
                final_task_status = A2AScheduleTask.STATUS_FAILED
                if execution.finished_at is not None:
                    sequential_after_utc = ensure_utc(execution.finished_at)

            task.last_run_status = final_task_status
            task.last_run_at = now_utc
            task.current_run_id = None
            task.running_started_at = None
            task.last_heartbeat_at = None
            if final_task_status == A2AScheduleTask.STATUS_SUCCESS:
                task.consecutive_failures = 0
            else:
                task.consecutive_failures = (task.consecutive_failures or 0) + 1
                if task.consecutive_failures >= failure_threshold:
                    task.enabled = False
            if task.cycle_type == A2AScheduleTask.CYCLE_SEQUENTIAL:
                if task.enabled:
                    task.next_run_at = self._compute_sequential_next_run_at(
                        time_point=dict(task.time_point or {}),
                        after_utc=sequential_after_utc,
                    )
                else:
                    task.next_run_at = None
            if task.delete_requested_at is not None:
                task.soft_delete()
                task.enabled = False
                task.next_run_at = None
                task.delete_requested_at = None
            recovered_count += 1

            await commit_safely(db)
        return recovered_count

    @_map_retryable_db_errors("Schedule task finalize")
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
    ) -> bool:
        """Finalize one claimed run only if current_run_id still matches run_id."""

        await self._apply_nowait_write_timeouts(db)
        stmt = (
            select(A2AScheduleTask)
            .where(
                and_(
                    A2AScheduleTask.id == task_id,
                    A2AScheduleTask.user_id == user_id,
                    A2AScheduleTask.current_run_id == run_id,
                )
            )
            .with_for_update(nowait=True)
            .limit(1)
        )
        task = await db.scalar(stmt)
        if task is None:
            return False

        threshold = max(int(settings.a2a_schedule_task_failure_threshold), 1)
        task.last_run_status = final_status
        task.last_run_at = ensure_utc(finished_at)
        task.current_run_id = None
        task.running_started_at = None
        task.last_heartbeat_at = None
        if conversation_id is not None:
            task.conversation_id = conversation_id

        if final_status == A2AScheduleTask.STATUS_SUCCESS:
            task.consecutive_failures = 0
        elif final_status == A2AScheduleTask.STATUS_FAILED:
            task.consecutive_failures = (task.consecutive_failures or 0) + 1
            if task.consecutive_failures >= threshold:
                task.enabled = False
        elif final_status == A2AScheduleTask.STATUS_IDLE:
            # Disabled tasks can be reset to idle without affecting failure counters.
            pass
        else:
            raise A2AScheduleValidationError("Unsupported final status for task run")
        if task.delete_requested_at is not None:
            task.soft_delete()
            task.enabled = False
            task.next_run_at = None
            task.delete_requested_at = None
        elif task.cycle_type == A2AScheduleTask.CYCLE_SEQUENTIAL:
            if task.enabled:
                task.next_run_at = self._compute_sequential_next_run_at(
                    time_point=dict(task.time_point or {}),
                    after_utc=task.last_run_at or ensure_utc(finished_at),
                )
            else:
                task.next_run_at = None

        return True

    async def _get_task(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        task_id: UUID,
    ) -> A2AScheduleTask:
        stmt = select(A2AScheduleTask).where(
            and_(
                A2AScheduleTask.id == task_id,
                A2AScheduleTask.user_id == user_id,
                A2AScheduleTask.deleted_at.is_(None),
                A2AScheduleTask.delete_requested_at.is_(None),
            )
        )
        task = await db.scalar(stmt)
        if task is None:
            raise A2AScheduleNotFoundError("Schedule task not found")
        return task

    async def _ensure_agent_owned(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        agent_id: UUID,
    ) -> None:
        stmt = select(A2AAgent.id).where(
            and_(
                A2AAgent.id == agent_id,
                A2AAgent.user_id == user_id,
                A2AAgent.agent_scope == A2AAgent.SCOPE_PERSONAL,
                A2AAgent.enabled.is_(True),
                A2AAgent.deleted_at.is_(None),
            )
        )
        found = await db.scalar(stmt)
        if found is None:
            raise A2AScheduleValidationError(
                "Target agent is missing, disabled, or not owned by current user"
            )

    async def _ensure_active_quota(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        is_superuser: bool,
    ) -> None:
        if is_superuser:
            return

        limit = max(settings.a2a_schedule_max_active_tasks_per_user, 0)
        if limit == 0:
            raise A2AScheduleQuotaError(
                "Scheduled tasks are currently disabled for non-admin users."
            )

        stmt = select(func.count(A2AScheduleTask.id)).where(
            and_(
                A2AScheduleTask.user_id == user_id,
                A2AScheduleTask.enabled.is_(True),
                A2AScheduleTask.deleted_at.is_(None),
                A2AScheduleTask.delete_requested_at.is_(None),
            )
        )
        active_count = int((await db.scalar(stmt)) or 0)

        if active_count >= limit:
            raise A2AScheduleQuotaError(
                f"Maximum active schedule tasks limit ({limit}) reached."
            )

    def _normalize_name(self, value: str) -> str:
        normalized = (value or "").strip()
        if not normalized:
            raise A2AScheduleValidationError("Task name is required")
        if len(normalized) > 120:
            raise A2AScheduleValidationError("Task name must be <= 120 characters")
        return normalized

    def _normalize_prompt(self, value: str) -> str:
        normalized = (value or "").strip()
        if not normalized:
            raise A2AScheduleValidationError("Prompt is required")
        if len(normalized) > 128_000:
            raise A2AScheduleValidationError("Prompt exceeds max length")
        return normalized

    @staticmethod
    def _build_manual_failure_reason(
        *,
        reason: Optional[str],
    ) -> str:
        normalized_reason = (reason or "").strip()
        return normalized_reason or _MANUAL_FAILURE_MESSAGE

    def _normalize_cycle_type(self, value: str) -> str:
        normalized = (value or "").strip().lower()
        if normalized not in self._allowed_cycle_types:
            raise A2AScheduleValidationError(
                "cycle_type must be one of daily, weekly, monthly, interval, sequential"
            )
        return normalized

    def _normalize_time_point(
        self,
        *,
        cycle_type: str,
        time_point: Dict[str, Any],
        is_superuser: bool = False,
        timezone_str: str = "UTC",
    ) -> Dict[str, Any]:
        if not isinstance(time_point, dict):
            raise A2AScheduleValidationError("time_point must be an object")

        if cycle_type == A2AScheduleTask.CYCLE_INTERVAL:
            minutes_raw = time_point.get("minutes", time_point.get("interval_minutes"))
            minutes = self._normalize_schedule_minutes(
                minutes_raw,
                cycle_type="interval",
            )
            interval_start_at_local = self._normalize_interval_start_at_local(
                time_point.get("start_at_local")
            )
            normalized: Dict[str, Any] = {"minutes": minutes}
            if interval_start_at_local is not None:
                normalized["start_at_local"] = interval_start_at_local
                normalized["start_at_utc"] = self._to_utc_from_local_iso(
                    interval_start_at_local,
                    timezone_str=timezone_str,
                )
            return normalized
        if cycle_type == A2AScheduleTask.CYCLE_SEQUENTIAL:
            minutes_raw = time_point.get("minutes", time_point.get("interval_minutes"))
            minutes = self._normalize_schedule_minutes(
                minutes_raw,
                cycle_type="sequential",
            )
            if time_point.get("start_at_local") not in (None, "") or time_point.get(
                "start_at_utc"
            ) not in (None, ""):
                raise A2AScheduleValidationError(
                    "sequential does not support start_at_local/start_at_utc; use minutes only"
                )
            return {"minutes": minutes}

        hh, mm = self._parse_hhmm(time_point.get("time"))
        normalized: Dict[str, Any] = {"time": f"{hh:02d}:{mm:02d}"}

        if cycle_type == A2AScheduleTask.CYCLE_DAILY:
            return normalized

        if cycle_type == A2AScheduleTask.CYCLE_WEEKLY:
            weekday = self._coerce_int(time_point.get("weekday"))
            # Contract: ISO weekday (1=Monday ... 7=Sunday). Keep this consistent
            # with other calendar settings like `calendar.first_day_of_week`.
            if weekday is None or weekday < 1 or weekday > 7:
                raise A2AScheduleValidationError(
                    "weekly time_point requires weekday in range 1..7 (1=Monday, 7=Sunday)"
                )
            normalized["weekday"] = weekday
            return normalized

        if cycle_type == A2AScheduleTask.CYCLE_MONTHLY:
            day = self._coerce_int(time_point.get("day"))
            if day is None or day < 1 or day > 31:
                raise A2AScheduleValidationError(
                    "monthly time_point requires day in range 1..31"
                )
            normalized["day"] = day
            return normalized

        raise A2AScheduleValidationError("Unsupported cycle_type")

    def _normalize_schedule_minutes(
        self,
        value: Any,
        *,
        cycle_type: str,
    ) -> int:
        minutes = self._coerce_int(value)
        if minutes is None:
            raise A2AScheduleValidationError(
                f"{cycle_type} time_point requires minutes"
            )
        return max(self._schedule_minutes_min, min(self._schedule_minutes_max, minutes))

    def _sanitize_schedule_minutes_for_read(self, value: Any) -> int:
        minutes = self._coerce_int(value)
        if minutes is None:
            return self._schedule_minutes_min
        return max(self._schedule_minutes_min, min(self._schedule_minutes_max, minutes))

    @staticmethod
    def _format_local_minute_iso(dt: datetime) -> str:
        return dt.strftime("%Y-%m-%dT%H:%M")

    @classmethod
    def _normalize_interval_start_at_local(
        cls,
        value: Any,
    ) -> Optional[str]:
        if value is None or value == "":
            return None
        if isinstance(value, str):
            trimmed = value.strip()
            if not trimmed:
                return None
            try:
                dt = datetime.fromisoformat(trimmed)
            except ValueError as exc:
                raise A2AScheduleValidationError(
                    "interval time_point.start_at_local must be a valid ISO datetime"
                ) from exc
            if dt.tzinfo is not None:
                raise A2AScheduleValidationError(
                    "interval time_point.start_at_local must be timezone-naive "
                    "(without Z or offset)"
                )
            return cls._format_local_minute_iso(dt)
        if isinstance(value, datetime):
            if value.tzinfo is not None:
                raise A2AScheduleValidationError(
                    "interval time_point.start_at_local must be timezone-naive "
                    "(without Z or offset)"
                )
            return cls._format_local_minute_iso(value)

        raise A2AScheduleValidationError(
            "interval time_point.start_at_local must be an ISO datetime string"
        )

    @classmethod
    def _to_utc_from_local_iso(cls, value: str, *, timezone_str: str) -> str:
        try:
            local_naive = datetime.fromisoformat(value)
        except ValueError as exc:
            raise A2AScheduleValidationError(
                "interval time_point.start_at_local must be a valid ISO datetime"
            ) from exc
        timezone_value = cls._normalize_timezone_str(timezone_str)
        tz = resolve_timezone(timezone_value, default="UTC")
        return ensure_utc(local_naive.replace(tzinfo=tz)).isoformat()

    def format_local_datetime(
        self,
        value: datetime | None,
        *,
        timezone_str: str,
    ) -> str | None:
        if value is None:
            return None
        timezone_value = self._normalize_timezone_str(timezone_str)
        tz = resolve_timezone(timezone_value, default="UTC")
        local_dt = ensure_utc(value).astimezone(tz)
        return self._format_local_minute_iso(local_dt)

    def serialize_time_point_for_response(
        self,
        *,
        cycle_type: str,
        time_point: Dict[str, Any] | None,
        timezone_str: str,
    ) -> Dict[str, Any]:
        payload = dict(time_point or {})
        if cycle_type == A2AScheduleTask.CYCLE_SEQUENTIAL:
            minutes = self._sanitize_schedule_minutes_for_read(
                payload.get("minutes", payload.get("interval_minutes"))
            )
            return {"minutes": minutes}
        if cycle_type != A2AScheduleTask.CYCLE_INTERVAL:
            return payload

        timezone_value = self._normalize_timezone_str(timezone_str)
        normalized: Dict[str, Any] = {
            "minutes": self._sanitize_schedule_minutes_for_read(
                payload.get("minutes", payload.get("interval_minutes"))
            )
        }

        start_at_local = payload.get("start_at_local")
        if isinstance(start_at_local, str) and start_at_local.strip():
            raw_local = start_at_local.strip()
            normalized["start_at_local"] = raw_local
            try:
                normalized_local = self._normalize_interval_start_at_local(raw_local)
            except A2AScheduleValidationError:
                normalized_local = None
            if normalized_local is not None:
                normalized["start_at_local"] = normalized_local
                normalized["start_at_utc"] = self._to_utc_from_local_iso(
                    normalized_local,
                    timezone_str=timezone_value,
                )

        start_at_utc = payload.get("start_at_utc")
        if isinstance(start_at_utc, str) and start_at_utc.strip():
            raw_utc = start_at_utc.strip()
            if "start_at_utc" not in normalized:
                normalized["start_at_utc"] = raw_utc
            if "start_at_local" not in normalized:
                try:
                    start_at_dt = self._resolve_interval_start_at_utc(raw_utc)
                except A2AScheduleValidationError:
                    start_at_dt = None
                if start_at_dt is not None:
                    normalized["start_at_local"] = self.format_local_datetime(
                        start_at_dt,
                        timezone_str=timezone_value,
                    )

        return normalized

    @staticmethod
    def _resolve_interval_start_at_utc(value: Any) -> Optional[datetime]:
        if value is None:
            return None

        if isinstance(value, datetime):
            return ensure_utc(value)

        if not isinstance(value, str):
            return None

        trimmed = value.strip()
        if not trimmed:
            return None

        try:
            dt = datetime.fromisoformat(trimmed)
        except ValueError as exc:
            if trimmed.endswith("Z"):
                dt = datetime.fromisoformat(trimmed.replace("Z", "+00:00"))
            else:
                raise A2AScheduleValidationError(
                    "interval time_point.start_at_utc is not a valid ISO datetime"
                ) from exc

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return ensure_utc(dt)

    def _compute_sequential_next_run_at(
        self,
        *,
        time_point: Dict[str, Any] | None,
        after_utc: datetime,
    ) -> datetime:
        minutes = self._sanitize_schedule_minutes_for_read(
            (time_point or {}).get(
                "minutes", (time_point or {}).get("interval_minutes")
            )
        )
        return ensure_utc(after_utc) + timedelta(minutes=minutes)

    @staticmethod
    def _next_interval_candidate(
        after_utc: datetime,
        interval: timedelta,
        start_at_utc: Optional[datetime],
        guard_utc: datetime,
    ) -> datetime:
        anchor = ensure_utc(start_at_utc) if start_at_utc else None
        after = ensure_utc(after_utc)
        if anchor is None:
            candidate = after + interval
            if candidate <= guard_utc:
                interval_seconds = max(interval.total_seconds(), 1.0)
                return candidate + timedelta(
                    seconds=(guard_utc - candidate).total_seconds()
                    // interval_seconds
                    * interval_seconds
                    + interval_seconds
                )
            return candidate
        else:
            if after < anchor:
                candidate = anchor
            else:
                interval_seconds = max(interval.total_seconds(), 1.0)
                delta_seconds = (after - anchor).total_seconds()
                steps = int((delta_seconds + interval_seconds - 1) // interval_seconds)
                candidate = anchor + timedelta(seconds=steps * interval_seconds)

                if candidate <= guard_utc:
                    additional_steps = (
                        int((guard_utc - candidate).total_seconds() // interval_seconds)
                        + 1
                    )
                    return candidate + timedelta(
                        seconds=additional_steps * interval_seconds
                    )
            return candidate

        return candidate

    @staticmethod
    def _coerce_int(value: Any) -> Optional[int]:
        try:
            if value is None:
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_hhmm(value: Any) -> tuple[int, int]:
        raw = str(value or "").strip()
        pieces = raw.split(":", 1)
        if len(pieces) != 2:
            raise A2AScheduleValidationError("time_point.time must be HH:MM")
        hour = A2AScheduleService._coerce_int(pieces[0])
        minute = A2AScheduleService._coerce_int(pieces[1])
        if hour is None or minute is None:
            raise A2AScheduleValidationError("time_point.time must be HH:MM")
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            raise A2AScheduleValidationError("time_point.time must be HH:MM")
        return hour, minute

    @staticmethod
    def _monthly_candidate(
        *,
        year: int,
        month: int,
        day: int,
        hour: int,
        minute: int,
        tz,
    ) -> datetime:
        last_day = calendar.monthrange(year, month)[1]
        resolved_day = min(day, last_day)
        return datetime(year, month, resolved_day, hour, minute, tzinfo=tz)

    @staticmethod
    def _resolve_local_wall_clock(candidate_local: datetime) -> datetime:
        """Resolve local wall-clock ambiguity and DST gaps deterministically.

        - Non-existent local times (DST spring-forward gap) are shifted forward to
          the first valid local timestamp after round-tripping via UTC.
        - Ambiguous local times (DST fall-back overlap) are pinned to fold=0
          (the first occurrence).
        """
        if candidate_local.tzinfo is None:
            return candidate_local

        normalized = candidate_local.astimezone(timezone.utc).astimezone(
            candidate_local.tzinfo
        )
        original_wall = (
            candidate_local.year,
            candidate_local.month,
            candidate_local.day,
            candidate_local.hour,
            candidate_local.minute,
            candidate_local.second,
            candidate_local.microsecond,
        )
        normalized_wall = (
            normalized.year,
            normalized.month,
            normalized.day,
            normalized.hour,
            normalized.minute,
            normalized.second,
            normalized.microsecond,
        )
        if normalized_wall != original_wall:
            return normalized.replace(fold=0)

        return candidate_local.replace(fold=0)

    def _next_occurrence_local(
        self,
        *,
        cycle_type: str,
        time_point: Dict[str, Any],
        after_local: datetime,
        is_superuser: bool = False,
    ) -> datetime:
        if cycle_type == A2AScheduleTask.CYCLE_INTERVAL:
            minutes = self._normalize_schedule_minutes(
                time_point.get("minutes", time_point.get("interval_minutes")),
                cycle_type="interval",
            )
            return after_local + timedelta(minutes=minutes)

        hh, mm = self._parse_hhmm(time_point.get("time"))
        target_time = time(hour=hh, minute=mm)

        if cycle_type == A2AScheduleTask.CYCLE_DAILY:
            candidate = datetime.combine(
                after_local.date(),
                target_time,
                tzinfo=after_local.tzinfo,
            )
            candidate = self._resolve_local_wall_clock(candidate)
            if candidate <= after_local:
                candidate = self._resolve_local_wall_clock(
                    candidate + timedelta(days=1)
                )
            return candidate

        if cycle_type == A2AScheduleTask.CYCLE_WEEKLY:
            weekday = self._coerce_int(time_point.get("weekday"))
            if weekday is None or weekday < 1 or weekday > 7:
                raise A2AScheduleValidationError("Invalid weekday")

            # ISO weekday (1=Monday ... 7=Sunday) aligns with datetime.isoweekday().
            delta_days = (weekday - after_local.isoweekday()) % 7
            candidate_date = after_local.date() + timedelta(days=delta_days)
            candidate = datetime.combine(
                candidate_date,
                target_time,
                tzinfo=after_local.tzinfo,
            )
            candidate = self._resolve_local_wall_clock(candidate)
            if candidate <= after_local:
                candidate = self._resolve_local_wall_clock(
                    candidate + timedelta(days=7)
                )
            return candidate

        if cycle_type == A2AScheduleTask.CYCLE_MONTHLY:
            day = self._coerce_int(time_point.get("day"))
            if day is None or day < 1 or day > 31:
                raise A2AScheduleValidationError("Invalid day")

            candidate = self._monthly_candidate(
                year=after_local.year,
                month=after_local.month,
                day=day,
                hour=hh,
                minute=mm,
                tz=after_local.tzinfo,
            )
            candidate = self._resolve_local_wall_clock(candidate)
            if candidate <= after_local:
                if after_local.month == 12:
                    year = after_local.year + 1
                    month = 1
                else:
                    year = after_local.year
                    month = after_local.month + 1

                candidate = self._monthly_candidate(
                    year=year,
                    month=month,
                    day=day,
                    hour=hh,
                    minute=mm,
                    tz=after_local.tzinfo,
                )
                candidate = self._resolve_local_wall_clock(candidate)
            return candidate

        raise A2AScheduleValidationError("Unsupported cycle_type")

    def compute_next_run_at(
        self,
        *,
        cycle_type: str,
        time_point: Dict[str, Any],
        timezone_str: str,
        after_utc: datetime,
        not_before_utc: Optional[datetime] = None,
        is_superuser: bool = False,
    ) -> datetime:
        normalized_cycle = self._normalize_cycle_type(cycle_type)
        timezone_value = self._normalize_timezone_str(timezone_str)
        normalized_point = self._normalize_time_point(
            cycle_type=normalized_cycle,
            time_point=time_point,
            is_superuser=is_superuser,
            timezone_str=timezone_value,
        )
        if normalized_cycle == A2AScheduleTask.CYCLE_SEQUENTIAL:
            after = ensure_utc(after_utc)
            guard = ensure_utc(not_before_utc or after_utc)
            baseline = after if after >= guard else guard
            return self._compute_sequential_next_run_at(
                time_point=normalized_point,
                after_utc=baseline,
            )

        if normalized_cycle == A2AScheduleTask.CYCLE_INTERVAL:
            minutes = self._normalize_schedule_minutes(
                normalized_point.get(
                    "minutes", normalized_point.get("interval_minutes")
                ),
                cycle_type="interval",
            )
            interval = timedelta(minutes=minutes)
            after = ensure_utc(after_utc)
            guard = ensure_utc(not_before_utc or after_utc)
            start_at = self._resolve_interval_start_at_utc(
                normalized_point.get("start_at_utc")
            )
            return self._next_interval_candidate(
                after_utc=after,
                interval=interval,
                start_at_utc=start_at,
                guard_utc=guard,
            )

        tz = resolve_timezone(timezone_value, default="UTC")
        after_local = ensure_utc(after_utc).astimezone(tz)
        guard_utc = ensure_utc(not_before_utc or after_utc)

        candidate_local = self._next_occurrence_local(
            cycle_type=normalized_cycle,
            time_point=normalized_point,
            after_local=after_local,
            is_superuser=is_superuser,
        )
        while ensure_utc(candidate_local) <= guard_utc:
            candidate_local = self._next_occurrence_local(
                cycle_type=normalized_cycle,
                time_point=normalized_point,
                after_local=candidate_local,
                is_superuser=is_superuser,
            )

        return candidate_local.astimezone(timezone.utc)


A2A_SCHEDULE_SOURCE = "scheduled"
A2A_MANUAL_SOURCE = "manual"


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
