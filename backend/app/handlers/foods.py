"""Async food service layer."""

from __future__ import annotations

from typing import Any, List, Optional, Union
from uuid import UUID

from sqlalchemy import Column, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.food import Food
from app.db.transaction import commit_safely
from app.schemas.food import FoodCreate, FoodUpdate


class FoodNotFoundError(Exception):
    """Raised when a food is not found."""


class FoodAlreadyExistsError(Exception):
    """Raised when a food with the same name already exists for the user."""


class FoodPermissionDeniedError(Exception):
    """Raised when user doesn't have permission to access/modify a food."""


class FoodOperationNotAllowedError(Exception):
    """Raised when operation is not allowed (e.g., modifying common foods)."""


def _food_filters() -> list:
    return [Food.deleted_at.is_(None)]


def _build_foods_query(
    *,
    user_id: Union[UUID, Column],
    search: Optional[str],
    common_only: bool,
) -> Any:
    stmt = select(Food).where(*_food_filters())
    if common_only:
        stmt = stmt.where(Food.is_common.is_(True))
    else:
        stmt = stmt.where(or_(Food.is_common.is_(True), Food.user_id == user_id))
    if search:
        stmt = stmt.where(Food.name.ilike(f"%{search}%"))
    return stmt


async def _ensure_food_for_user(
    db: AsyncSession, *, user_id: Union[UUID, Column], food_id: UUID
) -> Food:
    stmt = select(Food).where(Food.id == food_id, *_food_filters()).limit(1)
    food = (await db.execute(stmt)).scalar_one_or_none()
    if not food:
        raise FoodNotFoundError("Food not found")
    if not food.is_common and getattr(food, "user_id", None) != user_id:
        raise FoodOperationNotAllowedError("Not authorized to modify this food item.")
    return food


async def create_food(
    db: AsyncSession, *, user_id: Union[UUID, Column], food_in: FoodCreate
) -> Food:
    stmt = (
        select(Food.id)
        .where(
            Food.user_id == user_id,
            Food.name == food_in.name,
            *_food_filters(),
        )
        .limit(1)
    )
    exists = await db.scalar(stmt)
    if exists:
        raise FoodAlreadyExistsError("You already have a food with this name")

    payload = food_in.model_dump()
    payload["user_id"] = user_id
    payload["is_common"] = payload.get("is_common", False)
    food = Food(**payload)
    db.add(food)
    await commit_safely(db)
    await db.refresh(food)
    return food


async def get_food(
    db: AsyncSession, *, user_id: Union[UUID, Column], food_id: UUID
) -> Optional[Food]:
    stmt = select(Food).where(Food.id == food_id, *_food_filters()).limit(1)
    food = (await db.execute(stmt)).scalar_one_or_none()
    if not food:
        return None
    if not food.is_common and getattr(food, "user_id", None) != user_id:
        raise FoodPermissionDeniedError("Not authorized to access this food item")
    return food


async def list_foods(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    search: Optional[str] = None,
    common_only: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> List[Food]:
    stmt = _build_foods_query(
        user_id=user_id,
        search=search,
        common_only=common_only,
    )
    stmt = stmt.order_by(Food.name.asc()).offset(offset).limit(limit)
    return (await db.execute(stmt)).scalars().all()


async def list_foods_with_total(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    search: Optional[str] = None,
    common_only: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> tuple[List[Food], int]:
    stmt = _build_foods_query(
        user_id=user_id,
        search=search,
        common_only=common_only,
    )
    count_stmt = select(func.count()).select_from(stmt.subquery())
    stmt = stmt.order_by(Food.name.asc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    total = await db.scalar(count_stmt)
    return result.scalars().all(), int(total or 0)


async def update_food(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    food_id: UUID,
    update_in: FoodUpdate,
) -> Food:
    food = await _ensure_food_for_user(db, user_id=user_id, food_id=food_id)

    update_data = update_in.model_dump(exclude_unset=True)
    if "name" in update_data and update_data["name"] != food.name:
        stmt = (
            select(Food.id)
            .where(
                Food.user_id == user_id,
                Food.name == update_data["name"],
                Food.id != food_id,
                *_food_filters(),
            )
            .limit(1)
        )
        exists = await db.scalar(stmt)
        if exists:
            raise FoodAlreadyExistsError("You already have a food with this name")

    for field, value in update_data.items():
        setattr(food, field, value)

    await commit_safely(db)
    await db.refresh(food)
    return food


async def delete_food(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    food_id: UUID,
) -> None:
    food = await _ensure_food_for_user(db, user_id=user_id, food_id=food_id)
    food.soft_delete()
    await commit_safely(db)


__all__ = [
    "FoodAlreadyExistsError",
    "FoodNotFoundError",
    "FoodOperationNotAllowedError",
    "FoodPermissionDeniedError",
    "create_food",
    "delete_food",
    "get_food",
    "list_foods",
    "list_foods_with_total",
    "update_food",
]
