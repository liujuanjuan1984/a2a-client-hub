"""
Background job to persist habit expiration status.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from sqlalchemy import select

from app.core.logging import get_logger
from app.db.models.habit import Habit
from app.db.session import AsyncSessionLocal
from app.handlers.habits import refresh_habit_expiration
from app.services.scheduler import get_scheduler
from app.utils.timezone_util import utc_now

logger = get_logger(__name__)

_HABIT_EXPIRATION_JOB_ID = "habit-expiration-hourly"


async def _list_active_habit_user_ids() -> list[UUID]:
    async with AsyncSessionLocal() as db:
        stmt = (
            select(Habit.user_id)
            .where(Habit.deleted_at.is_(None), Habit.status == "active")
            .distinct()
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())


async def refresh_expired_habits() -> None:
    user_ids = await _list_active_habit_user_ids()
    if not user_ids:
        logger.info("Habit expiration refresh skipped: no active habits found.")
        return

    total_updated = 0
    async with AsyncSessionLocal() as db:
        for user_id in user_ids:
            total_updated += await refresh_habit_expiration(db, user_id=user_id)

    logger.info(
        "Habit expiration refresh completed: %d habits updated for %d users.",
        total_updated,
        len(user_ids),
    )


def ensure_habit_expiration_job() -> None:
    scheduler = get_scheduler()
    if scheduler.get_job(_HABIT_EXPIRATION_JOB_ID):
        return

    scheduler.add_job(
        refresh_expired_habits,
        trigger=CronTrigger(minute=5),
        id=_HABIT_EXPIRATION_JOB_ID,
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )
    logger.info("Registered hourly habit expiration refresh job.")

    scheduler.add_job(
        refresh_expired_habits,
        trigger=DateTrigger(run_date=utc_now() + timedelta(seconds=30)),
        id=f"{_HABIT_EXPIRATION_JOB_ID}-initial",
        replace_existing=True,
        misfire_grace_time=60,
        coalesce=True,
        max_instances=1,
    )
    logger.info("Scheduled warm-up habit expiration refresh run.")
