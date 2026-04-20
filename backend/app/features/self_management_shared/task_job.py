"""Durable task dispatcher for the built-in self-management agent."""

from __future__ import annotations

from datetime import timedelta
from typing import cast

from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models.self_management_agent_task import SelfManagementAgentTask
from app.db.models.user import User
from app.db.session import AsyncSessionLocal
from app.db.transaction import run_with_new_session
from app.features.self_management_agent.service import (
    SelfManagementBuiltInAgentRunStatus,
    self_management_built_in_agent_service,
)
from app.features.self_management_shared import delegated_conversation_service
from app.features.self_management_shared.task_service import (
    DelegatedInvokeTaskRequest,
    PermissionReplyContinuationTaskRequest,
    SelfManagementAgentTaskWorkItem,
    SelfManagementFollowUpTaskCompletion,
    SelfManagementFollowUpTaskRequest,
    self_management_agent_task_service,
)
from app.runtime.scheduler import get_scheduler
from app.utils.timezone_util import utc_now

logger = get_logger(__name__)

_SELF_MANAGEMENT_AGENT_TASK_JOB_ID = "self-management-agent-task"
_SELF_MANAGEMENT_AGENT_TASK_REQUEST_JOB_ID = "self-management-agent-task-requested"


async def _execute_self_management_agent_task(
    task: SelfManagementAgentTaskWorkItem,
) -> None:
    extra = {
        "task_id": str(task.task_id),
        "user_id": str(task.user_id),
        "task_kind": task.task_kind,
        "built_in_conversation_id": task.built_in_conversation_id,
    }
    try:
        async with AsyncSessionLocal() as db:
            user = await db.get(User, task.user_id)
            if user is None:
                await self_management_agent_task_service.fail_task(
                    db=db,
                    task_id=task.task_id,
                    error="user_not_found",
                )
                return

            if task.task_kind == SelfManagementAgentTask.KIND_FOLLOW_UP_WATCH:
                request = cast(SelfManagementFollowUpTaskRequest, task.request)
                result = (
                    await self_management_built_in_agent_service.run_durable_follow_up(
                        db=db,
                        current_user=user,
                        request=request,
                    )
                )
                if result.status == SelfManagementBuiltInAgentRunStatus.INTERRUPTED:
                    await self_management_agent_task_service.fail_task(
                        db=db,
                        task_id=task.task_id,
                        error="follow_up_requires_write_approval",
                    )
                    return
                await self_management_agent_task_service.complete_task(
                    db=db,
                    task_id=task.task_id,
                    follow_up_completion=SelfManagementFollowUpTaskCompletion(
                        next_target_agent_message_anchors=(
                            request.observed_target_agent_message_anchors
                        )
                    ),
                )
                return

            if (
                task.task_kind
                == SelfManagementAgentTask.KIND_PERMISSION_REPLY_CONTINUATION
            ):
                await self_management_built_in_agent_service.run_permission_reply_continuation(
                    db=db,
                    current_user=user,
                    request=cast(PermissionReplyContinuationTaskRequest, task.request),
                )
            elif task.task_kind == SelfManagementAgentTask.KIND_DELEGATED_INVOKE:
                await delegated_conversation_service.self_management_delegated_conversation_service.run_delegated_dispatch_request(
                    db=db,
                    current_user=user,
                    request=cast(DelegatedInvokeTaskRequest, task.request),
                )
            else:  # pragma: no cover - defensive guard
                raise ValueError(
                    f"Unsupported self-management task kind: {task.task_kind}"
                )

            await self_management_agent_task_service.complete_task(
                db=db,
                task_id=task.task_id,
            )
    except Exception as exc:
        logger.exception(
            "Built-in self-management durable task execution failed",
            extra=extra,
        )
        try:
            async with AsyncSessionLocal() as db:
                await self_management_agent_task_service.fail_task(
                    db=db,
                    task_id=task.task_id,
                    error=str(exc),
                )
        except Exception:
            logger.exception(
                "Built-in self-management durable task failure could not be persisted",
                extra=extra,
            )


async def dispatch_due_self_management_agent_tasks(
    *, batch_size: int | None = None
) -> None:
    effective_batch_size = (
        max(int(batch_size), 1)
        if batch_size is not None
        else settings.self_management_agent_task_batch_size
    )
    recovered = await run_with_new_session(
        lambda db: self_management_agent_task_service.recover_stale_running_tasks(
            db=db,
            timeout_seconds=settings.self_management_agent_task_running_timeout_seconds,
        ),
        session_factory=AsyncSessionLocal,
    )
    if recovered:
        logger.warning(
            "Recovered %d stale built-in self-management task(s).",
            recovered,
        )

    tasks = await run_with_new_session(
        lambda db: self_management_agent_task_service.claim_due_tasks(
            db=db,
            batch_size=effective_batch_size,
        ),
        session_factory=AsyncSessionLocal,
    )
    if not tasks:
        return

    logger.info("Dispatching %d built-in self-management task(s).", len(tasks))
    for task in tasks:
        await _execute_self_management_agent_task(task)


def request_self_management_agent_task_run(*, delay_seconds: int = 1) -> None:
    """Request a near-future task scan when the scheduler is live."""

    try:
        scheduler = get_scheduler()
    except RuntimeError:
        return

    scheduler.add_job(
        dispatch_due_self_management_agent_tasks,
        trigger=DateTrigger(
            run_date=utc_now() + timedelta(seconds=max(int(delay_seconds), 0))
        ),
        id=_SELF_MANAGEMENT_AGENT_TASK_REQUEST_JOB_ID,
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=max(delay_seconds * 2, 30),
        coalesce=True,
    )


def ensure_self_management_agent_task_job() -> None:
    scheduler = get_scheduler()
    if scheduler.get_job(_SELF_MANAGEMENT_AGENT_TASK_JOB_ID):
        return

    interval_seconds = max(
        int(settings.self_management_agent_task_poll_interval_seconds),
        1,
    )
    scheduler.add_job(
        dispatch_due_self_management_agent_tasks,
        trigger=IntervalTrigger(seconds=interval_seconds),
        id=_SELF_MANAGEMENT_AGENT_TASK_JOB_ID,
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=max(interval_seconds * 2, 30),
        coalesce=True,
    )
    scheduler.add_job(
        dispatch_due_self_management_agent_tasks,
        trigger=DateTrigger(run_date=utc_now() + timedelta(seconds=5)),
        id=f"{_SELF_MANAGEMENT_AGENT_TASK_JOB_ID}-initial",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=30,
        coalesce=True,
    )
    logger.info("Registered built-in self-management durable task job.")
