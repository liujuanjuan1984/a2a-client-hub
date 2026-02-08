"""Async implementations for the dimension service layer."""

from __future__ import annotations

import time
from threading import RLock
from typing import Any, List, Optional, Sequence, Union
from uuid import UUID

from sqlalchemy import Column, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.dimension import Dimension
from app.db.models.user_preference import UserPreference
from app.db.transaction import commit_safely
from app.handlers import user_preferences as user_preferences_service
from app.schemas.dimension import DimensionCreate, DimensionUpdate

logger = get_logger(__name__)

PreferenceUser = Union[UUID, Column]

_DIMENSION_ORDER_CACHE_TTL_SECONDS = 120.0
_dimension_order_cache: dict[UUID, tuple[float, List[str]]] = {}
_dimension_order_cache_lock = RLock()


class DimensionAlreadyExistsError(Exception):
    """Raised when a dimension with the same name already exists for the user."""


def _coerce_dimension_order(value: Optional[Sequence[object]]) -> List[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [str(item) for item in value if item is not None]


def _get_cached_dimension_order(user_id: UUID) -> Optional[List[str]]:
    now = time.monotonic()
    with _dimension_order_cache_lock:
        cached = _dimension_order_cache.get(user_id)
        if not cached:
            return None
        expires_at, value = cached
        if expires_at <= now:
            _dimension_order_cache.pop(user_id, None)
            return None
        return list(value)


def _set_cached_dimension_order(user_id: UUID, order: Sequence[str]) -> None:
    with _dimension_order_cache_lock:
        _dimension_order_cache[user_id] = (
            time.monotonic() + _DIMENSION_ORDER_CACHE_TTL_SECONDS,
            list(order),
        )


def _clear_cached_dimension_order(user_id: UUID) -> None:
    with _dimension_order_cache_lock:
        _dimension_order_cache.pop(user_id, None)


async def _append_dimension_to_order(
    db: AsyncSession, *, user_id: PreferenceUser, dimension_id: UUID
) -> None:
    key = "dashboard.dimension_order"
    preference = await user_preferences_service.get_preference_by_key(
        db, user_id=user_id, key=key
    )
    if preference is None:
        preference = await user_preferences_service.create_default_preference(
            db, user_id=user_id, key=key
        )

    current_order: List[str] = []
    if preference:
        current_order = _coerce_dimension_order(preference.value)

    dimension_uuid = str(dimension_id)
    if dimension_uuid in current_order:
        return

    next_order = current_order + [dimension_uuid]
    preference = await user_preferences_service.set_preference_value(
        db, user_id=user_id, key=key, value=next_order, module="general"
    )
    _set_cached_dimension_order(user_id, _coerce_dimension_order(preference.value))


async def create_dimension(
    db: AsyncSession, *, user_id: PreferenceUser, dimension_in: DimensionCreate
) -> Dimension:
    stmt = (
        select(Dimension)
        .where(Dimension.name == dimension_in.name, Dimension.user_id == user_id)
        .limit(1)
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        raise DimensionAlreadyExistsError(
            f"Dimension with name '{dimension_in.name}' already exists"
        )

    db_dimension = Dimension(**dimension_in.model_dump(), user_id=user_id)
    db.add(db_dimension)
    await commit_safely(db)
    await db.refresh(db_dimension)

    try:
        await _append_dimension_to_order(
            db=db, user_id=user_id, dimension_id=db_dimension.id
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to append dimension %s to order: %s", db_dimension.id, exc
        )

    return db_dimension


async def list_dimensions(
    db: AsyncSession,
    *,
    user_id: PreferenceUser,
    skip: int = 0,
    limit: int = 100,
    include_inactive: bool = False,
) -> List[Dimension]:
    stmt = _build_dimensions_query(
        user_id=user_id,
        include_inactive=include_inactive,
    )
    stmt = stmt.order_by(Dimension.display_order, Dimension.name)
    stmt = stmt.offset(skip).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()


def _build_dimensions_query(*, user_id: PreferenceUser, include_inactive: bool) -> Any:
    stmt = select(Dimension).where(Dimension.user_id == user_id)
    if not include_inactive:
        stmt = stmt.where(Dimension.is_active.is_(True))
    return stmt


async def list_dimensions_with_total(
    db: AsyncSession,
    *,
    user_id: PreferenceUser,
    skip: int = 0,
    limit: int = 100,
    include_inactive: bool = False,
) -> tuple[List[Dimension], int]:
    stmt = _build_dimensions_query(
        user_id=user_id,
        include_inactive=include_inactive,
    )
    count_stmt = select(func.count()).select_from(stmt.subquery())
    stmt = stmt.order_by(Dimension.display_order, Dimension.name)
    stmt = stmt.offset(skip).limit(limit)
    result = await db.execute(stmt)
    total = await db.scalar(count_stmt)
    return result.scalars().all(), int(total or 0)


async def get_dimension(
    db: AsyncSession, *, user_id: PreferenceUser, dimension_id: UUID
) -> Optional[Dimension]:
    stmt = (
        select(Dimension)
        .where(Dimension.id == dimension_id, Dimension.user_id == user_id)
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def update_dimension(
    db: AsyncSession,
    *,
    user_id: PreferenceUser,
    dimension_id: UUID,
    update_in: DimensionUpdate,
) -> Optional[Dimension]:
    stmt = (
        select(Dimension)
        .where(Dimension.id == dimension_id, Dimension.user_id == user_id)
        .limit(1)
    )
    db_dimension = (await db.execute(stmt)).scalar_one_or_none()
    if not db_dimension:
        return None

    if update_in.name and update_in.name != db_dimension.name:
        conflict_stmt = (
            select(Dimension)
            .where(
                Dimension.name == update_in.name,
                Dimension.id != dimension_id,
                Dimension.user_id == user_id,
            )
            .limit(1)
        )
        exists = (await db.execute(conflict_stmt)).scalar_one_or_none()
        if exists:
            raise DimensionAlreadyExistsError(
                f"Dimension with name '{update_in.name}' already exists"
            )

    update_data = update_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_dimension, field, value)

    await commit_safely(db)
    await db.refresh(db_dimension)
    return db_dimension


async def soft_delete_dimension(
    db: AsyncSession, *, user_id: PreferenceUser, dimension_id: UUID
) -> bool:
    stmt = (
        select(Dimension)
        .where(Dimension.id == dimension_id, Dimension.user_id == user_id)
        .limit(1)
    )
    db_dimension = (await db.execute(stmt)).scalar_one_or_none()
    if not db_dimension:
        return False

    db_dimension.is_active = False
    await commit_safely(db)

    try:
        key = "dashboard.dimension_order"
        preference = await user_preferences_service.get_preference_by_key(
            db, user_id=user_id, key=key
        )
        if preference:
            existing_order = _coerce_dimension_order(preference.value)
            dimension_uuid = str(db_dimension.id)
            next_order = [item for item in existing_order if item != dimension_uuid]
            if next_order != existing_order:
                preference = await user_preferences_service.set_preference_value(
                    db, user_id=user_id, key=key, value=next_order, module="general"
                )
                _set_cached_dimension_order(
                    user_id, _coerce_dimension_order(preference.value)
                )
    except Exception as exc:  # noqa: BLE001
        _clear_cached_dimension_order(user_id)
        logger.warning(
            "Failed to remove dimension %s from order: %s", dimension_id, exc
        )

    return True


async def activate_dimension(
    db: AsyncSession, *, user_id: PreferenceUser, dimension_id: UUID
) -> Optional[Dimension]:
    stmt = (
        select(Dimension)
        .where(Dimension.id == dimension_id, Dimension.user_id == user_id)
        .limit(1)
    )
    db_dimension = (await db.execute(stmt)).scalar_one_or_none()
    if not db_dimension:
        return None

    db_dimension.is_active = True
    await commit_safely(db)
    await db.refresh(db_dimension)

    try:
        await _append_dimension_to_order(
            db=db, user_id=user_id, dimension_id=dimension_id
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to ensure dimension %s in order: %s", dimension_id, exc)

    return db_dimension


async def get_dimension_order(
    db: AsyncSession, *, user_id: UUID
) -> Optional[UserPreference]:
    key = "dashboard.dimension_order"
    preference = await user_preferences_service.get_preference_by_key(
        db, user_id=user_id, key=key
    )
    if preference is None:
        preference = await user_preferences_service.create_default_preference(
            db, user_id=user_id, key=key
        )
        if preference is None:
            return None
        order_value = _coerce_dimension_order(preference.value)
        _set_cached_dimension_order(user_id, order_value)
        db.expunge(preference)
        preference.value = order_value
        return preference

    cached_value = _get_cached_dimension_order(user_id)
    if cached_value is not None:
        db.expunge(preference)
        preference.value = cached_value
        return preference

    normalized_value = await user_preferences_service.normalize_preference_value(
        db,
        user_id=user_id,
        key=key,
        value=preference.value,
    )
    normalized_list = _coerce_dimension_order(normalized_value)
    order_value = _coerce_dimension_order(preference.value)
    final_value = normalized_list if normalized_list != order_value else order_value
    _set_cached_dimension_order(user_id, final_value)
    db.expunge(preference)
    preference.value = final_value
    return preference


async def set_dimension_order(
    db: AsyncSession, *, user_id: PreferenceUser, dimension_order: List[str]
) -> UserPreference:
    key = "dashboard.dimension_order"
    preference = await user_preferences_service.set_preference_value(
        db, user_id=user_id, key=key, value=dimension_order, module="general"
    )
    _set_cached_dimension_order(user_id, _coerce_dimension_order(preference.value))
    return preference


async def reset_dimension_order(db: AsyncSession, *, user_id: UUID) -> None:
    key = "dashboard.dimension_order"
    preference = await user_preferences_service.get_preference_by_key(
        db, user_id=user_id, key=key
    )
    if preference:
        preference.value = []
        await commit_safely(db)
        _set_cached_dimension_order(user_id, [])
        return
    preference = await user_preferences_service.create_default_preference(
        db, user_id=user_id, key=key
    )
    if preference:
        _set_cached_dimension_order(user_id, _coerce_dimension_order(preference.value))


__all__ = [
    "activate_dimension",
    "create_dimension",
    "DimensionAlreadyExistsError",
    "get_dimension",
    "get_dimension_order",
    "list_dimensions",
    "list_dimensions_with_total",
    "reset_dimension_order",
    "set_dimension_order",
    "soft_delete_dimension",
    "update_dimension",
]
