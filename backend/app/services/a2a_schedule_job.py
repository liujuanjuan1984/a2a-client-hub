"""Scheduler job that dispatches due A2A schedule tasks."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from sqlalchemy import and_, select

from app.cardbox.service import cardbox_service
from app.core.config import settings
from app.core.logging import get_logger
from app.db.models.a2a_schedule_execution import A2AScheduleExecution
from app.db.models.a2a_schedule_task import A2AScheduleTask
from app.db.models.agent_session import AgentSession
from app.db.session import AsyncSessionLocal
from app.db.transaction import commit_safely, rollback_safely
from app.handlers import agent_message as agent_message_handler
from app.integrations.a2a_client import get_a2a_service
from app.services.a2a_runtime import a2a_runtime_builder
from app.services.a2a_schedule_service import (
    A2A_SCHEDULE_SOURCE,
    ClaimedA2AScheduleTask,
    a2a_schedule_service,
)
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


async def _ensure_task_session(
    *, db, task: A2AScheduleTask, agent_name: str
) -> AgentSession:
    session = None
    if task.session_id is not None:
        stmt = select(AgentSession).where(
            and_(
                AgentSession.id == task.session_id,
                AgentSession.user_id == task.user_id,
                AgentSession.deleted_at.is_(None),
            )
        )
        session = await db.scalar(stmt)

    if session is None:
        now = utc_now()
        session = AgentSession(
            id=uuid4(),
            user_id=task.user_id,
            name=f"[Scheduled] {task.name}",
            last_activity_at=now,
            module_key=agent_name,
            session_type=AgentSession.TYPE_SCHEDULED,
        )
        db.add(session)
        await db.flush()
        cardbox_service.ensure_session_box(session)
        task.session_id = session.id
    else:
        if session.session_type != AgentSession.TYPE_SCHEDULED:
            session.session_type = AgentSession.TYPE_SCHEDULED
        if agent_name:
            session.module_key = agent_name

    return session


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
        db.add(execution)
        await db.flush()

        metadata = _execution_metadata(task, str(execution.id))

        try:
            runtime = await a2a_runtime_builder.build(
                db,
                user_id=task.user_id,
                agent_id=task.agent_id,
            )
            if not bool(getattr(runtime.agent, "enabled", True)):
                raise RuntimeError("Target A2A agent is disabled")
            session = await _ensure_task_session(
                db=db,
                task=task,
                agent_name=runtime.resolved.name,
            )
            execution.session_id = session.id

            user_message = await agent_message_handler.create_agent_message(
                db,
                user_id=task.user_id,
                content=task.prompt,
                sender="automation",
                session_id=session.id,
                session=session,
                metadata=metadata,
            )
            execution.user_message_id = user_message.id

            result = await get_a2a_service().gateway.invoke(
                resolved=runtime.resolved,
                query=task.prompt,
                metadata=metadata,
            )
            success = bool(result.get("success"))
            response_content = (
                result.get("content")
                if success
                else (result.get("error") or "A2A invocation failed")
            ) or ""

            agent_metadata = {
                **metadata,
                "success": success,
                "error_code": result.get("error_code"),
            }
            agent_message = await agent_message_handler.create_agent_message(
                db,
                user_id=task.user_id,
                content=response_content,
                sender="agent",
                session_id=session.id,
                session=session,
                metadata=agent_metadata,
            )
            execution.agent_message_id = agent_message.id
            execution.response_content = response_content
            execution.finished_at = utc_now()
            execution.status = (
                A2AScheduleExecution.STATUS_SUCCESS
                if success
                else A2AScheduleExecution.STATUS_FAILED
            )
            execution.error_message = (
                None if success else (response_content[:2000] or None)
            )

            task.last_run_at = execution.finished_at
            task.last_run_status = (
                A2AScheduleTask.STATUS_SUCCESS
                if success
                else A2AScheduleTask.STATUS_FAILED
            )
            session.touch()

            await commit_safely(db)

        except Exception as exc:  # pragma: no cover - defensive path
            task.last_run_at = utc_now()
            task.last_run_status = A2AScheduleTask.STATUS_FAILED
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
    if not settings.a2a_enabled:
        return

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
