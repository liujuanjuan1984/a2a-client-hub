"""
Async helpers for habit handlers.

Routers should rely on these implementations to avoid ``run_with_session``.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple, Union
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.constants import (
    DEFAULT_HABIT_ACTION_WINDOW_DAYS,
    HABIT_ACTION_STATUS_CONFIG,
    HABIT_ALLOWED_STATUSES,
    HABIT_DURATION_OPTIONS,
    HABIT_EDITABLE_DAYS,
    MAX_ACTIVE_HABITS,
    MAX_HABIT_ACTION_WINDOW_DAYS,
    get_default_habit_action_status,
    get_habit_action_allowed_statuses,
)
from app.db.models.habit import Habit
from app.db.models.habit_action import HabitAction
from app.db.transaction import commit_safely
from app.handlers.user_preferences import get_user_timezone
from app.schemas.habit import HabitActionUpdate, HabitCreate, HabitUpdate
from app.utils.timezone_util import resolve_timezone, utc_now


class HabitNotFoundError(Exception):
    """Raised when a habit is not found."""


class HabitActionNotFoundError(Exception):
    """Raised when a habit action is not found."""


class InvalidOperationError(Exception):
    """Raised when an invalid operation is attempted."""


class ValidationError(Exception):
    """Raised when validation fails."""


async def _get_local_today(db: AsyncSession, *, user_id: UUID) -> date:
    timezone_name = await get_user_timezone(db, user_id=user_id, default="UTC")
    tzinfo = resolve_timezone(str(timezone_name), default="UTC")
    return datetime.now(tzinfo).date()


async def refresh_habit_expiration(
    db: AsyncSession,
    *,
    user_id: UUID,
    habit_id: Optional[UUID] = None,
) -> int:
    if db.new or db.dirty or db.deleted:
        return 0
    local_today = await _get_local_today(db, user_id=user_id)
    end_expr = Habit.start_date + (Habit.duration_days - 1) * text("INTERVAL '1 day'")
    filters = [
        Habit.user_id == user_id,
        Habit.deleted_at.is_(None),
        Habit.status == "active",
        end_expr < local_today,
    ]
    if habit_id is not None:
        filters.append(Habit.id == habit_id)

    stmt = update(Habit).where(*filters).values(status="expired", updated_at=func.now())
    result = await db.execute(stmt)
    updated = result.rowcount or 0
    if updated:
        await commit_safely(db)
    return updated


async def list_habits(
    db: AsyncSession,
    *,
    user_id: UUID,
    skip: int = 0,
    limit: int = 100,
    status_filter: Optional[str] = None,
    title: Optional[str] = None,
    active_window_only: bool = False,
) -> Tuple[List[Habit], int]:
    """Async implementation of ``habits.list_habits``."""

    filters = [
        Habit.user_id == user_id,
        Habit.deleted_at.is_(None),
        Habit.status != "deleted",
    ]

    if status_filter:
        if status_filter not in HABIT_ALLOWED_STATUSES:
            raise ValidationError(
                f"Invalid status filter. Allowed values: {HABIT_ALLOWED_STATUSES}"
            )
        filters.append(Habit.status == status_filter)

    if title:
        normalized = title.strip()
        if normalized:
            filters.append(Habit.title == normalized)

    if active_window_only:
        local_today = await _get_local_today(db, user_id=user_id)
        end_expr = Habit.start_date + (Habit.duration_days - 1) * text(
            "INTERVAL '1 day'"
        )
        filters.extend(
            [
                Habit.start_date.isnot(None),
                Habit.duration_days.isnot(None),
                Habit.start_date <= local_today,
                end_expr >= local_today,
            ]
        )

    total_stmt = select(func.count()).where(*filters)
    total = (await db.execute(total_stmt)).scalar_one()

    query = (
        select(Habit)
        .where(*filters)
        .options(selectinload(Habit.task))
        .order_by(Habit.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    habits = (await db.execute(query)).scalars().all()
    return habits, total


async def list_habit_overviews(
    db: AsyncSession,
    *,
    user_id: UUID,
    skip: int = 0,
    limit: int = 100,
    status_filter: Optional[str] = None,
    title: Optional[str] = None,
    active_window_only: bool = False,
) -> Tuple[List[Dict[str, Union[Habit, Dict[str, Union[int, float]]]]], int]:
    """Return habits with statistics using AsyncSession."""

    habits, total = await list_habits(
        db,
        user_id=user_id,
        skip=skip,
        limit=limit,
        status_filter=status_filter,
        title=title,
        active_window_only=active_window_only,
    )
    if not habits:
        return [], total

    habit_ids = [habit.id for habit in habits]
    actions_stmt = (
        select(HabitAction)
        .where(
            HabitAction.user_id == user_id,
            HabitAction.habit_id.in_(habit_ids),
            HabitAction.deleted_at.is_(None),
        )
        .order_by(HabitAction.action_date)
    )
    actions = (await db.execute(actions_stmt)).scalars().all()
    actions_map: Dict[UUID, List[HabitAction]] = {
        habit_id: [] for habit_id in habit_ids
    }
    for action in actions:
        actions_map.setdefault(action.habit_id, []).append(action)

    overviews = []
    for habit in habits:
        stats = _build_habit_stats_payload(habit, actions_map.get(habit.id, []))
        overviews.append({"habit": habit, "stats": stats})

    return overviews, total


async def get_habit(
    db: AsyncSession, *, user_id: UUID, habit_id: UUID
) -> Optional[Habit]:
    """Fetch a habit including soft-deleted records."""

    stmt = (
        select(Habit)
        .where(Habit.user_id == user_id, Habit.id == habit_id)
        .options(selectinload(Habit.task))
        .limit(1)
    )
    return (await db.execute(stmt)).scalars().first()


async def get_habit_overview(
    db: AsyncSession, *, user_id: UUID, habit_id: UUID
) -> Dict[str, Union[Habit, Dict[str, Union[int, float]]]]:
    habit = await get_habit(db, user_id=user_id, habit_id=habit_id)
    if habit is None:
        raise HabitNotFoundError("Habit not found")

    actions_stmt = (
        select(HabitAction)
        .where(
            HabitAction.user_id == user_id,
            HabitAction.habit_id == habit_id,
            HabitAction.deleted_at.is_(None),
        )
        .order_by(HabitAction.action_date)
    )
    actions = (await db.execute(actions_stmt)).scalars().all()
    stats = _build_habit_stats_payload(habit, actions)
    return {"habit": habit, "stats": stats}


async def _ensure_active_capacity(
    db: AsyncSession,
    *,
    user_id: UUID,
    exclude_habit_id: Optional[UUID] = None,
) -> None:
    """Ensure the user has not exceeded the active habit limit."""

    local_today = await _get_local_today(db, user_id=user_id)
    end_expr = Habit.start_date + (Habit.duration_days - 1) * text("INTERVAL '1 day'")
    filters = [
        Habit.user_id == user_id,
        Habit.status == "active",
        Habit.deleted_at.is_(None),
        end_expr >= local_today,
    ]
    if exclude_habit_id is not None:
        filters.append(Habit.id != exclude_habit_id)

    stmt = select(func.count()).where(*filters)
    active_count = (await db.execute(stmt)).scalar_one()
    if active_count >= MAX_ACTIVE_HABITS:
        raise InvalidOperationError(
            f"You already have {MAX_ACTIVE_HABITS} active habits. "
            "Pause or complete one before activating a new habit."
        )


async def create_habit(
    db: AsyncSession, *, user_id: UUID, habit_in: HabitCreate
) -> Habit:
    """Create a new habit."""

    await _ensure_active_capacity(db, user_id=user_id)
    if habit_in.duration_days not in HABIT_DURATION_OPTIONS:
        raise ValidationError(
            f"Invalid duration_days. Allowed values: {HABIT_DURATION_OPTIONS}"
        )

    today = date.today()
    if habit_in.start_date < today - timedelta(days=HABIT_EDITABLE_DAYS):
        raise ValidationError(
            f"Start date cannot be more than {HABIT_EDITABLE_DAYS} days in the past"
        )

    habit = Habit(
        title=habit_in.title,
        description=habit_in.description,
        start_date=habit_in.start_date,
        duration_days=habit_in.duration_days,
        status="active",
        task_id=habit_in.task_id,
        user_id=user_id,
    )
    db.add(habit)
    await commit_safely(db)
    await db.refresh(habit)

    updated = await refresh_habit_expiration(db, user_id=user_id, habit_id=habit.id)
    if updated:
        await db.refresh(habit)

    await _generate_habit_actions(db, habit)
    return habit


async def update_habit(
    db: AsyncSession, *, user_id: UUID, habit_id: UUID, habit_update: HabitUpdate
) -> Optional[Habit]:
    """Update a habit."""

    habit = await get_habit(db, user_id=user_id, habit_id=habit_id)
    if not habit:
        return None

    if habit_update.title is not None:
        habit.title = habit_update.title

    if habit_update.description is not None:
        habit.description = habit_update.description

    if "task_id" in habit_update.model_fields_set:
        habit.task_id = habit_update.task_id

    start_date_changed = False
    duration_changed = False
    old_start_date = habit.start_date
    old_duration = habit.duration_days

    if habit_update.start_date is not None:
        habit.start_date = habit_update.start_date
        start_date_changed = old_start_date != habit_update.start_date

    if habit_update.duration_days is not None:
        if habit_update.duration_days not in HABIT_DURATION_OPTIONS:
            raise ValidationError(
                f"Invalid duration. Allowed values: {HABIT_DURATION_OPTIONS}"
            )

        habit.duration_days = habit_update.duration_days
        duration_changed = old_duration != habit_update.duration_days

    if start_date_changed and duration_changed:
        await _adjust_actions_for_both_changes(db, habit, old_start_date, old_duration)
    elif start_date_changed:
        await _adjust_actions_for_start_change(db, habit, old_start_date)
    elif duration_changed:
        await _adjust_actions_for_duration_change(db, habit, old_duration)

    if habit_update.status is not None:
        if habit_update.status == "active" and habit.status != "active":
            await _ensure_active_capacity(
                db, user_id=user_id, exclude_habit_id=habit.id
            )
        if habit_update.status not in HABIT_ALLOWED_STATUSES:
            raise ValidationError(
                f"Invalid status. Allowed values: {HABIT_ALLOWED_STATUSES}"
            )
        habit.status = habit_update.status

    await commit_safely(db)
    await db.refresh(habit)

    updated = await refresh_habit_expiration(db, user_id=user_id, habit_id=habit.id)
    if updated:
        await db.refresh(habit)
    return habit


async def delete_habit(
    db: AsyncSession,
    *,
    user_id: UUID,
    habit_id: UUID,
    hard_delete: bool = False,
) -> bool:
    """Delete or soft-delete a habit."""

    habit = await get_habit(db, user_id=user_id, habit_id=habit_id)
    if not habit:
        return False

    if hard_delete:
        await db.delete(habit)
    else:
        habit.soft_delete()

    await commit_safely(db)
    return True


async def get_habit_actions(
    db: AsyncSession,
    *,
    user_id: UUID,
    habit_id: UUID,
    skip: int = 0,
    limit: int = 100,
    status_filter: Optional[str] = None,
    center_date: Optional[date] = None,
    days_before: Optional[int] = None,
    days_after: Optional[int] = None,
) -> Tuple[List[HabitAction], int]:
    """Return actions for a habit."""

    habit = await get_habit(db, user_id=user_id, habit_id=habit_id)
    if not habit:
        raise HabitNotFoundError("Habit not found")

    filters = [
        HabitAction.user_id == user_id,
        HabitAction.habit_id == habit_id,
        HabitAction.deleted_at.is_(None),
    ]
    if status_filter:
        filters.append(HabitAction.status == status_filter)

    use_window = any(
        value is not None for value in (center_date, days_before, days_after)
    )
    if use_window:
        reference_date = center_date or date.today()
        window_before = (
            days_before if days_before is not None else DEFAULT_HABIT_ACTION_WINDOW_DAYS
        )
        window_after = days_after if days_after is not None else window_before

        if window_before < 0 or window_after < 0:
            raise ValidationError("days_before/days_after must be non-negative")

        total_window = window_before + window_after + 1
        if total_window > MAX_HABIT_ACTION_WINDOW_DAYS:
            raise ValidationError(
                f"Window too large. Maximum combined window size is {MAX_HABIT_ACTION_WINDOW_DAYS} days"
            )

        start = reference_date - timedelta(days=window_before)
        end = reference_date + timedelta(days=window_after)
        filters.extend(
            [
                HabitAction.action_date >= start,
                HabitAction.action_date <= end,
            ]
        )

    total_stmt = select(func.count()).where(*filters)
    total = (await db.execute(total_stmt)).scalar_one()

    query = (
        select(HabitAction)
        .where(*filters)
        .order_by(HabitAction.action_date)
        .offset(skip)
        .limit(limit)
    )
    actions = (await db.execute(query)).scalars().all()
    return actions, total


async def update_habit_action(
    db: AsyncSession,
    *,
    user_id: UUID,
    habit_id: UUID,
    action_id: UUID,
    action_update: HabitActionUpdate,
) -> HabitAction:
    """Update a habit action."""

    habit = await get_habit(db, user_id=user_id, habit_id=habit_id)
    if not habit:
        raise HabitNotFoundError("Habit not found")

    stmt = (
        select(HabitAction)
        .where(
            HabitAction.user_id == user_id,
            HabitAction.id == action_id,
            HabitAction.habit_id == habit_id,
            HabitAction.deleted_at.is_(None),
        )
        .limit(1)
    )
    action = (await db.execute(stmt)).scalars().first()
    if not action:
        raise HabitActionNotFoundError("Action not found")

    today = date.today()
    if action.action_date > today:
        raise InvalidOperationError(
            "Action cannot be modified outside the allowed time window"
        )

    days_since_action = (today - action.action_date).days
    if days_since_action > HABIT_EDITABLE_DAYS:
        raise InvalidOperationError(
            "Action cannot be modified outside the allowed time window"
        )

    if action_update.status is not None:
        allowed_statuses = get_habit_action_allowed_statuses()
        if action_update.status not in allowed_statuses:
            raise ValidationError(f"Invalid status. Allowed values: {allowed_statuses}")
        action.status = action_update.status

    if action_update.notes is not None:
        action.notes = action_update.notes

    await commit_safely(db)
    await db.refresh(action)
    return action


async def get_habit_stats(
    db: AsyncSession, *, user_id: UUID, habit_id: UUID
) -> Dict[str, Union[int, float]]:
    """Fetch statistics for a habit."""

    habit = await get_habit(db, user_id=user_id, habit_id=habit_id)
    if not habit:
        raise HabitNotFoundError("Habit not found")

    stmt = (
        select(HabitAction)
        .where(
            HabitAction.user_id == user_id,
            HabitAction.habit_id == habit_id,
            HabitAction.deleted_at.is_(None),
        )
        .order_by(HabitAction.action_date)
    )
    actions = (await db.execute(stmt)).scalars().all()
    return _build_habit_stats_payload(habit, actions)


async def get_habit_actions_by_date(
    db: AsyncSession, *, user_id: UUID, action_date: date
) -> List[HabitAction]:
    """Return habit actions for a specific date."""

    stmt = (
        select(HabitAction)
        .options(selectinload(HabitAction.habit))
        .join(Habit, Habit.id == HabitAction.habit_id)
        .where(
            HabitAction.user_id == user_id,
            HabitAction.action_date == action_date,
            HabitAction.deleted_at.is_(None),
            Habit.deleted_at.is_(None),
            Habit.status != "deleted",
            Habit.user_id == user_id,
        )
    )
    return (await db.execute(stmt)).scalars().all()


async def get_habit_task_associations(
    db: AsyncSession, *, user_id: UUID
) -> Dict[UUID, List[Habit]]:
    """Return mapping task_id -> habits for active habits."""

    stmt = (
        select(Habit)
        .where(
            Habit.user_id == user_id,
            Habit.deleted_at.is_(None),
            Habit.task_id.isnot(None),
        )
        .options(selectinload(Habit.task))
        .order_by(Habit.created_at.desc())
    )
    habits = (await db.execute(stmt)).scalars().all()
    associations: Dict[UUID, List[Habit]] = {}
    for habit in habits:
        if habit.task_id is None:
            continue
        associations.setdefault(habit.task_id, []).append(habit)
    return associations


async def _generate_habit_actions(db: AsyncSession, habit: Habit) -> None:
    """Generate action rows for a habit."""

    current_date = habit.start_date
    end_date = habit.end_date

    while current_date <= end_date:
        action = HabitAction(
            habit_id=habit.id,
            user_id=habit.user_id,
            action_date=current_date,
            status=get_default_habit_action_status(),
        )
        db.add(action)
        current_date += timedelta(days=1)

    await commit_safely(db)


async def _adjust_actions_for_duration_change(
    db: AsyncSession, habit: Habit, old_duration: int
) -> None:
    """Adjust actions when duration changes."""

    new_end_date = habit.end_date
    old_end_date = habit.start_date + timedelta(days=old_duration - 1)

    if habit.duration_days > old_duration:
        start_date_for_new_actions = old_end_date + timedelta(days=1)
        current_date = start_date_for_new_actions
        while current_date <= new_end_date:
            stmt = (
                select(HabitAction.id)
                .where(
                    HabitAction.user_id == habit.user_id,
                    HabitAction.habit_id == habit.id,
                    HabitAction.action_date == current_date,
                    HabitAction.deleted_at.is_(None),
                )
                .limit(1)
            )
            exists = (await db.execute(stmt)).scalar_one_or_none()
            if not exists:
                db.add(
                    HabitAction(
                        habit_id=habit.id,
                        user_id=habit.user_id,
                        action_date=current_date,
                        status=get_default_habit_action_status(),
                    )
                )
            current_date += timedelta(days=1)
    else:
        cutoff_date = habit.start_date + timedelta(days=habit.duration_days - 1)
        stmt = select(HabitAction).where(
            HabitAction.user_id == habit.user_id,
            HabitAction.habit_id == habit.id,
            HabitAction.action_date > cutoff_date,
            HabitAction.deleted_at.is_(None),
        )
        actions = (await db.execute(stmt)).scalars().all()
        for action in actions:
            action.deleted_at = utc_now()

    await commit_safely(db)


async def _load_habit_actions(db: AsyncSession, habit: Habit) -> List[HabitAction]:
    stmt = select(HabitAction).where(
        HabitAction.user_id == habit.user_id,
        HabitAction.habit_id == habit.id,
        HabitAction.deleted_at.is_(None),
    )
    return (await db.execute(stmt)).scalars().all()


async def _adjust_actions_for_start_change(
    db: AsyncSession, habit: Habit, old_start_date: date
) -> None:
    """Adjust actions when start date changes."""

    _ = old_start_date  # preserved for parity with sync helper
    desired_dates = set()
    current_date = habit.start_date
    while current_date <= habit.end_date:
        desired_dates.add(current_date)
        current_date += timedelta(days=1)

    existing_actions = await _load_habit_actions(db, habit)
    existing_by_date = {action.action_date: action for action in existing_actions}

    for action in existing_actions:
        if action.action_date not in desired_dates:
            action.deleted_at = utc_now()

    for desired_date in sorted(desired_dates):
        if desired_date not in existing_by_date:
            db.add(
                HabitAction(
                    habit_id=habit.id,
                    user_id=habit.user_id,
                    action_date=desired_date,
                    status=get_default_habit_action_status(),
                )
            )

    await commit_safely(db)


async def _adjust_actions_for_both_changes(
    db: AsyncSession, habit: Habit, old_start_date: date, old_duration: int
) -> None:
    """Adjust actions when both start date and duration change."""

    _ = (old_start_date, old_duration)
    desired_dates = set()
    current_date = habit.start_date
    while current_date <= habit.end_date:
        desired_dates.add(current_date)
        current_date += timedelta(days=1)

    existing_actions = await _load_habit_actions(db, habit)
    existing_by_date = {action.action_date: action for action in existing_actions}

    for action in existing_actions:
        if action.action_date not in desired_dates:
            action.deleted_at = utc_now()

    for desired_date in sorted(desired_dates):
        if desired_date not in existing_by_date:
            db.add(
                HabitAction(
                    habit_id=habit.id,
                    user_id=habit.user_id,
                    action_date=desired_date,
                    status=get_default_habit_action_status(),
                )
            )

    await commit_safely(db)


def _build_habit_stats_payload(
    habit: Habit, actions: List[HabitAction]
) -> Dict[str, Union[int, float, UUID]]:
    """Build stats dictionary shared across overview and stats endpoints."""

    total_actions = len(actions)
    completed_actions = len(
        [
            action
            for action in actions
            if HABIT_ACTION_STATUS_CONFIG.get(action.status, {}).get(
                "count_as_completed", False
            )
        ]
    )
    missed_actions = len([action for action in actions if action.status == "miss"])
    skipped_actions = len([action for action in actions if action.status == "skip"])

    current_streak = _calculate_current_streak(actions)
    longest_streak = _calculate_longest_streak(actions)

    progress_percentage = (
        (completed_actions / total_actions) * 100 if total_actions else 0.0
    )

    return {
        "habit_id": habit.id,
        "total_actions": total_actions,
        "completed_actions": completed_actions,
        "missed_actions": missed_actions,
        "skipped_actions": skipped_actions,
        "progress_percentage": progress_percentage,
        "current_streak": current_streak,
        "longest_streak": longest_streak,
    }


def _calculate_current_streak(actions: List[HabitAction]) -> int:
    """Calculate current streak of completed actions."""

    streak = 0
    today = date.today()
    sorted_actions = sorted(
        actions, key=lambda action: action.action_date, reverse=True
    )

    for action in sorted_actions:
        if action.action_date > today:
            continue
        if action.status == "done":
            streak += 1
        else:
            break

    return streak


def _calculate_longest_streak(actions: List[HabitAction]) -> int:
    """Calculate longest streak of completed actions."""

    max_streak = 0
    current_streak = 0
    sorted_actions = sorted(actions, key=lambda action: action.action_date)

    for action in sorted_actions:
        if action.status == "done":
            current_streak += 1
            max_streak = max(max_streak, current_streak)
        else:
            current_streak = 0

    return max_streak


__all__ = [
    "HabitActionNotFoundError",
    "HabitNotFoundError",
    "create_habit",
    "delete_habit",
    "get_habit",
    "get_habit_actions",
    "get_habit_actions_by_date",
    "get_habit_overview",
    "get_habit_stats",
    "get_habit_task_associations",
    "refresh_habit_expiration",
    "list_habit_overviews",
    "list_habits",
    "update_habit",
    "update_habit_action",
    "InvalidOperationError",
    "ValidationError",
]
