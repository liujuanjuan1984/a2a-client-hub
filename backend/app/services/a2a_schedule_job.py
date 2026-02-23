"""Scheduler job that dispatches due A2A schedule tasks."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from sqlalchemy import and_, select

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models.a2a_schedule_execution import A2AScheduleExecution
from app.db.models.a2a_schedule_task import A2AScheduleTask
from app.db.models.conversation_thread import ConversationThread
from app.db.session import AsyncSessionLocal
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
from app.services.scheduler import get_scheduler
from app.utils.timezone_util import utc_now

logger = get_logger(__name__)

_A2A_SCHEDULE_JOB_ID = "a2a-schedule-dispatch-minute"


def _execution_metadata(task: A2AScheduleTask, execution_id: str) -> dict[str, object]:
    return {
        "source": A2A_SCHEDULE_SOURCE,
        "schedule_task_id": str(task.id),
        "schedule_execution_id": execution_id,
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


async def _execute_claimed_task(*, claim: ClaimedA2AScheduleTask) -> None:
    async with AsyncSessionLocal() as db:
        stmt = select(A2AScheduleTask).where(
            and_(
                A2AScheduleTask.id == claim.task_id,
                A2AScheduleTask.deleted_at.is_(None),
            )
        )
        task = await db.scalar(stmt)
        if task is None:
            return
        if not task.enabled:
            if task.last_run_status == A2AScheduleTask.STATUS_RUNNING:
                task.last_run_status = A2AScheduleTask.STATUS_IDLE
                await commit_safely(db)
            return

        started_at = utc_now()
        execution = A2AScheduleExecution(
            user_id=task.user_id,
            task_id=task.id,
            scheduled_for=claim.scheduled_for,
            started_at=started_at,
            status=A2AScheduleExecution.STATUS_RUNNING,
        )
        try:
            db.add(execution)
            await db.flush()
            metadata = _execution_metadata(task, str(execution.id))
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

            task.last_run_at = execution.finished_at
            task.last_run_status = (
                A2AScheduleTask.STATUS_SUCCESS
                if success
                else A2AScheduleTask.STATUS_FAILED
            )
            if success:
                task.consecutive_failures = 0
            else:
                task.consecutive_failures = (task.consecutive_failures or 0) + 1
                if (
                    task.consecutive_failures
                    >= settings.a2a_schedule_task_failure_threshold
                ):
                    task.enabled = False

            await commit_safely(db)

        except Exception as exc:  # pragma: no cover - defensive path
            task.last_run_at = utc_now()
            task.last_run_status = A2AScheduleTask.STATUS_FAILED
            task.consecutive_failures = (task.consecutive_failures or 0) + 1
            if (
                task.consecutive_failures
                >= settings.a2a_schedule_task_failure_threshold
            ):
                task.enabled = False
            execution.status = A2AScheduleExecution.STATUS_FAILED
            execution.finished_at = task.last_run_at
            execution.error_message = str(exc)[:2000]
            if not execution.response_content:
                execution.response_content = execution.error_message
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
            )


async def dispatch_due_a2a_schedules(*, batch_size: int = 20) -> None:
    # Recover stale "running" tasks first so the UI doesn't get stuck forever if a
    # worker crashes after claiming a task but before persisting the execution.
    async with AsyncSessionLocal() as db:
        recovered = await a2a_schedule_service.recover_stale_running_tasks(db)
    if recovered:
        logger.warning("Recovered %d stale scheduled A2A task(s).", recovered)

    processed = 0
    while processed < max(batch_size, 1):
        async with AsyncSessionLocal() as db:
            claim = await a2a_schedule_service.claim_next_due_task(db)

        if claim is None:
            break

        await _execute_claimed_task(claim=claim)
        processed += 1

    if processed:
        logger.info("Processed %d scheduled A2A task(s).", processed)


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
