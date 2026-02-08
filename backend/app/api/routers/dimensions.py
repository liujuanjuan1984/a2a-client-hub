"""
Dimension API routes

This module contains all API routes for dimension management.
"""

from typing import List
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.routing import StrictAPIRouter
from app.db.models.user import User
from app.handlers import dimensions as dimension_service
from app.handlers.dimensions import DimensionAlreadyExistsError
from app.schemas.dimension import (
    DimensionCreate,
    DimensionListResponse,
    DimensionResponse,
    DimensionUpdate,
)
from app.schemas.user_preference import UserPreferenceResponse

router = StrictAPIRouter(
    prefix="/dimensions",
    tags=["dimensions"],
    responses={404: {"description": "Not found"}},
    dependencies=[Depends(get_current_user)],
)


@router.get("/", response_model=DimensionListResponse)
async def get_dimensions(
    page: int = 1,
    size: int = 100,
    include_inactive: bool = False,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> DimensionListResponse:
    """Get all dimensions via service layer."""
    offset = (page - 1) * size
    dims, total = await dimension_service.list_dimensions_with_total(
        db,
        user_id=current_user.id,
        skip=offset,
        limit=size,
        include_inactive=include_inactive,
    )
    items = [DimensionResponse.model_validate(d) for d in dims]
    pages = (total + size - 1) // size if size else 0
    return DimensionListResponse(
        items=items,
        pagination={
            "page": page,
            "size": size,
            "total": total,
            "pages": pages,
        },
        meta={
            "include_inactive": include_inactive,
        },
    )


@router.get("/order", response_model=UserPreferenceResponse)
async def get_dimension_order(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> UserPreferenceResponse:
    """Get dimension order via service layer. Returns full UserPreference object."""
    pref = await dimension_service.get_dimension_order(db, user_id=current_user.id)
    if pref is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create default dimension order preference",
        )
    return UserPreferenceResponse.model_validate(pref)


@router.put("/order", response_model=UserPreferenceResponse)
async def set_dimension_order(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    dimension_order: List[str],
) -> UserPreferenceResponse:
    """Set dimension order via service layer. Returns full UserPreference object."""
    pref = await dimension_service.set_dimension_order(
        db,
        user_id=current_user.id,
        dimension_order=dimension_order,
    )
    return UserPreferenceResponse.model_validate(pref)


@router.delete("/order", status_code=status.HTTP_204_NO_CONTENT)
async def reset_dimension_order(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """Reset dimension order via service layer."""
    await dimension_service.reset_dimension_order(db, user_id=current_user.id)


@router.get("/{dimension_id}", response_model=DimensionResponse)
async def get_dimension(
    dimension_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> DimensionResponse:
    """
    Get a specific dimension by ID

    Args:
        dimension_id: ID of the dimension to retrieve
        db: Database session

    Returns:
        Dimension data

    Raises:
        HTTPException: If dimension is not found
    """
    dimension = await dimension_service.get_dimension(
        db,
        user_id=current_user.id,
        dimension_id=dimension_id,
    )
    if not dimension:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dimension with id {dimension_id} not found",
        )
    return DimensionResponse.model_validate(dimension)


@router.post("/", response_model=DimensionResponse, status_code=status.HTTP_201_CREATED)
async def create_dimension(
    dimension: DimensionCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> DimensionResponse:
    """
    Create a new dimension by delegating to the service layer.
    """
    try:
        db_dimension = await dimension_service.create_dimension(
            db,
            user_id=current_user.id,
            dimension_in=dimension,
        )
        return DimensionResponse.model_validate(db_dimension)
    except DimensionAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred.",
        )


@router.put("/{dimension_id}", response_model=DimensionResponse)
async def update_dimension(
    dimension_id: UUID,
    dimension: DimensionUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> DimensionResponse:
    """
    Update an existing dimension

    Args:
        dimension_id: ID of the dimension to update
        dimension: Updated dimension data
        db: Database session

    Returns:
        Updated dimension data

    Raises:
        HTTPException: If dimension is not found or name conflict exists
    """
    try:
        updated = await dimension_service.update_dimension(
            db,
            user_id=current_user.id,
            dimension_id=dimension_id,
            update_in=dimension,
        )
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Dimension with id {dimension_id} not found",
            )
        return DimensionResponse.model_validate(updated)
    except DimensionAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.delete("/{dimension_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dimension(
    dimension_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """
    Delete a dimension (soft delete by setting is_active=False)

    Args:
        dimension_id: ID of the dimension to delete
        db: Database session

    Raises:
        HTTPException: If dimension is not found
    """
    ok = await dimension_service.soft_delete_dimension(
        db,
        user_id=current_user.id,
        dimension_id=dimension_id,
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dimension with id {dimension_id} not found",
        )


@router.post("/{dimension_id}/activate", response_model=DimensionResponse)
async def activate_dimension(
    dimension_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> DimensionResponse:
    """
    Reactivate a dimension

    Args:
        dimension_id: ID of the dimension to activate
        db: Database session

    Returns:
        Activated dimension data

    Raises:
        HTTPException: If dimension is not found
    """
    db_dimension = await dimension_service.activate_dimension(
        db,
        user_id=current_user.id,
        dimension_id=dimension_id,
    )
    if not db_dimension:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dimension with id {dimension_id} not found",
        )
    return db_dimension
