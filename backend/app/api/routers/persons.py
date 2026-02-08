"""
Person API Router

This module contains all API endpoints for managing persons.
Routers call into the service layer and map business exceptions to HTTP errors.
"""

from typing import Any, Dict, Literal, Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.routing import StrictAPIRouter
from app.db.models.user import User
from app.handlers import persons as person_service
from app.handlers.persons import (
    AnniversaryNotFoundError,
    PersonAlreadyExistsError,
    PersonNotFoundError,
    TagNotFoundError,
)
from app.schemas.person import (
    AnniversaryCreate,
    AnniversaryListResponse,
    AnniversaryResponse,
    AnniversaryUpdate,
    PersonActivitiesResponse,
    PersonCreate,
    PersonDetailListResponse,
    PersonListResponse,
    PersonResponse,
    PersonTagSearchRequest,
    PersonUpdate,
)
from app.utils.person_utils import convert_persons_to_summary

router = StrictAPIRouter(
    prefix="/persons",
    tags=["persons"],
    responses={404: {"description": "Not found"}},
    dependencies=[Depends(get_current_user)],
)
collection_router = StrictAPIRouter(tags=["persons"])
resource_router = StrictAPIRouter(prefix="/{person_id:uuid}", tags=["persons"])


@collection_router.get("/", response_model=PersonListResponse)
async def get_persons(
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(
        100, ge=1, le=1000, description="Page size / number of records to return"
    ),
    tag_filter: Optional[str] = Query(None, description="Filter by tag name"),
    tag_id: Optional[UUID] = Query(None, description="Filter by tag ID"),
    search: Optional[str] = Query(None, description="Search in name and nicknames"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> PersonListResponse:
    """
    Get all persons with optional filtering and search

    Args:
        page: Page number (1-indexed)
        size: Maximum number of records to return
        tag_filter: Filter by tag name
        search: Search query for name and nicknames
        db: Database session

    Returns:
        List of persons with summary information
    """
    try:
        offset = (page - 1) * size
        persons, total = await person_service.list_persons(
            db,
            user_id=current_user.id,
            skip=offset,
            limit=size,
            tag_filter=tag_filter,
            tag_id=tag_id,
            search=search,
        )

        # Convert to summary response using shared utility
        person_summaries = convert_persons_to_summary(persons)
        pages = (total + size - 1) // size if size else 0
        return PersonListResponse(
            items=person_summaries,
            pagination={
                "page": page,
                "size": size,
                "total": total,
                "pages": pages,
            },
            meta={"search": search, "tag_filter": tag_filter, "tag_id": tag_id},
        )
    except HTTPException as exc:
        raise exc
    except Exception:
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@collection_router.post("/search-by-tag", response_model=PersonDetailListResponse)
async def search_persons_by_tag(
    tag_identifier: PersonTagSearchRequest,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> PersonDetailListResponse:
    """
    Search for persons by tag ID or tag name

    This endpoint allows searching for persons using either:
    - tag_id: Direct tag ID lookup (faster)
    - tag_name: Tag name lookup (more flexible)

    Args:
        tag_identifier: Dictionary containing either 'tag_id' or 'tag_name'
        db: Database session

    Returns:
        List of persons that have the specified tag

    Raises:
        HTTPException: If tag not found
        ValidationError: If request body validation fails (handled automatically by FastAPI)
    """
    try:
        offset = (page - 1) * size
        persons, total = await person_service.search_persons_by_tag_with_total(
            db,
            user_id=current_user.id,
            tag_id=tag_identifier.tag_id,
            tag_name=tag_identifier.tag_name,
            limit=size,
            offset=offset,
        )
        items = [PersonResponse.model_validate(person) for person in persons]
        pages = (total + size - 1) // size if size else 0
        tag_filter = (
            tag_identifier.tag_name
            if tag_identifier.tag_name
            else (str(tag_identifier.tag_id) if tag_identifier.tag_id else None)
        )
        return PersonDetailListResponse(
            items=items,
            pagination={
                "page": page,
                "size": size,
                "total": total,
                "pages": pages,
            },
            meta={
                "search": None,
                "tag_filter": tag_filter,
            },
        )
    except TagNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException as exc:
        raise exc
    except Exception:
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@resource_router.get("", response_model=PersonResponse)
async def get_person(
    person_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> PersonResponse:
    """
    Get a specific person by ID

    Args:
        person_id: Person ID
        db: Database session

    Returns:
        Person details with tags and anniversaries
    """
    try:
        person = await person_service.get_person(
            db, user_id=current_user.id, person_id=person_id
        )
        if person is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Person not found"
            )
        return PersonResponse.model_validate(person)
    except HTTPException as exc:
        raise exc
    except Exception:
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@collection_router.post(
    "/", response_model=PersonResponse, status_code=status.HTTP_201_CREATED
)
async def create_person(
    person_data: PersonCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> PersonResponse:
    """
    Create a new person

    Args:
        person_data: Person creation data
        db: Database session

    Returns:
        Created person with tags and anniversaries
    """
    try:
        person = await person_service.create_person(
            db, user_id=current_user.id, person_in=person_data
        )
        return PersonResponse.model_validate(person)
    except TagNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException as exc:
        raise exc
    except Exception:
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@resource_router.put("", response_model=PersonResponse)
async def update_person(
    person_id: UUID,
    person_data: PersonUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> PersonResponse:
    """
    Update a person

    Args:
        person_id: Person ID
        person_data: Person update data
        db: Database session

    Returns:
        Updated person
    """
    try:
        person = await person_service.update_person(
            db,
            user_id=current_user.id,
            person_id=person_id,
            update_in=person_data,
        )
        if person is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Person not found"
            )
        return PersonResponse.model_validate(person)
    except TagNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException as exc:
        raise exc
    except Exception:
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@resource_router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_person(
    person_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete a person."""
    try:
        success = await person_service.delete_person(
            db,
            user_id=current_user.id,
            person_id=person_id,
            hard_delete=False,
        )
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Person not found"
            )
    except HTTPException as exc:
        raise exc
    except Exception:
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


# Person-Tag Association endpoints
# Note: Tag CRUD operations are handled by the unified /tags/ endpoints
# This section only handles the association between persons and tags


@resource_router.post("/tags/{tag_id:uuid}", response_model=PersonResponse)
async def add_tag_to_person(
    person_id: UUID,
    tag_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> PersonResponse:
    """
    Add a tag to a person

    This endpoint manages the association between a person and a tag.
    The tag must already exist and have entity_type='person'.

    Args:
        person_id: Person ID
        tag_id: Tag ID (must be a person tag)
        db: Database session

    Returns:
        Updated person with tags

    Raises:
        HTTPException: If person or tag not found, or tag is not a person tag
    """
    try:
        person = await person_service.add_tag_to_person(
            db,
            user_id=current_user.id,
            person_id=person_id,
            tag_id=tag_id,
        )
        if person is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Person not found"
            )
        return PersonResponse.model_validate(person)
    except TagNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PersonAlreadyExistsError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException as exc:
        raise exc
    except Exception:
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@resource_router.delete("/tags/{tag_id:uuid}", response_model=PersonResponse)
async def remove_tag_from_person(
    person_id: UUID,
    tag_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> PersonResponse:
    """
    Remove a tag from a person

    This endpoint removes the association between a person and a tag.
    The tag itself is not deleted, only the association is removed.

    Args:
        person_id: Person ID
        tag_id: Tag ID (must be a person tag)
        db: Database session

    Returns:
        Updated person without the tag

    Raises:
        HTTPException: If person or tag not found, or tag is not a person tag
    """
    try:
        person = await person_service.remove_tag_from_person(
            db,
            user_id=current_user.id,
            person_id=person_id,
            tag_id=tag_id,
        )
        if person is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Person not found"
            )
        return PersonResponse.model_validate(person)
    except TagNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PersonNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException as exc:
        raise exc
    except Exception:
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


# Anniversary endpoints
@resource_router.post(
    "/anniversaries/",
    response_model=AnniversaryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_anniversary(
    person_id: UUID,
    anniversary_data: AnniversaryCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Create a new anniversary for a person

    Args:
        person_id: Person ID
        anniversary_data: Anniversary creation data
        db: Database session

    Returns:
        Created anniversary
    """
    try:
        anniversary = await person_service.create_anniversary(
            db,
            user_id=current_user.id,
            person_id=person_id,
            anniversary_data=anniversary_data,
        )
        return anniversary
    except PersonNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException as exc:
        raise exc
    except Exception:
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@resource_router.get("/anniversaries/", response_model=AnniversaryListResponse)
async def get_person_anniversaries(
    person_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> AnniversaryListResponse:
    """
    Get all anniversaries for a person

    Args:
        person_id: Person ID
        db: Database session

    Returns:
        List of anniversaries for the person
    """
    try:
        anniversaries = await person_service.get_person_anniversaries(
            db,
            user_id=current_user.id,
            person_id=person_id,
        )
        total = len(anniversaries)
        pages = 1 if total > 0 else 0
        return AnniversaryListResponse(
            items=anniversaries,
            pagination={
                "page": 1,
                "size": total,
                "total": total,
                "pages": pages,
            },
            meta={"person_id": person_id},
        )
    except PersonNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException as exc:
        raise exc
    except Exception:
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@resource_router.delete(
    "/anniversaries/{anniversary_id:uuid}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_anniversary(
    person_id: UUID,
    anniversary_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """
    Delete an anniversary

    Args:
        person_id: Person ID
        anniversary_id: Anniversary ID
        db: Database session
    """
    try:
        await person_service.delete_anniversary(
            db,
            user_id=current_user.id,
            person_id=person_id,
            anniversary_id=anniversary_id,
        )
    except PersonNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except AnniversaryNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException as exc:
        raise exc
    except Exception:
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@resource_router.put(
    "/anniversaries/{anniversary_id:uuid}",
    response_model=AnniversaryResponse,
)
async def update_anniversary(
    person_id: UUID,
    anniversary_id: UUID,
    update_data: AnniversaryUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> AnniversaryResponse:
    """Update an anniversary for a person."""

    try:
        anniversary = await person_service.update_anniversary(
            db,
            user_id=current_user.id,
            person_id=person_id,
            anniversary_id=anniversary_id,
            update_data=update_data,
        )
        return anniversary
    except AnniversaryNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException as exc:
        raise exc
    except Exception:
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


# Person Activities Timeline
@resource_router.get("/activities/", response_model=PersonActivitiesResponse)
async def get_person_activities(
    person_id: UUID,
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(50, ge=1, le=1000, description="Page size"),
    activity_type: Optional[
        Literal["vision", "task", "planned_event", "actual_event", "note"]
    ] = Query(
        None,
        alias="type",
        description="Filter by activity type (vision, task, planned_event, actual_event, note)",
    ),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get activity timeline for a person

    This endpoint aggregates all activities (visions, tasks, events, notes)
    associated with a person and returns them in chronological order.

    Args:
        person_id: Person ID
        page: Page number (1-indexed)
        size: Number of records to return
        db: Database session

    Returns:
        Person activities timeline
    """
    try:
        activities_response = await person_service.get_person_activities(
            db,
            user_id=current_user.id,
            person_id=person_id,
            page=page,
            size=size,
            activity_type=activity_type,
        )
        return activities_response
    except PersonNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException as exc:
        raise exc
    except Exception:
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


router.include_router(collection_router)
router.include_router(resource_router)
