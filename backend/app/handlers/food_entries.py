"""
Food Entries service layer

此模块现在提供默认的异步实现，直接操作 ``AsyncSession``。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Optional, Union
from uuid import UUID

from sqlalchemy import Column, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.food import Food
from app.db.models.food_entry import FoodEntry, MealType
from app.db.transaction import commit_safely
from app.schemas.food_entry import (
    DailyNutritionSummary,
    FoodEntryCreate,
    FoodEntryUpdate,
)


class FoodEntryNotFoundError(Exception):
    """Raised when a food entry is not found."""


class InvalidMealTypeError(Exception):
    """Raised when an invalid meal type is provided."""


class InvalidDateError(Exception):
    """Raised when an invalid date format is provided."""


def _active_food_filter() -> list:
    return [Food.deleted_at.is_(None)]


def _active_entry_filter() -> list:
    return [FoodEntry.deleted_at.is_(None)]


def _calculate_nutrition(food: Food, portion_size_g: float) -> dict:
    """Calculate nutritional values for a given portion size."""
    if not food.calories_per_100g:
        return {}

    ratio = portion_size_g / 100.0
    return {
        "calories": food.calories_per_100g * ratio if food.calories_per_100g else None,
        "protein": food.protein_per_100g * ratio if food.protein_per_100g else None,
        "carbs": food.carbs_per_100g * ratio if food.carbs_per_100g else None,
        "fat": food.fat_per_100g * ratio if food.fat_per_100g else None,
        "fiber": food.fiber_per_100g * ratio if food.fiber_per_100g else None,
        "sugar": food.sugar_per_100g * ratio if food.sugar_per_100g else None,
        "sodium": food.sodium_per_100g * ratio if food.sodium_per_100g else None,
    }


def normalize_consumed_at(value: datetime) -> datetime:
    """Normalize timezone-aware datetimes to naive UTC for storage."""
    if value is None:
        return value
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _build_food_entries_query(
    *,
    user_id: Union[UUID, Column],
    start_date: Optional[str],
    end_date: Optional[str],
    meal_type: Optional[str],
) -> Any:
    stmt = (
        select(FoodEntry)
        .options(selectinload(FoodEntry.food))
        .where(FoodEntry.user_id == user_id, *_active_entry_filter())
    )
    if start_date:
        stmt = stmt.where(FoodEntry.date >= start_date)
    if end_date:
        stmt = stmt.where(FoodEntry.date <= end_date)
    if meal_type:
        try:
            stmt = stmt.where(FoodEntry.meal_type == MealType(meal_type))
        except ValueError as exc:
            raise InvalidMealTypeError(
                "Invalid meal type. Must be one of: "
                f"{', '.join([t.value for t in MealType])}"
            ) from exc
    return stmt


async def _get_food_for_user(
    db: AsyncSession, *, user_id: Union[UUID, Column], food_id: UUID
) -> Food:
    stmt = select(Food).where(Food.id == food_id, *_active_food_filter()).limit(1)
    food = (await db.execute(stmt)).scalar_one_or_none()
    if not food or (not food.is_common and getattr(food, "user_id", None) != user_id):
        raise FoodEntryNotFoundError("Food not found")
    return food


async def get_food_entry(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    entry_id: UUID,
) -> FoodEntry:
    """Get a single food entry by id."""
    stmt = (
        select(FoodEntry)
        .options(selectinload(FoodEntry.food))
        .where(
            FoodEntry.id == entry_id,
            FoodEntry.user_id == user_id,
            *_active_entry_filter(),
        )
        .limit(1)
    )
    entry = (await db.execute(stmt)).scalar_one_or_none()
    if not entry:
        raise FoodEntryNotFoundError("Food entry not found")
    return entry


async def create_food_entry(
    db: AsyncSession, *, user_id: Union[UUID, Column], entry_in: FoodEntryCreate
) -> FoodEntry:
    """Create a new food entry."""
    food = await _get_food_for_user(db, user_id=user_id, food_id=entry_in.food_id)
    nutrition = _calculate_nutrition(food, entry_in.portion_size_g)
    entry_data = entry_in.model_dump()
    entry_data["consumed_at"] = normalize_consumed_at(entry_data["consumed_at"])
    entry = FoodEntry(**entry_data, **nutrition, user_id=user_id)
    db.add(entry)
    await commit_safely(db)
    # Ensure the related food relationship is populated for response serialization
    await db.refresh(entry, attribute_names=[FoodEntry.food.key])
    return entry


async def list_food_entries(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    meal_type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[FoodEntry]:
    """List food entries with optional filtering."""
    stmt = _build_food_entries_query(
        user_id=user_id,
        start_date=start_date,
        end_date=end_date,
        meal_type=meal_type,
    )
    stmt = stmt.order_by(FoodEntry.consumed_at.desc()).offset(offset).limit(limit)
    return (await db.execute(stmt)).scalars().all()


async def list_food_entries_with_total(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    meal_type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[List[FoodEntry], int]:
    stmt = _build_food_entries_query(
        user_id=user_id,
        start_date=start_date,
        end_date=end_date,
        meal_type=meal_type,
    )
    count_stmt = select(func.count()).select_from(stmt.subquery())
    stmt = stmt.order_by(FoodEntry.consumed_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    total = await db.scalar(count_stmt)
    return result.scalars().all(), int(total or 0)


async def update_food_entry(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    entry_id: UUID,
    update_in: FoodEntryUpdate,
) -> FoodEntry:
    """Update a food entry."""
    entry = await get_food_entry(db, user_id=user_id, entry_id=entry_id)
    update_data = update_in.model_dump(exclude_unset=True)

    if "consumed_at" in update_data:
        update_data["consumed_at"] = normalize_consumed_at(update_data["consumed_at"])

    if "food_id" in update_data or "portion_size_g" in update_data:
        food_id = update_data.get("food_id", entry.food_id)
        portion_size = update_data.get("portion_size_g", entry.portion_size_g)
        food = await _get_food_for_user(db, user_id=user_id, food_id=food_id)
        update_data.update(_calculate_nutrition(food, portion_size))

    for field, value in update_data.items():
        setattr(entry, field, value)

    await commit_safely(db)
    await db.refresh(entry)
    return entry


async def delete_food_entry(
    db: AsyncSession,
    *,
    user_id: Union[UUID, Column],
    entry_id: UUID,
    hard_delete: bool = False,
) -> None:
    """Delete a food entry."""
    entry = await get_food_entry(db, user_id=user_id, entry_id=entry_id)
    if hard_delete:
        await db.delete(entry)
    else:
        entry.soft_delete()
    await commit_safely(db)


async def get_daily_nutrition_summary(
    db: AsyncSession, *, user_id: Union[UUID, Column], date_str: str
) -> DailyNutritionSummary:
    """Get daily nutrition summary for a specific date."""
    try:
        datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError as exc:
        raise InvalidDateError("Date must be in YYYY-MM-DD format") from exc

    stmt = select(FoodEntry).where(
        FoodEntry.user_id == user_id,
        FoodEntry.date == date_str,
        *_active_entry_filter(),
    )
    entries = (await db.execute(stmt)).scalars().all()

    total_calories = sum(entry.calories or 0 for entry in entries)
    total_protein = sum(entry.protein or 0 for entry in entries)
    total_carbs = sum(entry.carbs or 0 for entry in entries)
    total_fat = sum(entry.fat or 0 for entry in entries)
    total_fiber = sum(entry.fiber or 0 for entry in entries)
    total_sugar = sum(entry.sugar or 0 for entry in entries)
    total_sodium = sum(entry.sodium or 0 for entry in entries)

    return DailyNutritionSummary(
        date=date_str,
        total_calories=total_calories,
        total_protein=total_protein,
        total_carbs=total_carbs,
        total_fat=total_fat,
        total_fiber=total_fiber,
        total_sugar=total_sugar,
        total_sodium=total_sodium,
        entry_count=len(entries),
    )
