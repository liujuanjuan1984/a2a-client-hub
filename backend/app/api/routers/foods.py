"""
Foods API Router

This module contains all API endpoints for managing foods.
Routers call into the service layer and map business exceptions to HTTP errors.
"""

from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.routing import StrictAPIRouter
from app.db.models.user import User
from app.handlers import foods as food_service
from app.handlers.foods import (
    FoodAlreadyExistsError,
    FoodNotFoundError,
    FoodOperationNotAllowedError,
    FoodPermissionDeniedError,
)
from app.schemas.food import (
    FoodCreate,
    FoodListResponse,
    FoodResponse,
    FoodSummary,
    FoodUpdate,
)

router = StrictAPIRouter(
    prefix="/foods",
    tags=["foods"],
    responses={404: {"description": "Not found"}},
    dependencies=[Depends(get_current_user)],
)


@router.get("/", response_model=FoodListResponse)
async def get_foods(
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    search: Optional[str] = Query(None, description="Search food by name"),
    common_only: bool = Query(False, description="Show only common foods"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    size: int = Query(100, ge=1, le=1000, description="Number of foods per page"),
) -> FoodListResponse:
    """
    Get list of foods, including common foods and user's private foods.
    """
    try:
        offset = (page - 1) * size
        foods, total = await food_service.list_foods_with_total(
            db,
            user_id=current_user.id,
            search=search,
            common_only=common_only,
            limit=size,
            offset=offset,
        )

        items = [
            FoodSummary(
                id=food.id,
                name=food.name,
                is_common=food.is_common,
                calories_per_100g=food.calories_per_100g,
            )
            for food in foods
        ]
        pages = (total + size - 1) // size if size else 0
        return FoodListResponse(
            items=items,
            pagination={
                "page": page,
                "size": size,
                "total": total,
                "pages": pages,
            },
            meta={
                "search": search,
                "common_only": common_only,
            },
        )
    except Exception:
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.get("/{food_id}", response_model=FoodResponse)
async def get_food(
    food_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> FoodResponse:
    """
    Get a specific food by ID.
    Users can access common foods and their own private foods.
    """
    try:
        food = await food_service.get_food(db, user_id=current_user.id, food_id=food_id)
        if food is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Food not found"
            )
        return food
    except FoodPermissionDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        )
    except Exception:
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.post("/", response_model=FoodResponse, status_code=status.HTTP_201_CREATED)
async def create_food(
    food_data: FoodCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> FoodResponse:
    """
    Create a new private food item for the current user.
    """
    try:
        food = await food_service.create_food(
            db, user_id=current_user.id, food_in=food_data
        )
        return food
    except FoodAlreadyExistsError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception:
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.put("/{food_id}", response_model=FoodResponse)
async def update_food(
    food_id: UUID,
    food_data: FoodUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> FoodResponse:
    """
    Update an existing private food item. Common foods cannot be updated.
    """
    try:
        food = await food_service.update_food(
            db,
            user_id=current_user.id,
            food_id=food_id,
            update_in=food_data,
        )
        return food
    except FoodNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except FoodAlreadyExistsError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except FoodOperationNotAllowedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        )
    except Exception:
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.delete("/{food_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_food(
    food_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """
    Soft delete a private food item. Common foods cannot be deleted.
    """
    try:
        await food_service.delete_food(db, user_id=current_user.id, food_id=food_id)
    except FoodNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except FoodOperationNotAllowedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        )
    except Exception:
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")
