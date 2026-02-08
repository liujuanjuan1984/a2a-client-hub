"""
Tags API Router

This module contains API endpoints for managing the unified tagging system.
Routers call into the service layer and map business exceptions to HTTP errors.

Architecture:
- This router handles all tag CRUD operations (create, read, update, delete)
- Entity-specific routers (persons, notes, etc.) handle tag associations
- Convenience endpoints are provided for common entity types

API Structure:
- /tags/ - General tag management
- /tags/person/ - Convenience endpoint for person tags
- /tags/note/ - Convenience endpoint for note tags
- /tags/{tag_id}/usage - Tag usage statistics
"""

from typing import List, Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.routing import StrictAPIRouter
from app.core.config import settings
from app.db.models.user import User
from app.handlers import tags as tags_service
from app.handlers.tags import TagAlreadyExistsError
from app.schemas.tag import (
    TagCategoryOption,
    TagCreate,
    TagListResponse,
    TagResponse,
    TagUpdate,
)

# Router definition
router = StrictAPIRouter(
    prefix="/tags",
    tags=["tags"],
    responses={404: {"description": "Not found"}},
    dependencies=[Depends(get_current_user)],
)
collection_router = StrictAPIRouter(tags=["tags"])
resource_router = StrictAPIRouter(prefix="/{tag_id:uuid}", tags=["tags"])


@collection_router.get("/", response_model=TagListResponse)
async def get_tags(
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(
        100, ge=1, le=1000, description="Page size / number of records to return"
    ),
    entity_type: Optional[str] = Query(
        None, description="Filter by entity type (e.g., 'person', 'note', 'task')"
    ),
    category: Optional[str] = Query(
        None, description="Filter by tag category (e.g., 'general', 'location')"
    ),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> TagListResponse:
    """
    Get all available tags with optional filtering

    Args:
        entity_type: Filter by entity type
        db: Database session

    Returns:
        List of tags matching the criteria
    """
    try:
        offset = (page - 1) * size
        tags, total = await tags_service.list_tags_with_total(
            db,
            user_id=current_user.id,
            entity_type=entity_type,
            category=category,
            limit=size,
            offset=offset,
        )
        pages = (total + size - 1) // size if size else 0
        return TagListResponse(
            items=tags,
            pagination={
                "page": page,
                "size": size,
                "total": total,
                "pages": pages,
            },
            meta={"entity_type": entity_type, "category": category},
        )
    except HTTPException as exc:
        raise exc
    except Exception:
        if settings.debug:
            raise
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@collection_router.get("/entity-types/", response_model=List[str])
def get_entity_types() -> List[str]:
    """
    Get all supported entity types for tags

    Returns:
        List of supported entity types
    """
    return tags_service.get_entity_types()


@collection_router.get("/categories/", response_model=List[TagCategoryOption])
def get_categories() -> List[TagCategoryOption]:
    """
    Get all supported tag categories

    Returns:
        List of supported tag categories with display labels
    """
    return tags_service.get_categories()


@collection_router.post(
    "/", response_model=TagResponse, status_code=status.HTTP_201_CREATED
)
async def create_tag(
    tag_data: TagCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> TagResponse:
    """
    Create a new tag or return existing one if it already exists

    Args:
        tag_data: Tag creation data
        db: Database session

    Returns:
        Created tag or existing tag if it already exists

    Note:
        This endpoint implements "upsert" behavior - if a tag with the same name
        and entity type already exists, it returns the existing tag instead of
        creating a duplicate or throwing an error.
    """
    try:
        tag = await tags_service.create_tag(
            db, user_id=current_user.id, tag_in=tag_data
        )
        return tag
    except HTTPException as exc:
        raise exc
    except Exception:
        if settings.debug:
            raise
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@resource_router.get("", response_model=TagResponse)
async def get_tag(
    tag_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> TagResponse:
    """
    Get a specific tag by ID

    Args:
        tag_id: Tag ID
        db: Database session

    Returns:
        Tag details

    Raises:
        HTTPException: If tag not found
    """
    try:
        tag = await tags_service.get_tag(db, user_id=current_user.id, tag_id=tag_id)
        if tag is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found"
            )
        return tag
    except HTTPException as exc:
        raise exc
    except Exception:
        if settings.debug:
            raise
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@resource_router.put("", response_model=TagResponse)
async def update_tag(
    tag_id: UUID,
    tag_data: TagUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> TagResponse:
    """
    Update a tag

    Args:
        tag_id: Tag ID
        tag_data: Updated tag data
        db: Database session

    Returns:
        Updated tag

    Raises:
        HTTPException: If tag not found or name conflicts
    """
    try:
        tag = await tags_service.update_tag(
            db,
            user_id=current_user.id,
            tag_id=tag_id,
            update_in=tag_data,
        )
        if tag is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found"
            )
        return tag
    except TagAlreadyExistsError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except HTTPException as exc:
        raise exc
    except Exception:
        if settings.debug:
            raise
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@resource_router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(
    tag_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete a tag."""
    try:
        success = await tags_service.delete_tag(
            db,
            user_id=current_user.id,
            tag_id=tag_id,
            hard_delete=False,
        )
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found"
            )
    except HTTPException as exc:
        raise exc
    except Exception:
        if settings.debug:
            raise
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@resource_router.get("/usage", response_model=dict)
async def get_tag_usage(
    tag_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Get usage statistics for a tag

    Args:
        tag_id: Tag ID
        db: Database session

    Returns:
        Usage statistics by entity type

    Raises:
        HTTPException: If tag not found
    """
    try:
        usage_stats = await tags_service.get_tag_usage(
            db, user_id=current_user.id, tag_id=tag_id
        )
        if usage_stats is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found"
            )
        return usage_stats
    except HTTPException as exc:
        raise exc
    except Exception:
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


router.include_router(collection_router)
router.include_router(resource_router)
