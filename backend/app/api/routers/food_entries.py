"""
Food Entries API Router

This module contains all API endpoints for managing food entries.
Routers call into the service layer and map business exceptions to HTTP errors.
"""

import logging
from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.routing import StrictAPIRouter
from app.db.models.user import User
from app.handlers import food_entries as food_entry_service
from app.handlers.food_entries import (
    FoodEntryNotFoundError,
    InvalidDateError,
    InvalidMealTypeError,
)
from app.schemas.food_entry import (
    DailyNutritionSummary,
    FoodEntryCreate,
    FoodEntryListResponse,
    FoodEntryResponse,
    FoodEntrySummary,
    FoodEntryUpdate,
)

router = StrictAPIRouter(
    prefix="/food-entries",
    tags=["food-entries"],
    responses={404: {"description": "Not found"}},
    dependencies=[Depends(get_current_user)],
)
collection_router = StrictAPIRouter(tags=["food-entries"])
resource_router = StrictAPIRouter(prefix="/{entry_id:uuid}", tags=["food-entries"])

logger = logging.getLogger(__name__)


@collection_router.get("/", response_model=FoodEntryListResponse)
async def get_food_entries(
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    meal_type: Optional[str] = Query(None, description="Filter by meal type"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    size: int = Query(100, ge=1, le=1000, description="Number of entries per page"),
) -> FoodEntryListResponse:
    """
    Get list of food entries with optional filtering and pagination
    """
    try:
        offset = (page - 1) * size
        entries, total = await food_entry_service.list_food_entries_with_total(
            db,
            user_id=current_user.id,
            start_date=start_date,
            end_date=end_date,
            meal_type=meal_type,
            limit=size,
            offset=offset,
        )

        items = [
            FoodEntrySummary(
                id=entry.id,
                date=entry.date,
                consumed_at=entry.consumed_at,
                meal_type=entry.meal_type.value,
                food_name=entry.food.name,
                portion_size_g=entry.portion_size_g,
                calories=entry.calories,
                notes=entry.notes,
            )
            for entry in entries
        ]
        pages = (total + size - 1) // size if size else 0
        return FoodEntryListResponse(
            items=items,
            pagination={
                "page": page,
                "size": size,
                "total": total,
                "pages": pages,
            },
            meta={
                "start_date": start_date,
                "end_date": end_date,
                "meal_type": meal_type,
            },
        )
    except InvalidMealTypeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception:
        logger.exception("Failed to list food entries")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@resource_router.get("", response_model=FoodEntryResponse)
async def get_food_entry(
    entry_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> FoodEntryResponse:
    """
    Get a specific food entry by ID
    """
    try:
        entry = await food_entry_service.get_food_entry(
            db,
            user_id=current_user.id,
            entry_id=entry_id,
        )
        return entry
    except FoodEntryNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception:
        logger.exception("Failed to fetch food entry %s", entry_id)
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@collection_router.post(
    "/", response_model=FoodEntryResponse, status_code=status.HTTP_201_CREATED
)
async def create_food_entry(
    entry_data: FoodEntryCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> FoodEntryResponse:
    """
    Create a new food entry
    """
    try:
        entry = await food_entry_service.create_food_entry(
            db,
            user_id=current_user.id,
            entry_in=entry_data,
        )
        return entry
    except FoodEntryNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception:
        logger.exception("Failed to create food entry for user %s", current_user.id)
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@resource_router.put("", response_model=FoodEntryResponse)
async def update_food_entry(
    entry_id: UUID,
    entry_data: FoodEntryUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> FoodEntryResponse:
    """
    Update an existing food entry
    """
    try:
        entry = await food_entry_service.update_food_entry(
            db,
            user_id=current_user.id,
            entry_id=entry_id,
            update_in=entry_data,
        )
        return entry
    except FoodEntryNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception:
        logger.exception("Failed to update food entry %s", entry_id)
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@resource_router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_food_entry(
    entry_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """
    Soft delete a food entry
    """
    try:
        await food_entry_service.delete_food_entry(
            db,
            user_id=current_user.id,
            entry_id=entry_id,
        )
        return None
    except FoodEntryNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception:
        logger.exception("Failed to delete food entry %s", entry_id)
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@collection_router.get(
    "/daily-summary/{date_str}", response_model=DailyNutritionSummary
)
async def get_daily_nutrition_summary(
    date_str: str,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get daily nutrition summary for a specific date
    """
    try:
        summary = await food_entry_service.get_daily_nutrition_summary(
            db,
            user_id=current_user.id,
            date_str=date_str,
        )
        return summary
    except InvalidDateError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception:
        logger.exception("Failed to compute daily nutrition summary for %s", date_str)
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


router.include_router(collection_router)
router.include_router(resource_router)
