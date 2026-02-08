"""
Async implementations for the vision service layer.

这些实现覆盖 Agent 工具当前使用的 Vision CRUD 能力，避免继续依赖
``run_with_session`` 将请求转回同步 Session。随着迁移推进，可逐步补充
其他高级功能（体验值、收获等）到该模块。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Union
from uuid import UUID

from sqlalchemy import Column, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.constants import (
    USER_PREFERENCE_DEFAULTS,
    VISION_ALLOWED_STATUSES,
    VISION_EXPERIENCE_RATE_DEFAULT,
    VISION_EXPERIENCE_RATE_MAX,
)
from app.core.logging import get_logger
from app.db.models.person import Person
from app.db.models.task import Task
from app.db.models.vision import Vision
from app.db.transaction import commit_safely
from app.handlers import user_preferences as user_preferences_service
from app.handlers.associations import LinkType, ModelName
from app.handlers.associations_async import attach_persons_for_sources, set_links
from app.schemas.vision import (
    VisionCreate,
    VisionExperienceRateUpdateItem,
    VisionExperienceUpdate,
    VisionHarvestRequest,
    VisionStatsResponse,
    VisionUpdate,
)

logger = get_logger(__name__)


class VisionServiceError(Exception):
    """Base exception for vision handler errors."""


class VisionNotFoundError(VisionServiceError):
    """Raised when a vision is not found."""


class VisionAlreadyExistsError(VisionServiceError):
    """Raised when a vision with the same name already exists."""


class InvalidVisionStatusError(VisionServiceError):
    """Raised when a provided status value is invalid."""


class VisionNotReadyForHarvestError(VisionServiceError):
    """Raised when attempting to harvest a vision that is not ready."""


class InvalidVisionExperienceRateError(VisionServiceError):
    """Raised when an experience rate is outside the allowed range."""


VISION_EXPERIENCE_PREF_KEY = "visions.experience_rate_per_hour"
DEFAULT_EXPERIENCE_RATE = USER_PREFERENCE_DEFAULTS.get(
    VISION_EXPERIENCE_PREF_KEY, {}
).get("value", VISION_EXPERIENCE_RATE_DEFAULT)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _normalize_experience_rate(value: Optional[Union[int, str]]) -> Optional[int]:
    if value is None:
        return None
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    if 1 <= normalized <= VISION_EXPERIENCE_RATE_MAX:
        return normalized
    return None


def _coerce_uuid_list(values: Sequence[Union[str, UUID]]) -> List[UUID]:
    normalized: List[UUID] = []
    for value in values:
        if isinstance(value, UUID):
            normalized.append(value)
            continue
        try:
            normalized.append(UUID(str(value)))
        except (TypeError, ValueError) as exc:  # pragma: no cover - defensive branch
            raise VisionNotFoundError("Invalid person ID provided") from exc
    return normalized


async def _annotate_total_effort(
    db: AsyncSession, *, visions: Sequence[Vision], user_id: Union[UUID, Column]
) -> None:
    vision_ids = [vision.id for vision in visions if getattr(vision, "id", None)]
    if not vision_ids:
        return

    stmt = (
        select(Task.vision_id, func.sum(Task.actual_effort_total).label("total"))
        .where(
            Task.vision_id.in_(vision_ids),
            Task.user_id == user_id,
            Task.deleted_at.is_(None),
            Task.parent_task_id.is_(None),
        )
        .group_by(Task.vision_id)
    )
    rows = await db.execute(stmt)
    totals: Dict[UUID, int] = {
        vision_id: int(total or 0) for vision_id, total in rows.all()
    }
    for vision in visions:
        setattr(vision, "total_actual_effort", totals.get(vision.id, 0))


async def _attach_persons(
    db: AsyncSession, *, visions: Sequence[Vision], user_id: Union[UUID, Column]
) -> None:
    await attach_persons_for_sources(
        db,
        source_model=ModelName.Vision,
        items=visions,
        link_type=LinkType.INVOLVES,
        user_id=user_id,
    )


async def _load_single_vision(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    vision_id: UUID,
    with_tasks: bool = False,
) -> Optional[Vision]:
    options = []
    if with_tasks:
        options.append(selectinload(Vision.tasks))

    stmt = (
        select(Vision)
        .where(
            Vision.id == vision_id,
            Vision.user_id == user_id,
            Vision.deleted_at.is_(None),
        )
        .limit(1)
    )
    if options:
        stmt = stmt.options(*options)
    result = await db.execute(stmt)
    return result.scalars().first()


async def _ensure_person_ids_exist(
    db: AsyncSession, *, user_id: Union[UUID, Column], person_ids: Sequence[UUID]
) -> None:
    if not person_ids:
        return
    stmt = (
        select(Person.id)
        .where(
            Person.user_id == user_id,
            Person.id.in_(person_ids),
            Person.deleted_at.is_(None),
        )
        .order_by(Person.id)
    )
    rows = await db.execute(stmt)
    found = set(rows.scalars().all())
    missing = [str(pid) for pid in person_ids if pid not in found]
    if missing:
        raise VisionNotFoundError(
            f"One or more person IDs not found: {', '.join(missing)}"
        )


async def get_user_experience_rate(
    db: AsyncSession, *, user_id: Union[UUID, Column]
) -> int:
    raw_value = await user_preferences_service.get_preference_value(
        db,
        user_id=user_id,
        key=VISION_EXPERIENCE_PREF_KEY,
        default=DEFAULT_EXPERIENCE_RATE,
    )
    normalized = _normalize_experience_rate(raw_value)
    return normalized or DEFAULT_EXPERIENCE_RATE


async def resolve_experience_rate_for_vision(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    vision: Vision,
    user_rate_cache: Optional[int] = None,
) -> int:
    vision_rate = _normalize_experience_rate(vision.experience_rate_per_hour)
    if vision_rate is not None:
        return vision_rate
    cache = user_rate_cache
    if cache is None:
        cache = await get_user_experience_rate(db, user_id=user_id)
    return cache or DEFAULT_EXPERIENCE_RATE


def _apply_effective_experience_rate(vision: Vision, effective_rate: int) -> None:
    if vision.experience_rate_per_hour is None:
        vision.experience_rate_per_hour = effective_rate


def _build_visions_query(
    *,
    user_id: Union[UUID, Column],
    status_filter: Optional[str],
    name: Optional[str],
) -> Any:
    stmt = select(Vision).where(
        Vision.user_id == user_id,
        Vision.deleted_at.is_(None),
    )
    if status_filter:
        if status_filter not in VISION_ALLOWED_STATUSES:
            raise InvalidVisionStatusError(
                "Invalid status filter. Must be one of: "
                f"{', '.join(sorted(VISION_ALLOWED_STATUSES))}"
            )
        stmt = stmt.where(Vision.status == status_filter)
    if name:
        normalized = name.strip()
        if normalized:
            stmt = stmt.where(Vision.name == normalized)
    return stmt


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
async def list_visions(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    skip: int = 0,
    limit: int = 100,
    status_filter: Optional[str] = None,
    name: Optional[str] = None,
) -> List[Vision]:
    stmt = _build_visions_query(
        user_id=user_id,
        status_filter=status_filter,
        name=name,
    )
    stmt = stmt.order_by(Vision.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    visions = result.scalars().unique().all()
    if not visions:
        return []

    await _annotate_total_effort(db, visions=visions, user_id=user_id)
    await _attach_persons(db, visions=visions, user_id=user_id)
    return visions


async def list_visions_with_total(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    skip: int = 0,
    limit: int = 100,
    status_filter: Optional[str] = None,
    name: Optional[str] = None,
) -> tuple[List[Vision], int]:
    stmt = _build_visions_query(
        user_id=user_id,
        status_filter=status_filter,
        name=name,
    )
    count_stmt = select(func.count()).select_from(stmt.subquery())
    stmt = stmt.order_by(Vision.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    visions = result.scalars().unique().all()
    total = await db.scalar(count_stmt)
    if not visions:
        return [], int(total or 0)

    await _annotate_total_effort(db, visions=visions, user_id=user_id)
    await _attach_persons(db, visions=visions, user_id=user_id)
    return visions, int(total or 0)


async def get_vision_with_tasks(
    db: AsyncSession, *, user_id: Union[UUID, Column], vision_id: UUID
) -> Optional[dict]:
    vision = await _load_single_vision(
        db, user_id=user_id, vision_id=vision_id, with_tasks=True
    )
    if vision is None:
        return None

    effective_rate = await resolve_experience_rate_for_vision(
        db, user_id=user_id, vision=vision
    )
    _apply_effective_experience_rate(vision, effective_rate)

    tasks_stmt = (
        select(Task)
        .where(
            Task.user_id == user_id,
            Task.vision_id == vision_id,
            Task.deleted_at.is_(None),
        )
        .order_by(Task.display_order, Task.created_at)
    )
    task_rows = await db.execute(tasks_stmt)
    tasks = task_rows.scalars().all()

    await _attach_persons(db, visions=[vision], user_id=user_id)
    payload = {
        column.name: getattr(vision, column.name) for column in vision.__table__.columns
    }
    payload["persons"] = list(getattr(vision, "persons", []))
    payload["tasks"] = tasks
    return payload


async def get_vision(
    db: AsyncSession, *, user_id: Union[UUID, Column], vision_id: UUID
) -> Optional[Vision]:
    vision = await _load_single_vision(
        db, user_id=user_id, vision_id=vision_id, with_tasks=True
    )
    if vision is None:
        return None

    effective_rate = await resolve_experience_rate_for_vision(
        db, user_id=user_id, vision=vision
    )
    _apply_effective_experience_rate(vision, effective_rate)
    tasks = list(getattr(vision, "tasks", []) or [])
    vision.sync_experience_with_actual_effort(
        experience_rate_per_hour=effective_rate,
        tasks=tasks,
    )
    await commit_safely(db)
    await db.refresh(vision)
    await _attach_persons(db, visions=[vision], user_id=user_id)
    await _annotate_total_effort(db, visions=[vision], user_id=user_id)
    return vision


async def create_vision(
    db: AsyncSession, *, user_id: Union[UUID, Column], vision_in: VisionCreate
) -> Vision:
    stmt = (
        select(Vision.id)
        .where(
            Vision.user_id == user_id,
            Vision.deleted_at.is_(None),
            Vision.name == vision_in.name,
            Vision.status == "active",
        )
        .limit(1)
    )
    exists = (await db.execute(stmt)).scalar_one_or_none()
    if exists:
        raise VisionAlreadyExistsError("A vision with this name already exists")

    data = vision_in.model_dump(exclude={"person_ids"})
    vision = Vision(**data, user_id=user_id)
    db.add(vision)
    await db.flush()

    person_ids: Optional[List[UUID]] = None
    if vision_in.person_ids:
        person_ids = _coerce_uuid_list(vision_in.person_ids)
        await _ensure_person_ids_exist(db, user_id=user_id, person_ids=person_ids)
        await set_links(
            db,
            source_model=ModelName.Vision,
            source_id=vision.id,
            target_model=ModelName.Person,
            target_ids=person_ids,
            link_type=LinkType.INVOLVES,
            replace=True,
            user_id=user_id,
        )

    await commit_safely(db)
    await db.refresh(vision)
    await _attach_persons(db, visions=[vision], user_id=user_id)
    await _annotate_total_effort(db, visions=[vision], user_id=user_id)
    return vision


async def update_all_vision_experience_rates(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    experience_rate_per_hour: int,
) -> List[Vision]:
    if (
        experience_rate_per_hour < 1
        or experience_rate_per_hour > VISION_EXPERIENCE_RATE_MAX
    ):
        raise InvalidVisionExperienceRateError(
            f"Experience rate must be between 1 and {VISION_EXPERIENCE_RATE_MAX}"
        )

    stmt = (
        select(Vision)
        .where(Vision.user_id == user_id, Vision.deleted_at.is_(None))
        .order_by(Vision.created_at.asc())
    )
    rows = await db.execute(stmt)
    visions = rows.scalars().unique().all()
    if not visions:
        return []

    for vision in visions:
        vision.experience_rate_per_hour = experience_rate_per_hour
        vision.sync_experience_with_actual_effort(
            experience_rate_per_hour=experience_rate_per_hour
        )

    await commit_safely(db)
    for vision in visions:
        await db.refresh(vision)
    await _attach_persons(db, visions=visions, user_id=user_id)
    await _annotate_total_effort(db, visions=visions, user_id=user_id)
    return visions


async def bulk_update_vision_experience_rates(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    updates: List[VisionExperienceRateUpdateItem],
) -> List[Vision]:
    if not updates:
        return []

    vision_ids = [item.id for item in updates]
    stmt = (
        select(Vision)
        .options(selectinload(Vision.tasks))
        .where(
            Vision.user_id == user_id,
            Vision.deleted_at.is_(None),
            Vision.id.in_(vision_ids),
        )
    )
    rows = await db.execute(stmt)
    visions = rows.scalars().all()
    vision_map = {vision.id: vision for vision in visions}
    missing = [str(vid) for vid in vision_ids if vid not in vision_map]
    if missing:
        raise VisionNotFoundError(f"Visions not found: {', '.join(missing)}")

    user_rate_cache = await get_user_experience_rate(db, user_id=user_id)
    ordered: List[Vision] = []
    for item in updates:
        vision = vision_map[item.id]
        ordered.append(vision)
        if item.experience_rate_per_hour is None:
            vision.experience_rate_per_hour = None
            effective_rate = await resolve_experience_rate_for_vision(
                db,
                user_id=user_id,
                vision=vision,
                user_rate_cache=user_rate_cache,
            )
        else:
            normalized = _normalize_experience_rate(item.experience_rate_per_hour)
            if normalized is None:
                raise InvalidVisionExperienceRateError(
                    f"Experience rate must be between 1 and {VISION_EXPERIENCE_RATE_MAX}"
                )
            vision.experience_rate_per_hour = normalized
            effective_rate = normalized

        _apply_effective_experience_rate(vision, effective_rate)
        vision.sync_experience_with_actual_effort(
            experience_rate_per_hour=effective_rate
        )

    await commit_safely(db)
    for vision in ordered:
        await db.refresh(vision)
    await _attach_persons(db, visions=ordered, user_id=user_id)
    await _annotate_total_effort(db, visions=ordered, user_id=user_id)
    return ordered


async def update_vision(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    vision_id: UUID,
    update_in: VisionUpdate,
) -> Optional[Vision]:
    vision = await _load_single_vision(
        db, user_id=user_id, vision_id=vision_id, with_tasks=True
    )
    if vision is None:
        return None

    payload = update_in.model_dump(exclude_unset=True)
    raw_person_ids = payload.pop("person_ids", None)

    if "status" in payload and payload["status"] not in VISION_ALLOWED_STATUSES:
        raise InvalidVisionStatusError(
            f"Status must be one of: {', '.join(sorted(VISION_ALLOWED_STATUSES))}"
        )

    if "name" in payload and payload["name"] != vision.name:
        stmt = (
            select(Vision.id)
            .where(
                Vision.user_id == user_id,
                Vision.deleted_at.is_(None),
                Vision.name == payload["name"],
                Vision.id != vision_id,
            )
            .limit(1)
        )
        conflict = (await db.execute(stmt)).scalar_one_or_none()
        if conflict:
            raise VisionAlreadyExistsError(
                f"A vision with name '{payload['name']}' already exists"
            )

    for field, value in payload.items():
        setattr(vision, field, value)

    if raw_person_ids is not None:
        person_ids = _coerce_uuid_list(raw_person_ids)
        await _ensure_person_ids_exist(db, user_id=user_id, person_ids=person_ids)
        await set_links(
            db,
            source_model=ModelName.Vision,
            source_id=vision.id,
            target_model=ModelName.Person,
            target_ids=person_ids,
            link_type=LinkType.INVOLVES,
            replace=True,
            user_id=user_id,
        )

    await commit_safely(db)
    await db.refresh(vision)
    await _attach_persons(db, visions=[vision], user_id=user_id)
    await _annotate_total_effort(db, visions=[vision], user_id=user_id)
    return vision


async def delete_vision(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    vision_id: UUID,
    hard_delete: bool = False,
) -> bool:
    vision = await _load_single_vision(db, user_id=user_id, vision_id=vision_id)
    if vision is None:
        return False

    if hard_delete:
        await db.delete(vision)
    else:
        vision.soft_delete()

    await commit_safely(db)
    return True


async def add_experience_to_vision(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    vision_id: UUID,
    experience_data: VisionExperienceUpdate,
) -> Optional[Vision]:
    vision = await _load_single_vision(db, user_id=user_id, vision_id=vision_id)
    if vision is None:
        return None

    if vision.status != "active":
        raise InvalidVisionStatusError("Can only add experience to active visions")

    effective_rate = await resolve_experience_rate_for_vision(
        db, user_id=user_id, vision=vision
    )
    _apply_effective_experience_rate(vision, effective_rate)
    vision.add_experience(experience_data.experience_points)

    await commit_safely(db)
    await db.refresh(vision)
    await _attach_persons(db, visions=[vision], user_id=user_id)
    await _annotate_total_effort(db, visions=[vision], user_id=user_id)
    return vision


async def sync_vision_experience(
    db: AsyncSession, *, user_id: Union[UUID, Column], vision_id: UUID
) -> Optional[Vision]:
    vision = await _load_single_vision(
        db, user_id=user_id, vision_id=vision_id, with_tasks=True
    )
    if vision is None:
        return None

    effective_rate = await resolve_experience_rate_for_vision(
        db, user_id=user_id, vision=vision
    )
    _apply_effective_experience_rate(vision, effective_rate)
    tasks = list(getattr(vision, "tasks", []) or [])
    vision.sync_experience_with_actual_effort(
        experience_rate_per_hour=effective_rate,
        tasks=tasks,
    )

    await commit_safely(db)
    await db.refresh(vision)
    await _attach_persons(db, visions=[vision], user_id=user_id)
    await _annotate_total_effort(db, visions=[vision], user_id=user_id)
    return vision


async def harvest_vision(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    vision_id: UUID,
    harvest_data: VisionHarvestRequest,
) -> Optional[Vision]:
    vision = await _load_single_vision(db, user_id=user_id, vision_id=vision_id)
    if vision is None:
        return None

    if not vision.can_harvest():
        raise VisionNotReadyForHarvestError(
            "Vision is not ready for harvest (must be at final stage and active)"
        )

    effective_rate = await resolve_experience_rate_for_vision(
        db, user_id=user_id, vision=vision
    )
    _apply_effective_experience_rate(vision, effective_rate)
    vision.harvest()

    await commit_safely(db)
    await db.refresh(vision)
    await _attach_persons(db, visions=[vision], user_id=user_id)
    await _annotate_total_effort(db, visions=[vision], user_id=user_id)
    return vision


async def get_vision_stats(
    db: AsyncSession, *, user_id: Union[UUID, Column], vision_id: UUID
) -> Optional[VisionStatsResponse]:
    vision = await _load_single_vision(db, user_id=user_id, vision_id=vision_id)
    if vision is None:
        return None

    tasks_stmt = select(Task).where(
        Task.user_id == user_id,
        Task.vision_id == vision_id,
        Task.deleted_at.is_(None),
    )
    rows = await db.execute(tasks_stmt)
    tasks = rows.scalars().all()

    total_tasks = len(tasks)
    completed_tasks = len([task for task in tasks if task.status == "done"])
    in_progress_tasks = len([task for task in tasks if task.status == "in_progress"])
    todo_tasks = len([task for task in tasks if task.status == "todo"])

    completion_percentage = completed_tasks / total_tasks if total_tasks > 0 else 0.0
    total_estimated_effort = sum(
        task.estimated_effort or 0 for task in tasks if task.estimated_effort
    )
    root_tasks = [task for task in tasks if task.parent_task_id is None]
    total_actual_effort = sum((task.actual_effort_total or 0) for task in root_tasks)

    return VisionStatsResponse(
        total_tasks=total_tasks,
        completed_tasks=completed_tasks,
        in_progress_tasks=in_progress_tasks,
        todo_tasks=todo_tasks,
        completion_percentage=completion_percentage,
        total_estimated_effort=total_estimated_effort or None,
        total_actual_effort=total_actual_effort or None,
    )


__all__ = [
    "VisionServiceError",
    "VisionAlreadyExistsError",
    "VisionNotReadyForHarvestError",
    "InvalidVisionStatusError",
    "InvalidVisionExperienceRateError",
    "VisionNotFoundError",
    "get_vision_with_tasks",
    "create_vision",
    "delete_vision",
    "get_user_experience_rate",
    "get_vision",
    "get_vision_stats",
    "list_visions",
    "list_visions_with_total",
    "update_all_vision_experience_rates",
    "bulk_update_vision_experience_rates",
    "add_experience_to_vision",
    "sync_vision_experience",
    "harvest_vision",
    "resolve_experience_rate_for_vision",
    "update_vision",
]
