"""Durable follow-up dispatcher for the built-in self-management agent."""

from __future__ import annotations

from datetime import timedelta

from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models.user import User
from app.db.session import AsyncSessionLocal
from app.db.transaction import commit_safely, run_with_new_session
from app.features.self_management_agent.service import (
    SelfManagementBuiltInAgentRunStatus,
    self_management_built_in_agent_service,
)
from app.features.self_management_shared.follow_up_service import (
    BuiltInFollowUpWakeRequest,
    built_in_follow_up_service,
)
from app.runtime.scheduler import get_scheduler
from app.utils.timezone_util import utc_now

logger = get_logger(__name__)

_SELF_MANAGEMENT_FOLLOW_UP_JOB_ID = "self-management-follow-up-dispatch"


async def _execute_follow_up_request(request: BuiltInFollowUpWakeRequest) -> None:
    extra = {
        "task_id": str(request.task_id),
        "user_id": str(request.user_id),
        "built_in_conversation_id": request.built_in_conversation_id,
        "tracked_conversation_ids": list(request.tracked_conversation_ids),
        "changed_conversation_ids": list(request.changed_conversation_ids),
    }
    try:
        async with AsyncSessionLocal() as db:
            user = await db.get(User, request.user_id)
            if user is None:
                await built_in_follow_up_service.fail_follow_up_run(
                    db=db,
                    task_id=request.task_id,
                    error="user_not_found",
                )
                return
            result = await self_management_built_in_agent_service.run_durable_follow_up(
                db=db,
                current_user=user,
                request=request,
            )
            await commit_safely(db)

        if result.status == SelfManagementBuiltInAgentRunStatus.INTERRUPTED:
            async with AsyncSessionLocal() as db:
                await built_in_follow_up_service.fail_follow_up_run(
                    db=db,
                    task_id=request.task_id,
                    error="follow_up_requires_write_approval",
                )
            return

        async with AsyncSessionLocal() as db:
            await built_in_follow_up_service.complete_follow_up_run(
                db=db,
                task_id=request.task_id,
                next_target_agent_message_anchors=(
                    request.observed_target_agent_message_anchors
                ),
            )
    except Exception as exc:
        logger.exception(
            "Built-in durable follow-up execution failed",
            extra=extra,
        )
        try:
            async with AsyncSessionLocal() as db:
                await built_in_follow_up_service.fail_follow_up_run(
                    db=db,
                    task_id=request.task_id,
                    error=str(exc),
                )
        except Exception:
            logger.exception(
                "Built-in durable follow-up failure could not be persisted",
                extra=extra,
            )


async def dispatch_due_self_management_follow_ups(
    *, batch_size: int | None = None
) -> None:
    effective_batch_size = (
        max(int(batch_size), 1)
        if batch_size is not None
        else settings.self_management_follow_up_batch_size
    )
    recovered = await run_with_new_session(
        lambda db: built_in_follow_up_service.recover_stale_running_tasks(
            db=db,
            timeout_seconds=settings.self_management_follow_up_running_timeout_seconds,
        ),
        session_factory=AsyncSessionLocal,
    )
    if recovered:
        logger.warning(
            "Recovered %d stale built-in durable follow-up task(s).",
            recovered,
        )

    requests = await run_with_new_session(
        lambda db: built_in_follow_up_service.claim_due_follow_up_tasks(
            db=db,
            batch_size=effective_batch_size,
        ),
        session_factory=AsyncSessionLocal,
    )
    if not requests:
        return

    logger.info(
        "Dispatching %d durable built-in follow-up task(s).",
        len(requests),
    )
    for request in requests:
        await _execute_follow_up_request(request)


def ensure_self_management_follow_up_job() -> None:
    scheduler = get_scheduler()
    if scheduler.get_job(_SELF_MANAGEMENT_FOLLOW_UP_JOB_ID):
        return

    interval_seconds = max(
        int(settings.self_management_follow_up_poll_interval_seconds),
        1,
    )
    scheduler.add_job(
        dispatch_due_self_management_follow_ups,
        trigger=IntervalTrigger(seconds=interval_seconds),
        id=_SELF_MANAGEMENT_FOLLOW_UP_JOB_ID,
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=max(interval_seconds * 2, 30),
        coalesce=True,
    )
    scheduler.add_job(
        dispatch_due_self_management_follow_ups,
        trigger=DateTrigger(run_date=utc_now() + timedelta(seconds=5)),
        id=f"{_SELF_MANAGEMENT_FOLLOW_UP_JOB_ID}-initial",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=30,
        coalesce=True,
    )
    logger.info("Registered durable built-in follow-up dispatcher job.")
