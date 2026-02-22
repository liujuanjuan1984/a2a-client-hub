"""Business logic for user-configurable A2A schedules."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.a2a_agent import A2AAgent
from app.db.models.a2a_schedule_execution import A2AScheduleExecution
from app.db.models.a2a_schedule_task import A2AScheduleTask
from app.db.transaction import commit_safely
from app.handlers import auth as auth_handler
from app.utils.timezone_util import ensure_utc, resolve_timezone, utc_now


class A2AScheduleError(RuntimeError):
    """Base error for A2A schedule operations."""


class A2AScheduleNotFoundError(A2AScheduleError):
    """Raised when a schedule cannot be located for the user."""


class A2AScheduleValidationError(A2AScheduleError):
    """Raised when schedule payload validation fails."""


class A2AScheduleQuotaError(A2AScheduleError):
    """Raised when a schedule task operation exceeds user quotas."""


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


class A2AScheduleService:
    """CRUD, validation, and dispatch helpers for A2A schedules."""

    _allowed_cycle_types = {
        A2AScheduleTask.CYCLE_DAILY,
        A2AScheduleTask.CYCLE_WEEKLY,
        A2AScheduleTask.CYCLE_MONTHLY,
        A2AScheduleTask.CYCLE_INTERVAL,
    }

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
        )
        total = int(await db.scalar(count_stmt) or 0)
        return items, total

    async def get_task(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        task_id: UUID,
    ) -> A2AScheduleTask:
        return await self._get_task(db, user_id=user_id, task_id=task_id)

    async def create_task(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        is_superuser: bool,
        name: str,
        agent_id: UUID,
        prompt: str,
        cycle_type: str,
        time_point: Dict[str, Any],
        enabled: bool,
    ) -> A2AScheduleTask:
        await self._ensure_agent_owned(db, user_id=user_id, agent_id=agent_id)
        if enabled:
            await self._ensure_active_quota(
                db, user_id=user_id, is_superuser=is_superuser
            )

        normalized_name = self._normalize_name(name)
        normalized_prompt = self._normalize_prompt(prompt)
        normalized_cycle = self._normalize_cycle_type(cycle_type)
        normalized_point = self._normalize_time_point(
            cycle_type=normalized_cycle,
            time_point=time_point,
            is_superuser=is_superuser,
        )

        next_run_at: Optional[datetime] = None
        if enabled:
            timezone_value = await auth_handler.get_user_timezone(
                db,
                user_id=user_id,
                default="UTC",
            )
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

    async def update_task(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        task_id: UUID,
        is_superuser: bool,
        name: Optional[str] = None,
        agent_id: Optional[UUID] = None,
        prompt: Optional[str] = None,
        cycle_type: Optional[str] = None,
        time_point: Optional[Dict[str, Any]] = None,
        enabled: Optional[bool] = None,
    ) -> A2AScheduleTask:
        task = await self._get_task(db, user_id=user_id, task_id=task_id)

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
            timezone_value = await auth_handler.get_user_timezone(
                db,
                user_id=user_id,
                default="UTC",
            )
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

    async def set_enabled(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        task_id: UUID,
        enabled: bool,
        is_superuser: bool,
    ) -> A2AScheduleTask:
        task = await self._get_task(db, user_id=user_id, task_id=task_id)
        if enabled and not task.enabled:
            await self._ensure_active_quota(
                db, user_id=user_id, is_superuser=is_superuser
            )

        task.enabled = enabled
        if enabled:
            timezone_value = await auth_handler.get_user_timezone(
                db,
                user_id=user_id,
                default="UTC",
            )
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

    async def delete_task(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        task_id: UUID,
    ) -> None:
        task = await self._get_task(db, user_id=user_id, task_id=task_id)
        task.soft_delete()
        task.enabled = False
        task.next_run_at = None
        await commit_safely(db)

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
        stmt = (
            select(func.count(A2AScheduleExecution.id))
            .join(
                A2AScheduleTask,
                A2AScheduleTask.id == A2AScheduleExecution.task_id,
            )
            .where(
                and_(
                    A2AScheduleTask.agent_id == agent_id,
                    A2AScheduleTask.deleted_at.is_(None),
                    A2AScheduleExecution.status == A2AScheduleExecution.STATUS_RUNNING,
                )
            )
        )
        return int((await db.scalar(stmt)) or 0)

    async def claim_next_due_task(
        self,
        db: AsyncSession,
        *,
        now: Optional[datetime] = None,
    ) -> Optional[ClaimedA2AScheduleTask]:
        now_utc = ensure_utc(now or utc_now())
        concurrency_limit = max(int(settings.a2a_schedule_agent_concurrency_limit), 1)

        stmt = (
            select(A2AScheduleTask)
            .where(
                and_(
                    A2AScheduleTask.deleted_at.is_(None),
                    A2AScheduleTask.enabled.is_(True),
                    A2AScheduleTask.next_run_at.is_not(None),
                    A2AScheduleTask.next_run_at <= now_utc,
                )
            )
            .order_by(A2AScheduleTask.next_run_at.asc(), A2AScheduleTask.id.asc())
            .limit(max(concurrency_limit * 3, 10))
            .with_for_update(skip_locked=True)
        )
        candidates = list((await db.scalars(stmt)).all())
        if not candidates:
            return None

        selected_task: Optional[A2AScheduleTask] = None
        for task in candidates:
            running_count = await self._running_execution_count_for_agent(
                db,
                agent_id=task.agent_id,
            )
            if running_count >= concurrency_limit:
                continue
            selected_task = task
            break

        if selected_task is None:
            return None

        timezone_value = await auth_handler.get_user_timezone(
            db,
            user_id=selected_task.user_id,
            default="UTC",
        )

        from app.db.models.user import User

        is_superuser = (
            await db.scalar(
                select(User.is_superuser).where(User.id == selected_task.user_id)
            )
        ) or False

        scheduled_for = ensure_utc(selected_task.next_run_at or now_utc)
        next_run_at = self.compute_next_run_at(
            cycle_type=selected_task.cycle_type,
            time_point=dict(selected_task.time_point or {}),
            timezone_str=timezone_value,
            after_utc=scheduled_for,
            not_before_utc=now_utc,
            is_superuser=is_superuser,
        )

        selected_task.next_run_at = next_run_at
        selected_task.last_run_status = A2AScheduleTask.STATUS_RUNNING
        # Record the claim timestamp so we can recover stale runs if the worker crashes
        # before creating an execution row.
        selected_task.last_run_at = now_utc
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
        )

    async def recover_stale_running_tasks(
        self,
        db: AsyncSession,
        *,
        now: Optional[datetime] = None,
        timeout_seconds: int = 600,
    ) -> int:
        """Mark stale `running` tasks as failed and persist failure executions.

        This recovers the scenario where a task is claimed (status=running) but the
        worker crashes before the execution row is created or finalized.
        """

        now_utc = ensure_utc(now or utc_now())
        timeout_seconds = max(int(timeout_seconds or 0), 1)
        cutoff = now_utc - timedelta(seconds=timeout_seconds)

        stmt = (
            select(A2AScheduleTask)
            .where(
                and_(
                    A2AScheduleTask.deleted_at.is_(None),
                    A2AScheduleTask.last_run_status == A2AScheduleTask.STATUS_RUNNING,
                    A2AScheduleTask.last_run_at.is_not(None),
                    A2AScheduleTask.last_run_at <= cutoff,
                )
            )
            .order_by(A2AScheduleTask.last_run_at.asc(), A2AScheduleTask.id.asc())
            .with_for_update(skip_locked=True)
        )
        rows = await db.execute(stmt)
        tasks = list(rows.scalars().all())
        if not tasks:
            return 0

        error_message = "Execution marked as failed by recovery: stale running task exceeded timeout"

        for task in tasks:
            # Try to locate the most recent execution; if it's still running, finalize it.
            exec_stmt = (
                select(A2AScheduleExecution)
                .where(
                    A2AScheduleExecution.task_id == task.id,
                    A2AScheduleExecution.user_id == task.user_id,
                )
                .order_by(
                    A2AScheduleExecution.started_at.desc(),
                    A2AScheduleExecution.id.desc(),
                )
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            execution = await db.scalar(exec_stmt)

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
            else:
                # No running execution row exists (e.g., crash before execution creation).
                started_at = ensure_utc(task.last_run_at or now_utc)
                recovered = A2AScheduleExecution(
                    user_id=task.user_id,
                    task_id=task.id,
                    scheduled_for=started_at,
                    started_at=started_at,
                    finished_at=now_utc,
                    status=A2AScheduleExecution.STATUS_FAILED,
                    error_message=error_message,
                    conversation_id=task.conversation_id,
                )
                db.add(recovered)

            task.last_run_status = A2AScheduleTask.STATUS_FAILED
            task.last_run_at = now_utc

        await commit_safely(db)
        return len(tasks)

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

    def _normalize_cycle_type(self, value: str) -> str:
        normalized = (value or "").strip().lower()
        if normalized not in self._allowed_cycle_types:
            raise A2AScheduleValidationError(
                "cycle_type must be one of daily, weekly, monthly, interval"
            )
        return normalized

    def _normalize_time_point(
        self,
        *,
        cycle_type: str,
        time_point: Dict[str, Any],
        is_superuser: bool = False,
    ) -> Dict[str, Any]:
        if not isinstance(time_point, dict):
            raise A2AScheduleValidationError("time_point must be an object")

        if cycle_type == A2AScheduleTask.CYCLE_INTERVAL:
            minutes_raw = time_point.get("minutes", time_point.get("interval_minutes"))
            minutes = self._normalize_interval_minutes(
                minutes_raw, is_superuser=is_superuser
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

    @staticmethod
    def _ceil_to_multiple(value: int, base: int) -> int:
        if base <= 0:
            return value
        return ((value + base - 1) // base) * base

    def _normalize_interval_minutes(
        self, value: Any, *, is_superuser: bool = False
    ) -> int:
        minutes = self._coerce_int(value)
        if minutes is None:
            raise A2AScheduleValidationError("interval time_point requires minutes")

        min_interval = (
            1 if is_superuser else max(settings.a2a_schedule_min_interval_minutes, 1)
        )

        # Soft normalization:
        # - round up to the next multiple of 5 if not superuser
        # - clamp to [min_interval, 1440]
        if minutes < min_interval:
            raise A2AScheduleValidationError(
                f"interval minutes cannot be less than {min_interval}"
            )

        minutes = min(minutes, 24 * 60)

        if not is_superuser:
            normalized = self._ceil_to_multiple(minutes, 5)
        else:
            normalized = minutes

        if normalized > 24 * 60:
            normalized = 24 * 60
        return normalized

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

    def _next_occurrence_local(
        self,
        *,
        cycle_type: str,
        time_point: Dict[str, Any],
        after_local: datetime,
        is_superuser: bool = False,
    ) -> datetime:
        if cycle_type == A2AScheduleTask.CYCLE_INTERVAL:
            minutes = self._normalize_interval_minutes(
                time_point.get("minutes", time_point.get("interval_minutes")),
                is_superuser=is_superuser,
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
            if candidate <= after_local:
                candidate += timedelta(days=1)
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
            if candidate <= after_local:
                candidate += timedelta(days=7)
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
        normalized_point = self._normalize_time_point(
            cycle_type=normalized_cycle,
            time_point=time_point,
            is_superuser=is_superuser,
        )

        if normalized_cycle == A2AScheduleTask.CYCLE_INTERVAL:
            minutes = self._normalize_interval_minutes(
                normalized_point.get(
                    "minutes", normalized_point.get("interval_minutes")
                ),
                is_superuser=is_superuser,
            )
            interval = timedelta(minutes=minutes)
            after = ensure_utc(after_utc)
            guard = ensure_utc(not_before_utc or after_utc)

            base_candidate = after + interval
            if base_candidate > guard:
                return base_candidate

            delta_seconds = (guard - base_candidate).total_seconds()
            interval_seconds = max(interval.total_seconds(), 1.0)
            steps = int(delta_seconds // interval_seconds) + 1
            return base_candidate + (interval * steps)

        tz = resolve_timezone(timezone_str, default="UTC")
        after_local = ensure_utc(after_utc).astimezone(tz)
        guard_local = ensure_utc(not_before_utc or after_utc).astimezone(tz)

        candidate_local = self._next_occurrence_local(
            cycle_type=normalized_cycle,
            time_point=normalized_point,
            after_local=after_local,
            is_superuser=is_superuser,
        )
        while candidate_local <= guard_local:
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
    "A2AScheduleError",
    "A2AScheduleNotFoundError",
    "A2AScheduleQuotaError",
    "A2AScheduleService",
    "A2AScheduleValidationError",
    "ClaimedA2AScheduleTask",
    "a2a_schedule_service",
]
