"""Scheduler job that dispatches due A2A schedule tasks."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from sqlalchemy import and_, func, select, text, update
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.locking import (
    is_retryable_db_lock_failure,
    is_retryable_db_query_timeout,
    set_postgres_local_timeouts,
)
from app.db.models.a2a_schedule_execution import A2AScheduleExecution
from app.db.models.a2a_schedule_task import A2AScheduleTask
from app.db.models.conversation_thread import ConversationThread
from app.db.session import AsyncSessionLocal, async_engine
from app.db.transaction import commit_safely, rollback_safely
from app.features.invoke.route_runner import run_background_invoke
from app.features.personal_agents.runtime import a2a_runtime_builder
from app.features.schedules.common import (
    A2A_SCHEDULE_SOURCE,
    A2AScheduleConflictError,
    ClaimedA2AScheduleTask,
)
from app.features.schedules.preflight import (
    open_schedule_invoke_session,
)
from app.features.schedules.runtime_summary import (
    derive_schedule_recovery_timeouts,
)
from app.features.schedules.service import (
    a2a_schedule_service,
)
from app.integrations.a2a_client import get_a2a_service
from app.runtime.ops_metrics import ops_metrics
from app.runtime.ops_metrics_refresh import refresh_db_pool_checked_out
from app.runtime.scheduler import get_scheduler
from app.schemas.a2a_invoke import A2AAgentInvokeRequest
from app.utils.async_cleanup import await_cancel_safe_suppressed
from app.utils.session_identity import normalize_non_empty_text
from app.utils.timezone_util import utc_now

logger = get_logger(__name__)

_A2A_SCHEDULE_JOB_ID = "a2a-schedule-dispatch-minute"
_A2A_SCHEDULE_WORKER_PREFIX = "a2a-schedule-worker"
_dispatch_workers_started = False
_dispatch_workers_lock = asyncio.Lock()
_dispatch_worker_tasks: set[asyncio.Task[None]] = set()
_NON_SQLA_DB_CONNECTIVITY_ERRORS = (ConnectionError, OSError)
_HEARTBEAT_WARNING_COOLDOWN_SECONDS = 60.0
_HEARTBEAT_LOCK_TIMEOUT_MS = 1000
_HEARTBEAT_STATEMENT_TIMEOUT_MS = 3000
_SCHEDULE_DISPATCH_ADVISORY_LOCK_KEY = 1_601_016_389


@dataclass(slots=True)
class _ClaimedTaskExecutionContext:
    task_id: UUID
    user_id: UUID
    agent_id: UUID
    prompt: str
    task_conversation_id: UUID | None
    execution_id: UUID
    runtime: Any


def _is_db_connectivity_issue(exc: Exception) -> bool:
    if isinstance(exc, _NON_SQLA_DB_CONNECTIVITY_ERRORS):
        return True
    if isinstance(exc, (OperationalError, InterfaceError)):
        return True
    if isinstance(exc, DBAPIError):
        return bool(getattr(exc, "connection_invalidated", False))
    return False


def _is_db_lock_contention_issue(exc: Exception) -> bool:
    return is_retryable_db_lock_failure(exc)


def _is_db_query_timeout_issue(exc: Exception) -> bool:
    return is_retryable_db_query_timeout(exc)


def _execution_metadata(
    *,
    task_id: UUID,
    execution_id: str,
    run_id: str,
    agent_id: UUID,
) -> dict[str, object]:
    return {
        "source": A2A_SCHEDULE_SOURCE,
        "schedule_task_id": str(task_id),
        "schedule_execution_id": execution_id,
        "run_id": run_id,
        "agent_id": str(agent_id),
    }


def _normalize_schedule_error_code(value: object) -> str | None:
    normalized = normalize_non_empty_text(value)
    if normalized is None:
        return None
    return normalized.replace("-", "_").lower()


def _resolve_schedule_failure_details(
    *,
    invoke_result: dict[str, object] | None = None,
    exc: BaseException | None = None,
) -> tuple[str | None, str | None]:
    if invoke_result is not None:
        error_code = _normalize_schedule_error_code(invoke_result.get("error_code"))
        internal_error_message = normalize_non_empty_text(
            invoke_result.get("internal_error_message")
        )
        public_error_message = normalize_non_empty_text(invoke_result.get("error"))
        response_content = normalize_non_empty_text(
            invoke_result.get("response_content")
        )
        return (
            error_code,
            internal_error_message or public_error_message or response_content,
        )

    if exc is None:
        return None, None

    error_code = _normalize_schedule_error_code(getattr(exc, "error_code", None))
    return error_code, normalize_non_empty_text(str(exc))


def _derive_recovery_timeouts() -> tuple[int, int]:
    return derive_schedule_recovery_timeouts()


async def _touch_schedule_run_heartbeat(*, claim: ClaimedA2AScheduleTask) -> bool:
    observed_at = utc_now()
    async with AsyncSessionLocal() as db:
        await set_postgres_local_timeouts(
            db,
            lock_timeout_ms=_HEARTBEAT_LOCK_TIMEOUT_MS,
            statement_timeout_ms=_HEARTBEAT_STATEMENT_TIMEOUT_MS,
        )
        stmt = (
            update(A2AScheduleExecution)
            .where(
                and_(
                    A2AScheduleExecution.task_id == claim.task_id,
                    A2AScheduleExecution.user_id == claim.user_id,
                    A2AScheduleExecution.run_id == claim.run_id,
                    A2AScheduleExecution.status == A2AScheduleExecution.STATUS_RUNNING,
                )
            )
            .values(last_heartbeat_at=observed_at)
        )
        result = await db.execute(stmt)
        rowcount = cast(int | None, getattr(result, "rowcount", None))
        if int(rowcount or 0) <= 0:
            return False
        await commit_safely(db)
    return True


async def _schedule_run_heartbeat_loop(
    *,
    claim: ClaimedA2AScheduleTask,
    stop_event: asyncio.Event,
) -> None:
    interval = max(float(settings.a2a_schedule_run_heartbeat_interval_seconds), 0.1)
    last_connectivity_warning_at: float | None = None
    last_lock_contention_warning_at: float | None = None
    last_query_timeout_warning_at: float | None = None
    last_unknown_warning_at: float | None = None
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            break
        except asyncio.TimeoutError:
            pass

        try:
            still_running = await _touch_schedule_run_heartbeat(claim=claim)
        except Exception as exc:
            now_monotonic = time.monotonic()
            if _is_db_connectivity_issue(exc):
                if (
                    last_connectivity_warning_at is None
                    or now_monotonic - last_connectivity_warning_at
                    >= _HEARTBEAT_WARNING_COOLDOWN_SECONDS
                ):
                    logger.warning(
                        "Skip schedule heartbeat update due to database connectivity issue.",
                        exc_info=exc,
                        extra={
                            "schedule_task_id": str(claim.task_id),
                            "run_id": str(claim.run_id),
                            "phase": "heartbeat",
                        },
                    )
                    last_connectivity_warning_at = now_monotonic
                continue
            if _is_db_lock_contention_issue(exc):
                if (
                    last_lock_contention_warning_at is None
                    or now_monotonic - last_lock_contention_warning_at
                    >= _HEARTBEAT_WARNING_COOLDOWN_SECONDS
                ):
                    logger.warning(
                        "Skip schedule heartbeat update due to lock contention.",
                        exc_info=exc,
                        extra={
                            "schedule_task_id": str(claim.task_id),
                            "run_id": str(claim.run_id),
                            "phase": "heartbeat",
                            "lock_contention": True,
                        },
                    )
                    last_lock_contention_warning_at = now_monotonic
                continue
            if _is_db_query_timeout_issue(exc):
                ops_metrics.increment_schedule_db_query_timeouts()
                if (
                    last_query_timeout_warning_at is None
                    or now_monotonic - last_query_timeout_warning_at
                    >= _HEARTBEAT_WARNING_COOLDOWN_SECONDS
                ):
                    logger.warning(
                        "Skip schedule heartbeat update due to database statement timeout.",
                        exc_info=exc,
                        extra={
                            "schedule_task_id": str(claim.task_id),
                            "run_id": str(claim.run_id),
                            "phase": "heartbeat",
                            "db_query_timeout": True,
                        },
                    )
                    last_query_timeout_warning_at = now_monotonic
                continue
            if (
                last_unknown_warning_at is None
                or now_monotonic - last_unknown_warning_at
                >= _HEARTBEAT_WARNING_COOLDOWN_SECONDS
            ):
                logger.warning(
                    "Schedule heartbeat update failed task=%s run_id=%s",
                    claim.task_id,
                    claim.run_id,
                    exc_info=exc,
                    extra={
                        "schedule_task_id": str(claim.task_id),
                        "run_id": str(claim.run_id),
                        "phase": "heartbeat",
                    },
                )
                last_unknown_warning_at = now_monotonic
            continue

        if not still_running:
            return


async def _ensure_task_session(
    *, db: AsyncSession, task: A2AScheduleTask
) -> tuple[ConversationThread, bool]:
    now = utc_now()
    task_conversation_policy = cast(str, task.conversation_policy)
    task_conversation_id = cast(UUID | None, task.conversation_id)
    task_user_id = cast(UUID, task.user_id)
    task_agent_id = cast(UUID, task.agent_id)
    task_name = cast(str, task.name)

    # Check conversation_policy
    if (
        task_conversation_policy == A2AScheduleTask.POLICY_REUSE
        and task_conversation_id
    ):
        stmt = select(ConversationThread).where(
            ConversationThread.id == task_conversation_id
        )
        existing_thread = await db.scalar(stmt)
        if (
            existing_thread
            and existing_thread.status != ConversationThread.STATUS_ARCHIVED
        ):
            setattr(existing_thread, "last_active_at", now)
            return existing_thread, False

    thread = ConversationThread(
        id=uuid4(),
        user_id=task_user_id,
        source=ConversationThread.SOURCE_SCHEDULED,
        agent_id=task_agent_id,
        agent_source="personal",
        title=f"[Scheduled] {task_name}",
        last_active_at=now,
        status=ConversationThread.STATUS_ACTIVE,
    )
    db.add(thread)
    await db.flush()
    setattr(task, "conversation_id", cast(UUID, thread.id))
    return thread, True


async def _refresh_ops_metrics() -> None:
    running_stmt = select(func.count(A2AScheduleExecution.id)).where(
        A2AScheduleExecution.status == A2AScheduleExecution.STATUS_RUNNING
    )
    try:
        async with AsyncSessionLocal() as db:
            running_count = int((await db.scalar(running_stmt)) or 0)
            ops_metrics.set_schedule_running_task_count(running_count)
            try:
                idle_in_tx_count = int(
                    (
                        await db.scalar(
                            text(
                                "SELECT count(*) FROM pg_stat_activity "
                                "WHERE datname = current_database() "
                                "AND state = 'idle in transaction'"
                            )
                        )
                    )
                    or 0
                )
                ops_metrics.set_db_idle_in_tx_count(idle_in_tx_count)
            except Exception:
                # pg_stat_activity may be unavailable depending on DB permissions.
                pass
        refresh_db_pool_checked_out(async_engine.sync_engine.pool)
    except Exception as exc:
        if not _is_db_connectivity_issue(exc):
            raise
        logger.warning(
            "Skip schedule ops metrics refresh due to database connectivity issue.",
            exc_info=exc,
            extra={"phase": "metrics"},
        )


async def _prepare_claimed_task_execution(
    *,
    claim: ClaimedA2AScheduleTask,
) -> _ClaimedTaskExecutionContext | None:
    async with AsyncSessionLocal() as db:
        logger.info(
            "Start scheduled run claim task=%s run_id=%s",
            claim.task_id,
            claim.run_id,
            extra={
                "schedule_task_id": str(claim.task_id),
                "run_id": str(claim.run_id),
                "phase": "claim",
            },
        )
        stmt = select(A2AScheduleTask).where(
            and_(
                A2AScheduleTask.id == claim.task_id,
                A2AScheduleTask.deleted_at.is_(None),
            )
        )
        task = await db.scalar(stmt)
        execution = await db.scalar(
            select(A2AScheduleExecution)
            .where(
                and_(
                    A2AScheduleExecution.task_id == claim.task_id,
                    A2AScheduleExecution.user_id == claim.user_id,
                    A2AScheduleExecution.run_id == claim.run_id,
                )
            )
            .limit(1)
        )
        if task is None or execution is None:
            logger.info(
                "Skip stale schedule claim task=%s run_id=%s because task or execution disappeared",
                claim.task_id,
                claim.run_id,
                extra={
                    "schedule_task_id": str(claim.task_id),
                    "run_id": str(claim.run_id),
                    "phase": "claim",
                },
            )
            return None
        if execution.status != A2AScheduleExecution.STATUS_RUNNING:
            logger.info(
                "Skip stale schedule claim task=%s run_id=%s because execution is no longer running",
                task.id,
                claim.run_id,
                extra={
                    "schedule_task_id": str(task.id),
                    "run_id": str(claim.run_id),
                    "phase": "claim",
                },
            )
            return None

        task_id = cast(UUID, task.id)
        task_user_id = cast(UUID, task.user_id)
        task_agent_id = cast(UUID, task.agent_id)
        task_prompt = cast(str, task.prompt)
        task_conversation_id = cast(UUID | None, task.conversation_id)
        execution_id = cast(UUID, execution.id)

        if not task.enabled:
            finished_at = utc_now()
            failure_message = "Task disabled or deleted before execution started"
            try:
                finalized = await a2a_schedule_service.finalize_task_run(
                    db,
                    task_id=task_id,
                    user_id=task_user_id,
                    run_id=claim.run_id,
                    final_status=A2AScheduleTask.STATUS_FAILED,
                    finished_at=finished_at,
                    conversation_id=task_conversation_id,
                    response_content=failure_message,
                    error_message=failure_message,
                )
            except A2AScheduleConflictError:
                ops_metrics.increment_schedule_finalize_lock_conflicts()
                logger.warning(
                    "Skip disabled-task finalize due to lock contention task=%s run_id=%s",
                    task.id,
                    claim.run_id,
                    extra={
                        "schedule_task_id": str(task.id),
                        "run_id": str(claim.run_id),
                        "phase": "finalize",
                        "finalize_conflict": True,
                    },
                )
                await rollback_safely(db)
                return None
            if finalized:
                await commit_safely(db)
            else:
                await rollback_safely(db)
            return None

        runtime = await a2a_runtime_builder.build(
            db,
            user_id=task_user_id,
            agent_id=task_agent_id,
        )
        if not runtime.agent_enabled:
            raise RuntimeError("Target A2A agent is disabled")

        return _ClaimedTaskExecutionContext(
            task_id=task_id,
            user_id=task_user_id,
            agent_id=task_agent_id,
            prompt=task_prompt,
            task_conversation_id=task_conversation_id,
            execution_id=execution_id,
            runtime=runtime,
        )


async def _execute_claimed_task(*, claim: ClaimedA2AScheduleTask) -> None:
    task_id = claim.task_id
    task_user_id = claim.user_id
    task_agent_id = claim.agent_id
    task_conversation_id = claim.conversation_id
    task_prompt = claim.prompt
    execution_id_str = "unknown"
    thread_id: UUID | None = None
    is_new_thread = False
    runtime: Any = None
    heartbeat_stop_event = asyncio.Event()
    heartbeat_task: asyncio.Task[None] | None = None

    try:
        context = await _prepare_claimed_task_execution(claim=claim)
        if context is None:
            return

        task_id = context.task_id
        task_user_id = context.user_id
        task_agent_id = context.agent_id
        task_prompt = context.prompt
        task_conversation_id = context.task_conversation_id
        execution_id_str = str(context.execution_id)
        runtime = context.runtime

        metadata = _execution_metadata(
            task_id=task_id,
            execution_id=execution_id_str,
            run_id=str(claim.run_id),
            agent_id=task_agent_id,
        )
        gateway = cast(Any, get_a2a_service()).gateway
        async with open_schedule_invoke_session(
            gateway=gateway,
            runtime=runtime,
        ) as invoke_session:
            async with AsyncSessionLocal() as db:
                task = await db.scalar(
                    select(A2AScheduleTask).where(
                        and_(
                            A2AScheduleTask.id == task_id,
                            A2AScheduleTask.user_id == task_user_id,
                            A2AScheduleTask.deleted_at.is_(None),
                        )
                    )
                )
                execution = await db.scalar(
                    select(A2AScheduleExecution)
                    .where(
                        and_(
                            A2AScheduleExecution.task_id == task_id,
                            A2AScheduleExecution.user_id == task_user_id,
                            A2AScheduleExecution.run_id == claim.run_id,
                        )
                    )
                    .limit(1)
                )
                if task is None or execution is None:
                    raise RuntimeError("Execution disappeared before invoke start")
                if execution.status != A2AScheduleExecution.STATUS_RUNNING:
                    raise RuntimeError("Execution is no longer running before invoke")

                thread, is_new_thread = await _ensure_task_session(
                    db=db,
                    task=task,
                )
                thread_id = cast(UUID, thread.id)
                setattr(execution, "conversation_id", thread_id)
                await commit_safely(db)

            # Keep DB work in short-lived sessions so remote invoke does not pin a
            # pooled connection for the full task runtime.
            heartbeat_task = asyncio.create_task(
                _schedule_run_heartbeat_loop(
                    claim=claim,
                    stop_event=heartbeat_stop_event,
                )
            )
            invoke_payload = A2AAgentInvokeRequest(
                query=task_prompt,
                conversationId=str(thread_id),
                metadata=metadata,
            )
            try:
                invoke_result = await run_background_invoke(
                    gateway=gateway,
                    runtime=runtime,
                    user_id=task_user_id,
                    agent_id=task_agent_id,
                    agent_source="personal",
                    payload=invoke_payload,
                    validate_message=lambda _payload: [],
                    logger=logger,
                    log_extra={
                        "schedule_task_id": str(task_id),
                        "schedule_execution_id": execution_id_str,
                        "run_id": str(claim.run_id),
                        "phase": "invoke",
                        "agent_id": str(task_agent_id),
                        "user_id": str(task_user_id),
                    },
                    total_timeout_seconds=settings.a2a_schedule_task_invoke_timeout,
                    idle_timeout_seconds=settings.a2a_schedule_task_stream_idle_timeout,
                    invoke_session=invoke_session,
                )
            finally:
                heartbeat_stop_event.set()
                if heartbeat_task is not None:
                    with contextlib.suppress(Exception):
                        await heartbeat_task

        success = bool(invoke_result.get("success"))
        response_content = str(invoke_result.get("response_content") or "")
        message_refs = invoke_result.get("message_refs") or {}
        should_cleanup_ephemeral_thread = bool(
            (not success)
            and (not message_refs.get("user_message_id"))
            and is_new_thread
            and thread_id is not None
        )
        resolved_conversation_id = None
        if not should_cleanup_ephemeral_thread:
            resolved_conversation_id = cast(
                UUID | None,
                message_refs.get("conversation_id")
                or invoke_result.get("conversation_id")
                or thread_id
                or task_conversation_id,
            )
        finished_at = utc_now()

        final_status = (
            A2AScheduleTask.STATUS_SUCCESS if success else A2AScheduleTask.STATUS_FAILED
        )
        execution_error_code = None
        execution_error_message = None
        if not success:
            execution_error_code, execution_error_message = (
                _resolve_schedule_failure_details(invoke_result=invoke_result)
            )
            if execution_error_message is not None:
                execution_error_message = execution_error_message[:2000]

        async with AsyncSessionLocal() as db:
            execution = await db.scalar(
                select(A2AScheduleExecution)
                .where(
                    and_(
                        A2AScheduleExecution.task_id == task_id,
                        A2AScheduleExecution.user_id == task_user_id,
                        A2AScheduleExecution.run_id == claim.run_id,
                    )
                )
                .limit(1)
            )
            task = await db.scalar(
                select(A2AScheduleTask)
                .where(
                    and_(
                        A2AScheduleTask.id == task_id,
                        A2AScheduleTask.user_id == task_user_id,
                    )
                )
                .limit(1)
            )
            try:
                finalized = await a2a_schedule_service.finalize_task_run(
                    db,
                    task_id=task_id,
                    user_id=task_user_id,
                    run_id=claim.run_id,
                    final_status=final_status,
                    finished_at=finished_at,
                    conversation_id=resolved_conversation_id,
                    response_content=response_content,
                    error_message=execution_error_message,
                    error_code=execution_error_code,
                    user_message_id=message_refs.get("user_message_id"),
                    agent_message_id=message_refs.get("agent_message_id"),
                )
            except A2AScheduleConflictError:
                ops_metrics.increment_schedule_finalize_lock_conflicts()
                logger.warning(
                    "Schedule run finalize deferred due to lock contention task=%s run_id=%s",
                    task_id,
                    claim.run_id,
                    extra={
                        "schedule_task_id": str(task_id),
                        "schedule_execution_id": execution_id_str,
                        "run_id": str(claim.run_id),
                        "phase": "finalize",
                        "finalize_conflict": True,
                    },
                )
                await rollback_safely(db)
                return

            if not finalized:
                logger.warning(
                    "Schedule run finalize skipped due to run mismatch task=%s run_id=%s",
                    task_id,
                    claim.run_id,
                    extra={
                        "schedule_task_id": str(task_id),
                        "run_id": str(claim.run_id),
                        "phase": "finalize",
                    },
                )
                await rollback_safely(db)
                return

            if should_cleanup_ephemeral_thread and thread_id is not None:
                if execution is not None:
                    setattr(execution, "conversation_id", None)
                if task is not None and task_conversation_id == thread_id:
                    setattr(task, "conversation_id", None)
                thread_to_delete = await db.scalar(
                    select(ConversationThread)
                    .where(ConversationThread.id == thread_id)
                    .limit(1)
                )
                if thread_to_delete is not None:
                    await db.delete(thread_to_delete)

            if (
                execution is not None
                and execution.started_at is not None
                and execution.finished_at is not None
            ):
                latency_ms = (
                    execution.finished_at - execution.started_at
                ).total_seconds() * 1000
                ops_metrics.observe_schedule_run_finalize_latency(latency_ms)

            await commit_safely(db)

    except Exception as exc:  # pragma: no cover - defensive path
        heartbeat_stop_event.set()
        if heartbeat_task is not None:
            with contextlib.suppress(Exception):
                await heartbeat_task

        finished_at = utc_now()
        finalize_error_code: str | None
        finalize_failure_message: str | None
        finalize_error_code, finalize_failure_message = (
            _resolve_schedule_failure_details(exc=exc)
        )
        finalize_failure_message = (
            finalize_failure_message or "Schedule execution failed"
        )[:2000]

        async with AsyncSessionLocal() as db:
            execution = await db.scalar(
                select(A2AScheduleExecution)
                .where(
                    and_(
                        A2AScheduleExecution.task_id == task_id,
                        A2AScheduleExecution.user_id == task_user_id,
                        A2AScheduleExecution.run_id == claim.run_id,
                    )
                )
                .limit(1)
            )
            task = await db.scalar(
                select(A2AScheduleTask)
                .where(
                    and_(
                        A2AScheduleTask.id == task_id,
                        A2AScheduleTask.user_id == task_user_id,
                    )
                )
                .limit(1)
            )
            try:
                finalized = await a2a_schedule_service.finalize_task_run(
                    db,
                    task_id=task_id,
                    user_id=task_user_id,
                    run_id=claim.run_id,
                    final_status=A2AScheduleTask.STATUS_FAILED,
                    finished_at=finished_at,
                    conversation_id=(
                        None if thread_id is not None and is_new_thread else thread_id
                    ),
                    response_content=(
                        cast(str | None, execution.response_content)
                        if execution is not None and execution.response_content
                        else finalize_failure_message
                    ),
                    error_message=finalize_failure_message,
                    error_code=finalize_error_code,
                    user_message_id=(
                        cast(UUID | None, execution.user_message_id)
                        if execution is not None
                        else None
                    ),
                    agent_message_id=(
                        cast(UUID | None, execution.agent_message_id)
                        if execution is not None
                        else None
                    ),
                )
            except A2AScheduleConflictError:
                ops_metrics.increment_schedule_finalize_lock_conflicts()
                logger.warning(
                    "Schedule run failure finalize deferred due to lock contention task=%s run_id=%s",
                    task_id,
                    claim.run_id,
                    extra={
                        "schedule_task_id": str(task_id),
                        "run_id": str(claim.run_id),
                        "phase": "finalize",
                        "finalize_conflict": True,
                    },
                )
                await rollback_safely(db)
                return

            if not finalized:
                logger.warning(
                    "Schedule run failure finalize skipped due to run mismatch task=%s run_id=%s",
                    task_id,
                    claim.run_id,
                    extra={
                        "schedule_task_id": str(task_id),
                        "run_id": str(claim.run_id),
                        "phase": "finalize",
                    },
                )
                await rollback_safely(db)
                return

            if thread_id is not None and is_new_thread:
                if execution is not None:
                    setattr(execution, "conversation_id", None)
                if task is not None and task_conversation_id == thread_id:
                    setattr(task, "conversation_id", None)
                thread_to_delete = await db.scalar(
                    select(ConversationThread)
                    .where(ConversationThread.id == thread_id)
                    .limit(1)
                )
                if thread_to_delete is not None:
                    await db.delete(thread_to_delete)
            if execution is not None and execution.started_at:
                latency_ms = (finished_at - execution.started_at).total_seconds() * 1000
                ops_metrics.observe_schedule_run_finalize_latency(latency_ms)
            try:
                await commit_safely(db)
            except Exception as commit_error:  # pragma: no cover - defensive
                await rollback_safely(db)
                logger.error(
                    "Failed to persist schedule execution failure task=%s err=%s",
                    task_id,
                    commit_error,
                    exc_info=commit_error,
                )
            logger.error(
                "Scheduled A2A execution failed task=%s execution=%s err=%s",
                task_id,
                execution_id_str,
                exc,
                exc_info=exc,
                extra={
                    "schedule_task_id": str(task_id),
                    "schedule_execution_id": execution_id_str,
                    "run_id": str(claim.run_id),
                    "phase": "finalize",
                },
            )


@contextlib.asynccontextmanager
async def _try_hold_dispatch_leader_lock() -> AsyncIterator[bool]:
    async with async_engine.connect() as lock_conn:
        dialect_name = getattr(getattr(lock_conn, "dialect", None), "name", None)
        if dialect_name != "postgresql":
            yield True
            return

        acquired = bool(
            await lock_conn.scalar(
                text("SELECT pg_try_advisory_lock(:lock_key)"),
                {"lock_key": _SCHEDULE_DISPATCH_ADVISORY_LOCK_KEY},
            )
        )
        await await_cancel_safe_suppressed(lock_conn.rollback())
        if not acquired:
            ops_metrics.increment_schedule_leader_lock_contentions()
            yield False
            return

        unlocked = False
        try:
            yield True
        finally:
            try:
                unlocked = bool(
                    await lock_conn.scalar(
                        text("SELECT pg_advisory_unlock(:lock_key)"),
                        {"lock_key": _SCHEDULE_DISPATCH_ADVISORY_LOCK_KEY},
                    )
                )
                if not unlocked:
                    logger.error(
                        "Failed to release A2A schedule advisory leader lock because lock was no longer held."
                    )
            except Exception as exc:
                logger.error(
                    "Failed to release A2A schedule advisory leader lock due to unexpected DB error.",
                    exc_info=exc,
                )
            if not unlocked:
                ops_metrics.increment_schedule_leader_lock_release_failures()
                with contextlib.suppress(Exception):
                    await lock_conn.invalidate()
            await await_cancel_safe_suppressed(lock_conn.rollback())


async def _schedule_worker_loop(worker_index: int) -> None:
    worker_name = f"{_A2A_SCHEDULE_WORKER_PREFIX}-{worker_index}"
    logger.info("Started scheduled task worker %s", worker_name)
    while True:
        try:
            async with AsyncSessionLocal() as db:
                claim = await a2a_schedule_service.claim_next_pending_execution(db)

            if claim is None:
                # No tasks pending, sleep briefly
                await asyncio.sleep(1.0)
                continue

            await _execute_claimed_task(claim=claim)
        except asyncio.CancelledError:
            break
        except Exception as exc:  # pragma: no cover - defensive safety
            logger.error(
                "Unhandled exception in scheduled worker %s err=%s",
                worker_name,
                exc,
                exc_info=exc,
            )
            await asyncio.sleep(1.0)


def _prune_finished_worker_tasks() -> None:
    finished = {task for task in _dispatch_worker_tasks if task.done()}
    for task in finished:
        _dispatch_worker_tasks.discard(task)
        with contextlib.suppress(Exception):
            _ = task.result()


async def _ensure_schedule_workers_started() -> None:
    global _dispatch_workers_started

    if _dispatch_workers_started:
        _prune_finished_worker_tasks()
        if _dispatch_worker_tasks:
            return
        _dispatch_workers_started = False

    async with _dispatch_workers_lock:
        if _dispatch_workers_started:
            _prune_finished_worker_tasks()
            if _dispatch_worker_tasks:
                return
            _dispatch_workers_started = False

        worker_count = max(int(settings.a2a_schedule_worker_concurrency), 1)
        for index in range(worker_count):
            worker_task = asyncio.create_task(_schedule_worker_loop(index + 1))
            _dispatch_worker_tasks.add(worker_task)
        _dispatch_workers_started = True
        logger.info("Started %d scheduled task worker(s)", worker_count)


async def dispatch_due_a2a_schedules(*, batch_size: int = 20) -> None:
    async with _try_hold_dispatch_leader_lock() as has_leader_lock:
        if not has_leader_lock:
            logger.debug(
                "Skip A2A schedule dispatch: advisory leader lock is held by another process."
            )
            return

        # Recover stale "running" tasks first so the UI doesn't get stuck forever if a
        # worker crashes after claiming a task but before persisting the execution.
        try:
            heartbeat_timeout_seconds, hard_timeout_seconds = (
                _derive_recovery_timeouts()
            )
            recovered = await a2a_schedule_service.recover_stale_running_tasks(
                timeout_seconds=heartbeat_timeout_seconds,
                hard_timeout_seconds=hard_timeout_seconds,
            )
        except Exception as exc:
            if _is_db_lock_contention_issue(exc):
                logger.warning(
                    "Skip stale-task recovery this cycle due to lock contention; continue dispatch.",
                    exc_info=exc,
                    extra={"phase": "recovery", "lock_contention": True},
                )
                recovered = 0
            elif _is_db_query_timeout_issue(exc):
                ops_metrics.increment_schedule_db_query_timeouts()
                logger.warning(
                    "Skip stale-task recovery this cycle due to database statement timeout; continue dispatch.",
                    exc_info=exc,
                    extra={"phase": "recovery", "db_query_timeout": True},
                )
                recovered = 0
            elif _is_db_connectivity_issue(exc):
                logger.warning(
                    "Skip A2A schedule dispatch: database connectivity issue during stale-task recovery.",
                    exc_info=exc,
                    extra={"phase": "recovery"},
                )
                return
            else:
                raise
        if recovered:
            logger.warning(
                "Recovered %d stale scheduled A2A task(s).",
                recovered,
                extra={"phase": "recovery"},
            )

        await _ensure_schedule_workers_started()

        try:
            async with AsyncSessionLocal() as db:
                enqueued = await a2a_schedule_service.enqueue_due_tasks(
                    db, batch_size=batch_size
                )
        except Exception as exc:
            if _is_db_lock_contention_issue(exc):
                logger.warning(
                    "Stop enqueuing due tasks this cycle due to lock contention.",
                    exc_info=exc,
                    extra={"phase": "enqueue", "lock_contention": True},
                )
                enqueued = 0
            elif _is_db_query_timeout_issue(exc):
                ops_metrics.increment_schedule_db_query_timeouts()
                logger.warning(
                    "Stop enqueuing due tasks this cycle due to database statement timeout.",
                    exc_info=exc,
                    extra={"phase": "enqueue", "db_query_timeout": True},
                )
                enqueued = 0
            elif _is_db_connectivity_issue(exc):
                logger.warning(
                    "Skip A2A schedule dispatch: database connectivity issue while enqueuing due tasks.",
                    exc_info=exc,
                    extra={"phase": "enqueue"},
                )
                return
            else:
                raise

        if enqueued:
            logger.info(
                "Enqueued %d scheduled A2A task(s).",
                enqueued,
            )
        await _refresh_ops_metrics()


def ensure_a2a_schedule_job() -> None:
    scheduler = get_scheduler()
    if scheduler.get_job(_A2A_SCHEDULE_JOB_ID):
        return

    scheduler.add_job(
        dispatch_due_a2a_schedules,
        trigger=CronTrigger(minute="*"),
        id=_A2A_SCHEDULE_JOB_ID,
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=120,
        coalesce=True,
    )
    logger.info("Registered minute-level A2A schedule dispatcher job.")

    scheduler.add_job(
        dispatch_due_a2a_schedules,
        trigger=DateTrigger(run_date=utc_now() + timedelta(seconds=20)),
        id=f"{_A2A_SCHEDULE_JOB_ID}-initial",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=60,
        coalesce=True,
    )
    logger.info("Scheduled warm-up A2A schedule dispatcher run.")
