"""
Async task handlers (canonical implementation).

Provides the authoritative task operations backed by ``AsyncSession``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
from uuid import UUID

from sqlalchemy import func, not_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Load, selectinload

from app.core.constants import (
    MAX_TASK_DEPTH,
    PLANNING_CYCLE_TYPES,
    TASK_ALLOWED_STATUSES,
)
from app.db.models.actual_event import ActualEvent
from app.db.models.association import Association
from app.db.models.person import Person
from app.db.models.task import Task
from app.db.models.user_preference import UserPreference
from app.db.models.vision import Vision
from app.db.transaction import commit_safely
from app.handlers.associations import LinkType, ModelName
from app.handlers.associations_async import (
    attach_persons_for_sources,
    load_persons_for_sources,
    set_links,
)
from app.handlers.metrics.effort_async import (
    recompute_subtree_totals,
    recompute_totals_upwards,
)
from app.schemas.actual_event import ActualEventResponse
from app.schemas.task import (
    TaskCreate,
    TaskHierarchy,
    TaskMoveRequest,
    TaskReorderRequest,
    TaskStatsResponse,
    TaskStatusUpdate,
    TaskUpdate,
    TaskWithSubtasks,
)
from app.serialization.entities import (
    build_task_summary,
    normalize_task_summary,
    serialize_dimension_summary,
)
from app.services.work_recalc import schedule_recalc_jobs
from app.utils.person_utils import convert_persons_to_summary


class TaskNotFoundError(Exception):
    """Raised when a task is not found."""


class VisionNotFoundError(Exception):
    """Raised when a vision is not found."""


class ParentTaskNotFoundError(Exception):
    """Raised when a parent task is not found."""


class InvalidTaskDepthError(Exception):
    """Raised when task hierarchy depth exceeds maximum allowed."""


class CircularReferenceError(Exception):
    """Raised when a task operation would create a circular reference."""


class InvalidPlanningCycleError(Exception):
    """Raised when planning cycle data is invalid."""


class InvalidStatusError(Exception):
    """Raised when task status is invalid."""


class TaskCannotBeCompletedError(Exception):
    """Raised when a task cannot be completed due to incomplete subtasks."""


class InvalidOperationError(Exception):
    """Raised when an invalid operation is attempted."""


@dataclass
class TaskMoveResult:
    """Result payload containing the moved task and any updated descendants."""

    task: Task
    updated_descendants: List[Task]


def _get_cycle_date_range(
    cycle_type: str, start_date: date, calendar_system: str
) -> Tuple[date, date]:
    """Return [start, end] tuple for the requested planning cycle."""

    if cycle_type == "day":
        return start_date, start_date

    if cycle_type == "week":
        if calendar_system == "gregorian":
            days_since_monday = start_date.weekday()
            week_start = start_date - timedelta(days=days_since_monday)
            week_end = week_start + timedelta(days=6)
            return week_start, week_end
        week_end = start_date + timedelta(days=6)
        return start_date, week_end

    if cycle_type == "month":
        if calendar_system == "gregorian":
            month_start = start_date.replace(day=1)
            if start_date.month == 12:
                month_end = start_date.replace(
                    year=start_date.year + 1, month=1, day=1
                ) - timedelta(days=1)
            else:
                month_end = start_date.replace(
                    month=start_date.month + 1, day=1
                ) - timedelta(days=1)
            return month_start, month_end
        month_end = start_date + timedelta(days=27)
        return start_date, month_end

    if cycle_type == "year":
        if calendar_system == "gregorian":
            year_start = start_date.replace(month=1, day=1)
            year_end = start_date.replace(month=12, day=31)
            return year_start, year_end
        year_start = start_date.replace(month=7, day=26)
        if start_date < year_start:
            year_start = year_start.replace(year=year_start.year - 1)
        year_end = year_start.replace(year=year_start.year + 1) - timedelta(days=1)
        return year_start, year_end

    return start_date, start_date


def _build_task_tree(
    tasks: List[Task],
    task_id_to_persons: dict[UUID, List[Person]] | None = None,
    task_notes_count_map: dict[UUID, int] | None = None,
) -> List[TaskWithSubtasks]:
    """Build hierarchical task tree from flat list of tasks."""

    task_dict = {task.id: task for task in tasks}
    root_tasks: List[Task] = []

    for task in tasks:
        setattr(task, "_subtasks", [])

    for task in tasks:
        if task.parent_task_id is None:
            root_tasks.append(task)
            continue
        parent = task_dict.get(task.parent_task_id)
        if parent:
            parent._subtasks.append(task)
        else:
            root_tasks.append(task)

    def completion_ratio(task: Task, subtasks: List[Task]) -> float:
        if not subtasks:
            return 1.0 if task.status == "done" else 0.0
        completed = sum(1 for subtask in subtasks if subtask.status == "done")
        return completed / len(subtasks)

    def convert_to_response(task: Task, depth: int = 0) -> TaskWithSubtasks:
        subtasks = getattr(task, "_subtasks", [])
        persons_for_task = []
        if task_id_to_persons is not None:
            persons_for_task = task_id_to_persons.get(task.id, [])
        notes_count = 0
        if task_notes_count_map is not None:
            notes_count = task_notes_count_map.get(task.id, 0) or 0

        child_responses = [
            convert_to_response(subtask, depth + 1) for subtask in subtasks
        ]

        return TaskWithSubtasks(
            id=task.id,
            vision_id=task.vision_id,
            parent_task_id=task.parent_task_id,
            content=task.content,
            status=task.status,
            priority=task.priority,
            display_order=task.display_order,
            estimated_effort=task.estimated_effort,
            actual_effort=task.actual_effort_total or 0,
            actual_effort_self=task.actual_effort_self or 0,
            actual_effort_total=task.actual_effort_total or 0,
            notes_count=notes_count,
            planning_cycle_type=task.planning_cycle_type,
            planning_cycle_days=task.planning_cycle_days,
            planning_cycle_start_date=task.planning_cycle_start_date,
            created_at=task.created_at,
            updated_at=task.updated_at,
            deleted_at=task.deleted_at,
            persons=convert_persons_to_summary(persons_for_task),
            subtasks=child_responses,
            completion_percentage=completion_ratio(task, subtasks),
            depth=depth,
        )

    return [convert_to_response(task, depth=0) for task in root_tasks]


async def _get_user_calendar_system(db: AsyncSession, user_id: UUID) -> str:
    """
    Async variant of ``_get_user_calendar_system``.

    Defaults mirror ``USER_PREFERENCE_DEFAULTS['calendar.system']`` but the
    import is avoided here to prevent circular dependencies.
    """

    stmt = (
        select(UserPreference.value)
        .where(
            UserPreference.user_id == user_id,
            UserPreference.key == "calendar.system",
            UserPreference.deleted_at.is_(None),
        )
        .limit(1)
    )
    value = (await db.execute(stmt)).scalar_one_or_none()
    if value in {"gregorian", "mayan_13_moon"}:
        return value
    # Fallback to same default as the synchronous helper.
    return "gregorian"


async def _load_task_notes_count(
    db: AsyncSession, task_ids: Sequence[UUID], user_id: UUID
) -> Dict[UUID, int]:
    """Return a mapping of task_id -> related note count."""
    if not task_ids:
        return {}

    stmt = (
        select(Association.target_id, func.count(Association.id))
        .where(
            Association.user_id == user_id,
            Association.target_model == ModelName.Task.value,
            Association.source_model == ModelName.Note.value,
            Association.link_type == LinkType.RELATES_TO.value,
            Association.deleted_at.is_(None),
            Association.target_id.in_(task_ids),
        )
        .group_by(Association.target_id)
    )
    rows = await db.execute(stmt)
    return {task_id: count for task_id, count in rows.all()}


async def _load_task_persons_map(
    db: AsyncSession, task_ids: Sequence[UUID], user_id: UUID
) -> Dict[UUID, List[object]]:
    """Load persons linked to the provided tasks."""
    if not task_ids:
        return {}

    persons_map = await load_persons_for_sources(
        db,
        source_model=ModelName.Task,
        source_ids=list(task_ids),
        link_type=LinkType.INVOLVES,
        user_id=user_id,
    )
    return persons_map


async def _get_task_for_user(
    db: AsyncSession, *, user_id: UUID, task_id: UUID
) -> Optional[Task]:
    task = await db.get(Task, task_id)
    if not task or task.deleted_at is not None or task.user_id != user_id:
        return None
    return task


async def _require_task(db: AsyncSession, *, user_id: UUID, task_id: UUID) -> Task:
    task = await _get_task_for_user(db, user_id=user_id, task_id=task_id)
    if not task:
        raise TaskNotFoundError("Task not found")
    return task


async def _get_vision_for_user(
    db: AsyncSession, *, user_id: UUID, vision_id: UUID
) -> Optional[Vision]:
    vision = await db.get(Vision, vision_id)
    if not vision or vision.deleted_at is not None or vision.user_id != user_id:
        return None
    return vision


async def _validate_task_depth(
    db: AsyncSession, *, user_id: UUID, task_id: UUID
) -> int:
    """Mirror ``_validate_task_depth`` for AsyncSession."""
    current_depth = 0
    current_task_id = task_id

    while current_task_id:
        task = await _get_task_for_user(db, user_id=user_id, task_id=current_task_id)
        if not task:
            break

        current_depth += 1
        if current_depth > MAX_TASK_DEPTH:
            raise InvalidTaskDepthError(
                f"Task hierarchy depth cannot exceed {MAX_TASK_DEPTH} levels"
            )
        current_task_id = task.parent_task_id

    return current_depth


async def _update_descendant_visions(
    db: AsyncSession, *, user_id: UUID, root_task_id: UUID, new_vision_id: UUID
) -> List[Task]:
    """Update vision for descendants when moving tasks between visions."""
    updated: List[Task] = []
    queue: List[UUID] = [root_task_id]

    while queue:
        current_parent = queue.pop()
        stmt = select(Task).where(
            Task.deleted_at.is_(None),
            Task.user_id == user_id,
            Task.parent_task_id == current_parent,
        )
        children = (await db.execute(stmt)).scalars().all()
        for child in children:
            if child.vision_id != new_vision_id:
                child.vision_id = new_vision_id
                updated.append(child)
            queue.append(child.id)

    return updated


def _task_subtree_cte(task_id: UUID, user_id: UUID):
    task_subtree = (
        select(Task.id, Task.parent_task_id)
        .where(
            Task.id == task_id,
            Task.user_id == user_id,
            Task.deleted_at.is_(None),
        )
        .cte(name="task_subtree", recursive=True)
    )
    descendants = select(Task.id, Task.parent_task_id).where(
        Task.parent_task_id == task_subtree.c.id,
        Task.user_id == user_id,
        Task.deleted_at.is_(None),
    )
    return task_subtree.union_all(descendants)


async def _load_subtree_tasks(
    db: AsyncSession, *, user_id: UUID, root_task_id: UUID
) -> List[Task]:
    subtree = _task_subtree_cte(root_task_id, user_id)
    stmt = (
        select(Task)
        .join(subtree, Task.id == subtree.c.id)
        .order_by(Task.display_order, Task.created_at)
    )
    rows = await db.execute(stmt)
    return rows.scalars().all()


def _build_subtasks_loader(max_depth: int) -> List[Load]:
    """Return selectinload options that load subtasks up to ``max_depth`` levels."""

    if max_depth < 1:
        raise ValueError("max_depth must be at least 1")

    options: List[Load] = []
    current_option = selectinload(Task.subtasks)
    options.append(current_option)
    for _ in range(max_depth - 1):
        current_option = current_option.selectinload(Task.subtasks)
        options.append(current_option)
    return options


async def load_task_with_subtasks(
    db: AsyncSession,
    *,
    user_id: UUID,
    task_id: UUID,
    max_depth: int = 2,
) -> Task | None:
    """Load a task along with its subtasks up to ``max_depth`` levels."""

    load_options = _build_subtasks_loader(max_depth)
    stmt = (
        select(Task)
        .options(*load_options, selectinload(Task.parent_task))
        .where(
            Task.id == task_id,
            Task.user_id == user_id,
            Task.deleted_at.is_(None),
        )
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _populate_person_summaries(
    db: AsyncSession, tasks: Sequence[Task], *, user_id: UUID
) -> None:
    if not tasks:
        return
    await attach_persons_for_sources(
        db,
        source_model=ModelName.Task,
        items=tasks,
        link_type=LinkType.INVOLVES,
        user_id=user_id,
    )
    for task in tasks:
        persons = getattr(task, "persons", [])
        task.persons = convert_persons_to_summary(persons)  # type: ignore[attr-defined]


async def _schedule_recalc_jobs(
    db: AsyncSession,
    *,
    user_id: UUID,
    task_ids: Sequence[UUID] | None = None,
    vision_ids: Sequence[UUID] | None = None,
    reason: Optional[str] = None,
    run_async: bool = False,
) -> None:
    # 使用独立 session 以避免 work_recalc 调度导致当前 ORM 实例过早过期。
    await schedule_recalc_jobs(
        None,
        user_id=user_id,
        task_ids=task_ids,
        vision_ids=vision_ids,
        reason=reason,
        run_async=run_async,
    )


async def _is_leaf_task(db: AsyncSession, *, user_id: UUID, task_id: UUID) -> bool:
    stmt = (
        select(Task.id)
        .where(
            Task.deleted_at.is_(None),
            Task.user_id == user_id,
            Task.parent_task_id == task_id,
        )
        .limit(1)
    )
    return (await db.execute(stmt)).first() is None


async def _can_complete_task(db: AsyncSession, *, user_id: UUID, task: Task) -> bool:
    stmt = select(Task.status).where(
        Task.deleted_at.is_(None),
        Task.user_id == user_id,
        Task.parent_task_id == task.id,
    )
    rows = await db.execute(stmt)
    statuses = [row[0] for row in rows.all()]
    if not statuses:
        return task.status != "done"
    return all(status == "done" for status in statuses)


async def _build_task_list_stmt(
    db: AsyncSession,
    *,
    user_id: UUID,
    vision_id: Optional[UUID],
    vision_in: Optional[str] = None,
    status_filter: Optional[str],
    status_in: Optional[str],
    exclude_status: Optional[str],
    planning_cycle_type: Optional[str],
    planning_cycle_start_date: Optional[str],
    content: Optional[str],
) -> Any:
    stmt = (
        select(Task)
        .join(Vision, Task.vision_id == Vision.id)
        .where(
            Task.deleted_at.is_(None),
            Task.user_id == user_id,
            Vision.deleted_at.is_(None),
        )
    )

    if vision_id:
        stmt = stmt.where(Task.vision_id == vision_id)

    if vision_in:
        try:
            allowed_vision_ids = [
                UUID(vid.strip()) for vid in vision_in.split(",") if vid.strip()
            ]
            if allowed_vision_ids:
                stmt = stmt.where(Task.vision_id.in_(allowed_vision_ids))
        except ValueError:
            # If any ID is invalid, we could raise error or just ignore.
            # Following pattern of status_in, let's just ignore invalid parts if they are not UUIDs
            pass

    if status_filter:
        if status_filter not in TASK_ALLOWED_STATUSES:
            raise InvalidStatusError(
                f"Invalid status filter. Must be one of: "
                f"{', '.join(sorted(TASK_ALLOWED_STATUSES))}"
            )
        stmt = stmt.where(Task.status == status_filter)

    if status_in:
        allowed = [s.strip() for s in status_in.split(",") if s.strip()]
        if allowed:
            stmt = stmt.where(Task.status.in_(allowed))

    if exclude_status:
        excluded = [s.strip() for s in exclude_status.split(",") if s.strip()]
        if excluded:
            stmt = stmt.where(not_(Task.status.in_(excluded)))

    if planning_cycle_type:
        if planning_cycle_type not in PLANNING_CYCLE_TYPES:
            raise InvalidOperationError(
                f"Invalid planning cycle type. Must be one of: "
                f"{', '.join(sorted(PLANNING_CYCLE_TYPES))}"
            )
        stmt = stmt.where(Task.planning_cycle_type == planning_cycle_type)

    if planning_cycle_start_date:
        try:
            parsed_date = date.fromisoformat(planning_cycle_start_date)
        except ValueError:
            raise InvalidOperationError(
                "Invalid planning_cycle_start_date format. Must be YYYY-MM-DD"
            ) from None

        if planning_cycle_type:
            calendar_system = await _get_user_calendar_system(db, user_id)
            cycle_start, cycle_end = _get_cycle_date_range(
                planning_cycle_type, parsed_date, calendar_system
            )
            stmt = stmt.where(
                Task.planning_cycle_start_date >= cycle_start,
                Task.planning_cycle_start_date <= cycle_end,
            )
        else:
            stmt = stmt.where(Task.planning_cycle_start_date == parsed_date)

    if content:
        normalized = content.strip()
        if normalized:
            stmt = stmt.where(Task.content == normalized)

    return stmt


async def _hydrate_task_list(
    db: AsyncSession,
    tasks: List[Task],
    *,
    user_id: UUID,
    include_details: bool,
) -> List[Task]:
    if not tasks:
        return []

    task_ids = [task.id for task in tasks]
    if include_details:
        notes_count_map = await _load_task_notes_count(db, task_ids, user_id)
        persons_map = await _load_task_persons_map(db, task_ids, user_id)
    else:
        notes_count_map = {task_id: 0 for task_id in task_ids}
        persons_map = {}

    for task in tasks:
        task.actual_effort_total = task.actual_effort_total or 0
        task.actual_effort_self = task.actual_effort_self or 0
        task.actual_effort = task.actual_effort_total  # type: ignore[attr-defined]
        task.notes_count = notes_count_map.get(task.id, 0)
        if include_details:
            persons = persons_map.get(task.id, [])
            task.persons = convert_persons_to_summary(  # type: ignore[attr-defined]
                persons
            )
        else:
            task.persons = []  # type: ignore[attr-defined]

    return tasks


async def list_tasks(
    db: AsyncSession,
    *,
    user_id: UUID,
    skip: int = 0,
    limit: int = 100,
    vision_id: Optional[UUID] = None,
    vision_in: Optional[str] = None,
    status_filter: Optional[str] = None,
    status_in: Optional[str] = None,
    exclude_status: Optional[str] = None,
    planning_cycle_type: Optional[str] = None,
    planning_cycle_start_date: Optional[str] = None,
    content: Optional[str] = None,
    include_details: bool = True,
) -> List[Task]:
    """Async version of ``app.handlers.tasks.list_tasks``."""
    stmt = await _build_task_list_stmt(
        db,
        user_id=user_id,
        vision_id=vision_id,
        vision_in=vision_in,
        status_filter=status_filter,
        status_in=status_in,
        exclude_status=exclude_status,
        planning_cycle_type=planning_cycle_type,
        planning_cycle_start_date=planning_cycle_start_date,
        content=content,
    )
    stmt = stmt.order_by(Task.display_order, Task.created_at).offset(skip).limit(limit)
    rows = await db.execute(stmt)
    tasks = rows.scalars().all()
    return await _hydrate_task_list(
        db, tasks, user_id=user_id, include_details=include_details
    )


async def list_tasks_with_total(
    db: AsyncSession,
    *,
    user_id: UUID,
    skip: int = 0,
    limit: int = 100,
    vision_id: Optional[UUID] = None,
    vision_in: Optional[str] = None,
    status_filter: Optional[str] = None,
    status_in: Optional[str] = None,
    exclude_status: Optional[str] = None,
    planning_cycle_type: Optional[str] = None,
    planning_cycle_start_date: Optional[str] = None,
    content: Optional[str] = None,
    include_details: bool = True,
) -> Tuple[List[Task], int]:
    stmt = await _build_task_list_stmt(
        db,
        user_id=user_id,
        vision_id=vision_id,
        vision_in=vision_in,
        status_filter=status_filter,
        status_in=status_in,
        exclude_status=exclude_status,
        planning_cycle_type=planning_cycle_type,
        planning_cycle_start_date=planning_cycle_start_date,
        content=content,
    )
    count_stmt = select(func.count()).select_from(stmt.subquery())
    stmt = stmt.order_by(Task.display_order, Task.created_at).offset(skip).limit(limit)
    rows = await db.execute(stmt)
    tasks = rows.scalars().all()
    total = await db.scalar(count_stmt)
    hydrated = await _hydrate_task_list(
        db, tasks, user_id=user_id, include_details=include_details
    )
    return hydrated, int(total or 0)


async def get_vision_task_hierarchy(
    db: AsyncSession, *, user_id: UUID, vision_id: UUID
) -> TaskHierarchy:
    """Async version of ``app.handlers.tasks.get_vision_task_hierarchy``."""
    vision_stmt = select(Vision.id).where(
        Vision.deleted_at.is_(None),
        Vision.user_id == user_id,
        Vision.id == vision_id,
    )
    vision_exists = (await db.execute(vision_stmt)).scalar_one_or_none()
    if not vision_exists:
        raise VisionNotFoundError("Vision not found")

    tasks_stmt = (
        select(Task)
        .where(
            Task.deleted_at.is_(None),
            Task.user_id == user_id,
            Task.vision_id == vision_id,
        )
        .order_by(Task.display_order, Task.created_at)
    )
    tasks = (await db.execute(tasks_stmt)).scalars().all()
    if not tasks:
        return TaskHierarchy(vision_id=vision_id, root_tasks=[])

    task_ids = [task.id for task in tasks]
    persons_map = await _load_task_persons_map(db, task_ids, user_id)
    notes_count_map = await _load_task_notes_count(db, task_ids, user_id)
    task_tree = _build_task_tree(
        tasks,
        task_id_to_persons=persons_map,
        task_notes_count_map=notes_count_map,
    )
    return TaskHierarchy(vision_id=vision_id, root_tasks=task_tree)


async def get_task(db: AsyncSession, *, user_id: UUID, task_id: UUID) -> Optional[Task]:
    """Async variant of ``get_task``."""
    task = await _get_task_for_user(db, user_id=user_id, task_id=task_id)
    if not task:
        return None

    task.actual_effort = task.actual_effort_total or 0  # type: ignore[attr-defined]
    notes_map = await _load_task_notes_count(db, [task.id], user_id)
    task.notes_count = notes_map.get(task.id, 0)
    return task


async def get_task_with_subtasks(
    db: AsyncSession, *, user_id: UUID, task_id: UUID
) -> Optional[TaskWithSubtasks]:
    """Async variant of ``get_task_with_subtasks``."""
    await _require_task(db, user_id=user_id, task_id=task_id)
    tasks = await _load_subtree_tasks(db, user_id=user_id, root_task_id=task_id)
    if not tasks:
        return None

    task_ids = [task.id for task in tasks]
    persons_map = await _load_task_persons_map(db, task_ids, user_id)
    notes_map = await _load_task_notes_count(db, task_ids, user_id)
    task_tree = _build_task_tree(
        tasks,
        task_id_to_persons=persons_map,
        task_notes_count_map=notes_map,
    )
    return task_tree[0] if task_tree else None


async def create_task(
    db: AsyncSession,
    *,
    user_id: UUID,
    task_data: TaskCreate,
    run_async: bool = False,
) -> Task:
    vision = await _get_vision_for_user(
        db, user_id=user_id, vision_id=task_data.vision_id
    )
    if not vision:
        raise VisionNotFoundError("Vision not found")

    if task_data.parent_task_id:
        parent_task = await _get_task_for_user(
            db, user_id=user_id, task_id=task_data.parent_task_id
        )
        if not parent_task or parent_task.vision_id != task_data.vision_id:
            raise ParentTaskNotFoundError(
                "Parent task not found or not in the same vision"
            )
        depth = await _validate_task_depth(
            db, user_id=user_id, task_id=task_data.parent_task_id
        )
        if depth + 1 > MAX_TASK_DEPTH:
            raise InvalidTaskDepthError(
                f"Task hierarchy depth cannot exceed {MAX_TASK_DEPTH} levels"
            )

    stmt = (
        select(Task.display_order)
        .where(
            Task.deleted_at.is_(None),
            Task.user_id == user_id,
            Task.vision_id == task_data.vision_id,
            Task.parent_task_id == task_data.parent_task_id,
        )
        .order_by(Task.display_order.desc())
        .limit(1)
    )
    max_order = (await db.execute(stmt)).scalar_one_or_none()
    next_display_order = (max_order if max_order is not None else -1) + 1

    data = task_data.model_dump(exclude={"person_ids"})
    task = Task(**data, user_id=user_id)
    task.display_order = next_display_order

    if not task.validate_planning_cycle():
        raise InvalidPlanningCycleError(
            "Invalid planning cycle data. All three fields (type, days, start_date) must be set together or all be empty."
        )

    db.add(task)
    await db.flush()

    if task_data.person_ids:
        await set_links(
            db,
            source_model=ModelName.Task,
            source_id=task.id,
            target_model=ModelName.Person,
            target_ids=task_data.person_ids,
            link_type=LinkType.INVOLVES,
            replace=True,
            user_id=user_id,
        )

    await commit_safely(db)
    await db.refresh(task)
    await _populate_person_summaries(db, [task], user_id=user_id)
    task.actual_effort = task.actual_effort_total or 0  # type: ignore[attr-defined]

    await _schedule_recalc_jobs(
        db,
        user_id=user_id,
        task_ids=[task.id],
        vision_ids=[task.vision_id] if task.vision_id else [],
        reason="task:create",
        run_async=run_async,
    )
    # Re-fetch after scheduling jobs because the preceding commit expires attributes.
    await db.refresh(task)
    return task


async def update_task(
    db: AsyncSession,
    *,
    user_id: UUID,
    task_id: UUID,
    task_data: TaskUpdate,
    run_async: bool = False,
) -> Task:
    task = await _require_task(db, user_id=user_id, task_id=task_id)
    update_data = task_data.model_dump(exclude_unset=True)
    original_vision_id = task.vision_id

    if "parent_task_id" in update_data:
        parent_task_id = update_data["parent_task_id"]
        if parent_task_id:
            parent_task = await _get_task_for_user(
                db, user_id=user_id, task_id=parent_task_id
            )
            if not parent_task or parent_task.vision_id != task.vision_id:
                raise ParentTaskNotFoundError(
                    "Parent task not found or not in the same vision"
                )
            if parent_task_id == task_id:
                raise CircularReferenceError("Task cannot be its own parent")

            current_parent_id = parent_task.parent_task_id
            while current_parent_id:
                if current_parent_id == task_id:
                    raise CircularReferenceError(
                        "This would create a circular reference"
                    )
                ancestor = await _get_task_for_user(
                    db, user_id=user_id, task_id=current_parent_id
                )
                if not ancestor:
                    break
                current_parent_id = ancestor.parent_task_id

            depth = await _validate_task_depth(
                db, user_id=user_id, task_id=parent_task_id
            )
            if depth + 1 > MAX_TASK_DEPTH:
                raise InvalidTaskDepthError(
                    f"Task hierarchy depth cannot exceed {MAX_TASK_DEPTH} levels"
                )

    if "person_ids" in update_data:
        person_ids = update_data.pop("person_ids") or []
        await set_links(
            db,
            source_model=ModelName.Task,
            source_id=task.id,
            target_model=ModelName.Person,
            target_ids=person_ids,
            link_type=LinkType.INVOLVES,
            replace=True,
            user_id=user_id,
        )

    for field, value in update_data.items():
        setattr(task, field, value)

    if not task.validate_planning_cycle():
        raise InvalidPlanningCycleError(
            "Invalid planning cycle data. All three fields (type, days, start_date) must be set together or all be empty."
        )

    await commit_safely(db)
    await db.refresh(task)
    await _populate_person_summaries(db, [task], user_id=user_id)

    try:
        if "parent_task_id" in update_data:
            await recompute_subtree_totals(db, task.id)
            await recompute_totals_upwards(db, task.id)
            await commit_safely(db)
    except Exception:
        pass

    task.actual_effort = task.actual_effort_total or 0  # type: ignore[attr-defined]
    affected_vision_ids = {
        vid for vid in [original_vision_id, task.vision_id] if vid is not None
    }

    await _schedule_recalc_jobs(
        db,
        user_id=user_id,
        task_ids=[task.id],
        vision_ids=list(affected_vision_ids),
        reason="task:update",
        run_async=run_async,
    )
    return task


async def update_task_status(
    db: AsyncSession,
    *,
    user_id: UUID,
    task_id: UUID,
    status_data: TaskStatusUpdate,
    run_async: bool = False,
) -> Task:
    task = await _require_task(db, user_id=user_id, task_id=task_id)
    if status_data.status == "done":
        can_complete = await _can_complete_task(db, user_id=user_id, task=task)
        if not can_complete:
            raise TaskCannotBeCompletedError(
                "Task cannot be completed (subtasks may need to be completed first)"
            )

    task.status = status_data.status
    await commit_safely(db)
    await db.refresh(task)
    task.actual_effort = task.actual_effort_total or 0  # type: ignore[attr-defined]

    await _schedule_recalc_jobs(
        db,
        user_id=user_id,
        task_ids=[task.id],
        vision_ids=[task.vision_id] if task.vision_id else [],
        reason="task:update_status",
        run_async=run_async,
    )
    return task


async def delete_task(
    db: AsyncSession,
    *,
    user_id: UUID,
    task_id: UUID,
    hard_delete: bool = False,
    run_async: bool = False,
) -> bool:
    task = await _require_task(db, user_id=user_id, task_id=task_id)
    subtree_tasks = await _load_subtree_tasks(db, user_id=user_id, root_task_id=task_id)
    affected_task_ids = [subtask.id for subtask in subtree_tasks]
    affected_vision_ids = {
        subtask.vision_id for subtask in subtree_tasks if subtask.vision_id
    }

    if hard_delete:
        await db.delete(task)
    else:
        for subtask in subtree_tasks:
            subtask.soft_delete()

    await commit_safely(db)
    await _schedule_recalc_jobs(
        db,
        user_id=user_id,
        task_ids=affected_task_ids,
        vision_ids=list(affected_vision_ids),
        reason="task:delete",
        run_async=run_async,
    )
    return True


async def reorder_tasks(
    db: AsyncSession, *, user_id: UUID, reorder_data: TaskReorderRequest
) -> None:
    task_ids = [UUID(item["id"]) for item in reorder_data.task_orders]
    if not task_ids:
        return

    stmt = select(Task).where(
        Task.deleted_at.is_(None),
        Task.user_id == user_id,
        Task.id.in_(task_ids),
    )
    tasks = (await db.execute(stmt)).scalars().all()
    if len(tasks) != len(task_ids):
        raise TaskNotFoundError("One or more tasks not found")

    task_map = {task.id: task for task in tasks}
    for item in reorder_data.task_orders:
        task_map[UUID(item["id"])].display_order = item["display_order"]

    await commit_safely(db)


async def move_task(
    db: AsyncSession,
    *,
    user_id: UUID,
    task_id: UUID,
    move_data: TaskMoveRequest,
    run_async: bool = False,
) -> TaskMoveResult:
    task = await _require_task(db, user_id=user_id, task_id=task_id)
    updated_descendants: List[Task] = []
    current_vision_id = task.vision_id
    target_vision_id = move_data.new_vision_id or current_vision_id

    if move_data.new_vision_id and move_data.new_vision_id != current_vision_id:
        vision = await _get_vision_for_user(
            db, user_id=user_id, vision_id=move_data.new_vision_id
        )
        if not vision:
            raise VisionNotFoundError("New vision not found")

    if (
        move_data.old_parent_task_id is not None
        and move_data.old_parent_task_id != task.parent_task_id
    ):
        raise InvalidOperationError(
            "Old parent task ID does not match current parent task ID"
        )

    if move_data.new_parent_task_id:
        new_parent = await _get_task_for_user(
            db, user_id=user_id, task_id=move_data.new_parent_task_id
        )
        if not new_parent or new_parent.vision_id != target_vision_id:
            raise ParentTaskNotFoundError(
                "New parent task not found or not in target vision"
            )
        if move_data.new_parent_task_id == task_id:
            raise CircularReferenceError("Task cannot be its own parent")

        current_parent_id = new_parent.parent_task_id
        while current_parent_id:
            if current_parent_id == task_id:
                raise CircularReferenceError("This would create a circular reference")
            ancestor = await _get_task_for_user(
                db, user_id=user_id, task_id=current_parent_id
            )
            if not ancestor:
                break
            current_parent_id = ancestor.parent_task_id

        depth = await _validate_task_depth(
            db, user_id=user_id, task_id=move_data.new_parent_task_id
        )
        if depth + 1 > MAX_TASK_DEPTH:
            raise InvalidTaskDepthError(
                f"Task hierarchy depth cannot exceed {MAX_TASK_DEPTH} levels"
            )

    old_vision_id = current_vision_id
    task.parent_task_id = move_data.new_parent_task_id
    task.display_order = move_data.new_display_order

    if move_data.new_vision_id and move_data.new_vision_id != current_vision_id:
        task.vision_id = move_data.new_vision_id
        updated_descendants = await _update_descendant_visions(
            db,
            user_id=user_id,
            root_task_id=task.id,
            new_vision_id=move_data.new_vision_id,
        )

    await commit_safely(db)
    await db.refresh(task)
    for descendant in updated_descendants:
        await db.refresh(descendant)

    try:
        await recompute_subtree_totals(db, task.id)
        await recompute_totals_upwards(db, task.id)

        if move_data.old_parent_task_id:
            try:
                await recompute_totals_upwards(db, move_data.old_parent_task_id)
            except Exception:
                pass

        if move_data.new_parent_task_id:
            try:
                await recompute_totals_upwards(db, move_data.new_parent_task_id)
            except Exception:
                pass

        if move_data.new_vision_id and move_data.new_vision_id != old_vision_id:
            stmt = select(Task.id).where(
                Task.deleted_at.is_(None),
                Task.user_id == user_id,
                Task.vision_id == old_vision_id,
                Task.parent_task_id.is_(None),
            )
            root_ids = [row[0] for row in (await db.execute(stmt)).all()]
            for root_id in root_ids:
                try:
                    await recompute_totals_upwards(db, root_id)
                except Exception:
                    pass

        await commit_safely(db)
    except Exception:
        pass

    task.actual_effort = task.actual_effort_total or 0  # type: ignore[attr-defined]
    affected_task_ids: Set[UUID] = {task.id}
    affected_task_ids.update(desc.id for desc in updated_descendants)
    affected_vision_ids = {
        vid for vid in [old_vision_id, task.vision_id] if vid is not None
    }

    await _schedule_recalc_jobs(
        db,
        user_id=user_id,
        task_ids=list(affected_task_ids),
        vision_ids=list(affected_vision_ids),
        reason="task:move",
        run_async=run_async,
    )
    return TaskMoveResult(task=task, updated_descendants=updated_descendants)


async def get_task_stats(
    db: AsyncSession, *, user_id: UUID, task_id: UUID
) -> TaskStatsResponse:
    await _require_task(db, user_id=user_id, task_id=task_id)
    tasks = await _load_subtree_tasks(db, user_id=user_id, root_task_id=task_id)
    if not tasks:
        raise TaskNotFoundError("Task not found")

    root = next((task for task in tasks if task.id == task_id), None)
    if not root:
        raise TaskNotFoundError("Task not found")

    subtasks = [task for task in tasks if task.id != task_id]
    total_subtasks = len(subtasks)
    completed_subtasks = len([task for task in subtasks if task.status == "done"])

    direct_children = [task for task in subtasks if task.parent_task_id == task_id]
    if not direct_children:
        completion_percentage = 1.0 if root.status == "done" else 0.0
    else:
        done_children = len([task for task in direct_children if task.status == "done"])
        completion_percentage = done_children / len(direct_children)

    total_estimated_effort = sum(
        task.estimated_effort or 0 for task in subtasks if task.estimated_effort
    )
    total_actual_effort = sum((task.actual_effort_self or 0) for task in subtasks)

    if root.estimated_effort:
        total_estimated_effort += root.estimated_effort
    total_actual_effort += root.actual_effort_self or 0

    return TaskStatsResponse(
        total_subtasks=total_subtasks,
        completed_subtasks=completed_subtasks,
        completion_percentage=completion_percentage,
        total_estimated_effort=total_estimated_effort or None,
        total_actual_effort=total_actual_effort or None,
    )


def _build_task_actual_events_stmt(*, user_id: UUID, task_id: UUID):
    return (
        select(ActualEvent)
        .options(
            selectinload(ActualEvent.dimension),
            selectinload(ActualEvent.task).selectinload(Task.vision),
        )
        .where(
            ActualEvent.deleted_at.is_(None),
            ActualEvent.user_id == user_id,
            ActualEvent.task_id == task_id,
        )
        .order_by(ActualEvent.start_time.desc())
    )


async def _serialize_actual_events(
    db: AsyncSession,
    *,
    user_id: UUID,
    events: Sequence[ActualEvent],
) -> List[ActualEventResponse]:
    if not events:
        return []

    event_ids = [event.id for event in events]
    persons_map = await load_persons_for_sources(
        db,
        source_model=ModelName.ActualEvent,
        source_ids=event_ids,
        link_type=LinkType.ATTENDED_BY,
        user_id=user_id,
    )

    responses: List[ActualEventResponse] = []
    for event in events:
        person_summaries = convert_persons_to_summary(persons_map.get(event.id, []))
        task_data = None
        if event.task:
            task_summary = build_task_summary(event.task, include_parent_summary=False)
            task_data = normalize_task_summary(task_summary, event, as_json=False)

        payload = {
            **event.__dict__,
            "persons": person_summaries,
            "task": task_data,
            "dimension_summary": serialize_dimension_summary(event.dimension),
        }
        responses.append(ActualEventResponse.model_validate(payload))

    return responses


async def get_task_actual_events(
    db: AsyncSession, *, user_id: UUID, task_id: UUID
) -> List[ActualEventResponse]:
    await _require_task(db, user_id=user_id, task_id=task_id)
    events_stmt = _build_task_actual_events_stmt(user_id=user_id, task_id=task_id)
    events = (await db.execute(events_stmt)).scalars().all()
    return await _serialize_actual_events(db, user_id=user_id, events=events)


async def get_task_actual_events_with_total(
    db: AsyncSession,
    *,
    user_id: UUID,
    task_id: UUID,
    limit: int = 100,
    offset: int = 0,
) -> Tuple[List[ActualEventResponse], int]:
    await _require_task(db, user_id=user_id, task_id=task_id)
    events_stmt = _build_task_actual_events_stmt(user_id=user_id, task_id=task_id)
    count_stmt = select(func.count()).select_from(events_stmt.subquery())
    events_stmt = events_stmt.offset(offset).limit(limit)
    events = (await db.execute(events_stmt)).scalars().all()
    total = await db.scalar(count_stmt)
    responses = await _serialize_actual_events(db, user_id=user_id, events=events)
    return responses, int(total or 0)


__all__ = [
    "create_task",
    "delete_task",
    "get_task",
    "get_task_actual_events",
    "get_task_actual_events_with_total",
    "get_task_stats",
    "get_task_with_subtasks",
    "get_vision_task_hierarchy",
    "list_tasks",
    "move_task",
    "reorder_tasks",
    "update_task",
    "update_task_status",
]
