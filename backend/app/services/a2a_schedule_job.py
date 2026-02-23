"""Scheduler job that dispatches due A2A schedule tasks."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import timedelta
from uuid import uuid4

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from sqlalchemy import and_, func, select, text

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models.a2a_schedule_execution import A2AScheduleExecution
from app.db.models.a2a_schedule_task import A2AScheduleTask
from app.db.models.conversation_thread import ConversationThread
from app.db.session import AsyncSessionLocal, async_engine
from app.db.transaction import commit_safely, rollback_safely
from app.integrations.a2a_client import get_a2a_service
from app.schemas.a2a_invoke import A2AAgentInvokeRequest
from app.services.a2a_runtime import a2a_runtime_builder
from app.services.a2a_schedule_service import (
    A2A_SCHEDULE_SOURCE,
    ClaimedA2AScheduleTask,
    a2a_schedule_service,
)
from app.services.invoke_route_runner import run_background_invoke
from app.services.ops_metrics import ops_metrics
from app.services.scheduler import get_scheduler
from app.utils.timezone_util import utc_now

logger = get_logger(__name__)

_A2A_SCHEDULE_JOB_ID = "a2a-schedule-dispatch-minute"
_A2A_SCHEDULE_WORKER_PREFIX = "a2a-schedule-worker"
_dispatch_workers_started = False
_dispatch_workers_lock = asyncio.Lock()
_dispatch_queue: asyncio.Queue[ClaimedA2AScheduleTask] = asyncio.Queue()
_dispatch_worker_tasks: set[asyncio.Task[None]] = set()


def _execution_metadata(
    task: A2AScheduleTask,
    execution_id: str,
    run_id: str,
) -> dict[str, object]:
    return {
        "source": A2A_SCHEDULE_SOURCE,
        "schedule_task_id": str(task.id),
        "schedule_execution_id": execution_id,
        "run_id": run_id,
        "agent_id": str(task.agent_id),
    }


async def _ensure_task_session(*, db, task: A2AScheduleTask) -> ConversationThread:
    now = utc_now()
    thread = ConversationThread(
        id=uuid4(),
        user_id=task.user_id,
        source=ConversationThread.SOURCE_SCHEDULED,
        agent_id=task.agent_id,
        agent_source="personal",
        title=f"[Scheduled] {task.name}",
        last_active_at=now,
        status=ConversationThread.STATUS_ACTIVE,
    )
    db.add(thread)
    await db.flush()
    task.conversation_id = thread.id
    return thread


def _pool_checked_out() -> int:
    pool = getattr(async_engine.sync_engine, "pool", None)
    checked_out = getattr(pool, "checkedout", None)
    if not callable(checked_out):
        return 0
    try:
        return max(int(checked_out()), 0)
    except Exception:
        return 0


async def _refresh_ops_metrics() -> None:
    running_stmt = select(func.count(A2AScheduleTask.id)).where(
        and_(
            A2AScheduleTask.deleted_at.is_(None),
            A2AScheduleTask.last_run_status == A2AScheduleTask.STATUS_RUNNING,
            A2AScheduleTask.current_run_id.is_not(None),
        )
    )
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
    ops_metrics.set_db_pool_checked_out(_pool_checked_out())


async def _execute_claimed_task(*, claim: ClaimedA2AScheduleTask) -> None:
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
        if task is None:
            return
        if task.current_run_id != claim.run_id:
            logger.info(
                "Skip stale schedule claim task=%s run_id=%s current_run_id=%s",
                task.id,
                claim.run_id,
                task.current_run_id,
                extra={
                    "schedule_task_id": str(task.id),
                    "run_id": str(claim.run_id),
                    "phase": "claim",
                },
            )
            return
        if not task.enabled:
            if task.last_run_status == A2AScheduleTask.STATUS_RUNNING:
                await a2a_schedule_service.finalize_task_run(
                    db,
                    task_id=task.id,
                    user_id=task.user_id,
                    run_id=claim.run_id,
                    final_status=A2AScheduleTask.STATUS_IDLE,
                    finished_at=utc_now(),
                    conversation_id=task.conversation_id,
                )
                await commit_safely(db)
            return

        execution = await db.scalar(
            select(A2AScheduleExecution)
            .where(
                and_(
                    A2AScheduleExecution.task_id == task.id,
                    A2AScheduleExecution.user_id == task.user_id,
                    A2AScheduleExecution.run_id == claim.run_id,
                )
            )
            .limit(1)
            .with_for_update(skip_locked=True)
        )

        try:
            if execution is None:
                started_at = utc_now()
                execution = A2AScheduleExecution(
                    user_id=task.user_id,
                    task_id=task.id,
                    run_id=claim.run_id,
                    scheduled_for=claim.scheduled_for,
                    started_at=started_at,
                    status=A2AScheduleExecution.STATUS_RUNNING,
                )
                db.add(execution)
                await db.flush()
            metadata = _execution_metadata(task, str(execution.id), str(claim.run_id))
            runtime = await a2a_runtime_builder.build(
                db,
                user_id=task.user_id,
                agent_id=task.agent_id,
            )
            if not bool(getattr(runtime.agent, "enabled", True)):
                raise RuntimeError("Target A2A agent is disabled")
            thread = await _ensure_task_session(
                db=db,
                task=task,
            )
            execution.conversation_id = thread.id
            await commit_safely(db)
            invoke_payload = A2AAgentInvokeRequest(
                query=task.prompt,
                conversationId=str(thread.id),
                metadata=metadata,
            )
            invoke_result = await run_background_invoke(
                db=db,
                gateway=get_a2a_service().gateway,
                runtime=runtime,
                user_id=task.user_id,
                agent_id=task.agent_id,
                agent_source="personal",
                payload=invoke_payload,
                validate_message=lambda _payload: [],
                logger=logger,
                log_extra={
                    "schedule_task_id": str(task.id),
                    "schedule_execution_id": str(execution.id),
                    "run_id": str(claim.run_id),
                    "phase": "invoke",
                    "agent_id": str(task.agent_id),
                    "user_id": str(task.user_id),
                },
                total_timeout_seconds=settings.a2a_schedule_task_invoke_timeout,
                idle_timeout_seconds=settings.a2a_schedule_task_stream_idle_timeout,
            )
            success = bool(invoke_result.get("success"))
            response_content = str(invoke_result.get("response_content") or "")
            message_refs = invoke_result.get("message_refs") or {}
            execution.conversation_id = (
                message_refs.get("conversation_id")
                or invoke_result.get("conversation_id")
                or thread.id
            )
            execution.user_message_id = message_refs.get("user_message_id")
            execution.agent_message_id = message_refs.get("agent_message_id")
            execution.response_content = response_content
            execution.finished_at = utc_now()
            execution.status = (
                A2AScheduleExecution.STATUS_SUCCESS
                if success
                else A2AScheduleExecution.STATUS_FAILED
            )
            execution.error_message = (
                None
                if success
                else (
                    response_content[:2000]
                    or str(invoke_result.get("error") or "")[:2000]
                    or None
                )
            )
            if execution.started_at and execution.finished_at:
                latency_ms = (
                    execution.finished_at - execution.started_at
                ).total_seconds() * 1000
                ops_metrics.observe_schedule_run_finalize_latency(latency_ms)

            final_status = (
                A2AScheduleTask.STATUS_SUCCESS
                if success
                else A2AScheduleTask.STATUS_FAILED
            )
            finalized = await a2a_schedule_service.finalize_task_run(
                db,
                task_id=task.id,
                user_id=task.user_id,
                run_id=claim.run_id,
                final_status=final_status,
                finished_at=execution.finished_at,
                conversation_id=execution.conversation_id,
            )
            if not finalized:
                logger.warning(
                    "Schedule run finalize skipped due to run mismatch task=%s run_id=%s",
                    task.id,
                    claim.run_id,
                    extra={
                        "schedule_task_id": str(task.id),
                        "schedule_execution_id": str(execution.id),
                        "run_id": str(claim.run_id),
                        "phase": "finalize",
                    },
                )

            await commit_safely(db)

        except Exception as exc:  # pragma: no cover - defensive path
            finished_at = utc_now()
            if execution is None:
                execution = A2AScheduleExecution(
                    user_id=task.user_id,
                    task_id=task.id,
                    run_id=claim.run_id,
                    scheduled_for=claim.scheduled_for,
                    started_at=finished_at,
                    status=A2AScheduleExecution.STATUS_RUNNING,
                    conversation_id=task.conversation_id,
                )
                db.add(execution)
                await db.flush()

            execution.status = A2AScheduleExecution.STATUS_FAILED
            execution.finished_at = finished_at
            execution.error_message = str(exc)[:2000]
            if not execution.response_content:
                execution.response_content = execution.error_message
            if execution.started_at:
                latency_ms = (finished_at - execution.started_at).total_seconds() * 1000
                ops_metrics.observe_schedule_run_finalize_latency(latency_ms)
            await a2a_schedule_service.finalize_task_run(
                db,
                task_id=task.id,
                user_id=task.user_id,
                run_id=claim.run_id,
                final_status=A2AScheduleTask.STATUS_FAILED,
                finished_at=finished_at,
                conversation_id=execution.conversation_id or task.conversation_id,
            )
            try:
                await commit_safely(db)
            except Exception as commit_error:  # pragma: no cover - defensive
                await rollback_safely(db)
                logger.error(
                    "Failed to persist schedule execution failure task=%s err=%s",
                    task.id,
                    commit_error,
                    exc_info=commit_error,
                )
            logger.error(
                "Scheduled A2A execution failed task=%s execution=%s err=%s",
                task.id,
                execution.id,
                exc,
                exc_info=exc,
                extra={
                    "schedule_task_id": str(task.id),
                    "schedule_execution_id": str(execution.id),
                    "run_id": str(claim.run_id),
                    "phase": "finalize",
                },
            )


async def _schedule_worker_loop(worker_index: int) -> None:
    worker_name = f"{_A2A_SCHEDULE_WORKER_PREFIX}-{worker_index}"
    logger.info("Started scheduled task worker %s", worker_name)
    while True:
        claim = await _dispatch_queue.get()
        try:
            await _execute_claimed_task(claim=claim)
        except Exception as exc:  # pragma: no cover - defensive safety
            logger.error(
                "Unhandled exception in scheduled worker %s task=%s err=%s",
                worker_name,
                claim.task_id,
                exc,
                exc_info=exc,
            )
        finally:
            _dispatch_queue.task_done()


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
    # Recover stale "running" tasks first so the UI doesn't get stuck forever if a
    # worker crashes after claiming a task but before persisting the execution.
    async with AsyncSessionLocal() as db:
        recovered = await a2a_schedule_service.recover_stale_running_tasks(
            db,
            timeout_seconds=int(settings.a2a_schedule_run_lease_seconds),
        )
    if recovered:
        logger.warning(
            "Recovered %d stale scheduled A2A task(s).",
            recovered,
            extra={"phase": "recovery"},
        )

    await _ensure_schedule_workers_started()

    enqueued = 0
    while enqueued < max(batch_size, 1):
        async with AsyncSessionLocal() as db:
            claim = await a2a_schedule_service.claim_next_due_task(db)

        if claim is None:
            break

        _dispatch_queue.put_nowait(claim)
        enqueued += 1

    if enqueued:
        logger.info(
            "Enqueued %d scheduled A2A task(s). queue_size=%d",
            enqueued,
            _dispatch_queue.qsize(),
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


__all__ = ["dispatch_due_a2a_schedules", "ensure_a2a_schedule_job"]
