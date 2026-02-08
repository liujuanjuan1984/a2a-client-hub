"""
Notes API Router

This module contains API endpoints for managing quick notes.
Routers call into the service layer and map business exceptions to HTTP errors.
"""

from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.routing import StrictAPIRouter
from app.core.logging import get_logger
from app.db.models.note_ingest_job import NoteIngestJob
from app.db.models.user import User
from app.handlers import notes as note_service
from app.handlers.notes_exceptions import (
    InvalidOperationError,
    NoteNotFoundError,
    TagAlreadyAssociatedError,
    TagNotAssociatedError,
    TagNotFoundError,
)
from app.schemas.note import (
    NoteAdvancedSearchRequest,
    NoteBatchDeleteRequest,
    NoteBatchDeleteResponse,
    NoteBatchUpdateRequest,
    NoteBatchUpdateResponse,
    NoteBulkCreateFailedItem,
    NoteBulkCreateRequest,
    NoteBulkCreateResponse,
    NoteCreate,
    NoteIngestJobSummary,
    NoteListResponse,
    NoteResponse,
    NoteUpdate,
)
from app.serialization.entities import build_note_response
from app.services.note_ingest_jobs import enqueue_note_ingest_job

# Router definition
router = StrictAPIRouter(
    prefix="/notes",
    tags=["notes"],
    responses={404: {"description": "Not found"}},
    dependencies=[Depends(get_current_user)],
)
collection_router = StrictAPIRouter(tags=["notes"])
resource_router = StrictAPIRouter(prefix="/{note_id:uuid}", tags=["notes"])

logger = get_logger(__name__)


@collection_router.post("/", response_model=NoteResponse, status_code=201)
async def create_note(
    note: NoteCreate,
    auto_ingest: bool = Query(
        False,
        description="Trigger the asynchronous note auto-ingest workflow after creation",
    ),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> NoteResponse:
    """
    Create a new quick note

    Designed for instant capture with minimal overhead.

    Args:
        note: Note data containing only the content
        db: Database session

    Returns:
        Created note with id and timestamps
    """
    try:
        db_note = await note_service.create_note(
            db, user_id=current_user.id, note_in=note
        )

        associations = await note_service.get_notes_with_associations(
            db,
            user_id=current_user.id,
            notes=[db_note],
        )
        assoc = associations.get(db_note.id, {}) if associations else {}

        response = build_note_response(
            db_note,
            persons=assoc.get("persons", []),
            task=assoc.get("task"),
            timelogs=assoc.get("timelogs"),
            include_timelogs=True,
        )
        if auto_ingest:
            ingest_job_summary = await _try_enqueue_ingest_job(
                db=db,
                user_id=current_user.id,
                note_id=db_note.id,
            )
            if ingest_job_summary is not None:
                response = response.model_copy(
                    update={"ingest_job": ingest_job_summary}
                )

        return response
    except HTTPException as exc:
        raise exc
    except Exception:
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


def _build_ingest_job_summary(job: NoteIngestJob) -> NoteIngestJobSummary:
    return NoteIngestJobSummary(
        id=job.id,
        status=job.status,
        retry_count=job.retry_count,
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


async def _try_enqueue_ingest_job(
    *,
    db: AsyncSession,
    user_id: UUID,
    note_id: UUID,
) -> Optional[NoteIngestJobSummary]:
    try:
        job = await enqueue_note_ingest_job(
            db,
            user_id=user_id,
            note_id=note_id,
        )
        return _build_ingest_job_summary(job)
    except Exception:  # pragma: no cover - defensive log only
        logger.warning(
            "Failed to enqueue note ingest job user_id=%s note_id=%s",
            user_id,
            note_id,
            exc_info=True,
        )
        return None


@collection_router.get(
    "/ingest-jobs/{job_id:uuid}", response_model=NoteIngestJobSummary
)
async def get_ingest_job(
    job_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> NoteIngestJobSummary:
    stmt = (
        select(NoteIngestJob)
        .where(NoteIngestJob.id == job_id)
        .where(NoteIngestJob.user_id == current_user.id)
    )
    result = await db.execute(stmt)
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Ingest job not found")

    return _build_ingest_job_summary(job)


@collection_router.post(
    "/batch-create", response_model=NoteBulkCreateResponse, status_code=201
)
async def batch_create_notes_endpoint(
    note_request: NoteBulkCreateRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> NoteBulkCreateResponse:
    """Create multiple notes with shared associations in one request."""

    try:
        note_inputs = [
            NoteCreate(
                content=item.content,
                person_ids=note_request.person_ids,
                tag_ids=note_request.tag_ids,
                task_id=note_request.task_id,
                actual_event_ids=note_request.actual_event_ids,
            )
            for item in note_request.notes
        ]

        created_notes, failed_items = await note_service.batch_create_notes(
            db,
            user_id=current_user.id,
            note_inputs=note_inputs,
        )

        associations = await note_service.get_notes_with_associations(
            db,
            user_id=current_user.id,
            notes=created_notes,
        )

        response_notes: list[NoteResponse] = []
        for note in created_notes:
            assoc = associations.get(note.id, {})
            response_notes.append(
                build_note_response(
                    note,
                    persons=assoc.get("persons", []),
                    task=assoc.get("task"),
                    timelogs=assoc.get("timelogs"),
                    include_timelogs=True,
                )
            )

        failed_payload = [
            NoteBulkCreateFailedItem(
                index=item["index"],
                content_preview=item["content"][:200],
                error=item["error"],
            )
            for item in failed_items
        ]

        return NoteBulkCreateResponse(
            created_notes=response_notes,
            failed_items=failed_payload,
            created_count=len(response_notes),
            failed_count=len(failed_payload),
        )
    except HTTPException as exc:
        raise exc
    except Exception:
        logger.exception("Failed to batch create notes")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@collection_router.get("/stats")
async def get_notes_stats(
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    [Deprecated] Use `/stats/tags/usage/note` and `/notes/stats/persons` instead.

    This endpoint previously returned combined statistics. It is kept for
    backward compatibility and now returns only total notes count.

    Args:
        db: Database session

    Returns:
        Dictionary containing only total notes count
    """
    return await note_service.get_notes_stats(db, user_id=current_user.id)


@collection_router.get("/stats/persons")
async def get_notes_person_stats(
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Get person usage statistics for notes

    Returns a list of persons with their usage counts across all notes.
    Only non-deleted persons and non-deleted notes associated via `IS_ABOUT` are counted.
    """
    return await note_service.get_notes_person_stats(db, user_id=current_user.id)


@collection_router.get("/", response_model=NoteListResponse)
async def get_notes(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=100),
    tag_id: Optional[UUID] = Query(None, description="Filter by tag ID"),
    person_id: Optional[UUID] = Query(None, description="Filter by person ID"),
    task_id: Optional[UUID] = Query(None, description="Filter by task ID"),
    actual_event_id: Optional[UUID] = Query(
        None, description="Filter by associated actual event (timelog) ID"
    ),
    keyword: Optional[str] = Query(None, description="Search in note content"),
    untagged: Optional[bool] = Query(None, description="Filter for notes with no tags"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> NoteListResponse:
    """
    Get notes with pagination and optional filtering by tag or person

    This endpoint provides paginated access to notes with optional filtering
    by tag or person for better performance and targeted queries.

    Args:
        page: Page number (1-indexed)
        size: Maximum number of notes to return (1-100)
        tag_id: Optional tag ID to filter notes
        person_id: Optional person ID to filter notes
        db: Database session

    Returns:
        List of notes ordered by created_at desc, filtered and limited by pagination
    """
    try:
        offset = (page - 1) * size
        notes, total = await note_service.list_notes_with_total(
            db,
            user_id=current_user.id,
            limit=size,
            offset=offset,
            tag_id=tag_id,
            person_id=person_id,
            task_id=task_id,
            actual_event_id=actual_event_id,
            keyword=keyword,
            untagged=untagged,
        )

        pages = (total + size - 1) // size if size else 0
        if not notes:
            return NoteListResponse(
                items=[],
                pagination={
                    "page": page,
                    "size": size,
                    "total": total,
                    "pages": pages,
                },
                meta={
                    "tag_id": tag_id,
                    "person_id": person_id,
                    "task_id": task_id,
                    "actual_event_id": actual_event_id,
                    "keyword": keyword,
                    "untagged": untagged,
                },
            )

        # Get associations for all notes efficiently
        associations = await note_service.get_notes_with_associations(
            db,
            user_id=current_user.id,
            notes=notes,
        )

        result: list[NoteResponse] = []
        for note in notes:
            note_associations = associations.get(note.id, {})
            result.append(
                build_note_response(
                    note,
                    persons=note_associations.get("persons", []),
                    task=note_associations.get("task"),
                    timelogs=note_associations.get("timelogs", []),
                    include_timelogs=True,
                )
            )
        return NoteListResponse(
            items=result,
            pagination={
                "page": page,
                "size": size,
                "total": total,
                "pages": pages,
            },
            meta={
                "tag_id": tag_id,
                "person_id": person_id,
                "task_id": task_id,
                "actual_event_id": actual_event_id,
                "keyword": keyword,
                "untagged": untagged,
            },
        )
    except InvalidOperationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException as exc:
        raise exc
    except Exception:
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@resource_router.get("", response_model=NoteResponse)
async def get_note(
    note_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> NoteResponse:
    """Get a single note by ID."""

    try:
        db_note = await note_service.get_note(
            db,
            user_id=current_user.id,
            note_id=note_id,
        )

        associations = await note_service.get_notes_with_associations(
            db,
            user_id=current_user.id,
            notes=[db_note],  # type: ignore[list-item]
        )
        assoc = associations.get(db_note.id, {}) if associations else {}

        return build_note_response(
            db_note,
            persons=assoc.get("persons", []),
            task=assoc.get("task"),
            timelogs=assoc.get("timelogs", []),
            include_timelogs=True,
        )
    except NoteNotFoundError:
        raise HTTPException(status_code=404, detail="Note not found")
    except HTTPException as exc:
        raise exc
    except Exception:
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@collection_router.post("/advanced-search", response_model=NoteListResponse)
async def advanced_search_notes_endpoint(
    request: NoteAdvancedSearchRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> NoteListResponse:
    """Advanced search for notes with flexible filters and batch selection support."""

    try:
        results = await note_service.advanced_search_notes(
            db,
            user_id=current_user.id,
            request=request,
        )

        response: List[NoteResponse] = []
        for note, persons, task in results:
            response.append(
                build_note_response(
                    note,
                    persons=persons,
                    task=task,
                    timelogs=getattr(note, "timelogs", []),
                    include_timelogs=True,
                )
            )
        total = len(response)
        return NoteListResponse(
            items=response,
            pagination={
                "page": 1,
                "size": total,
                "total": total,
                "pages": 1 if total else 0,
            },
            meta={
                "start_date": request.start_date,
                "end_date": request.end_date,
                "tag_ids": request.tag_ids,
                "tag_mode": request.tag_mode,
                "person_ids": request.person_ids,
                "person_mode": request.person_mode,
                "task_filter": request.task_filter,
                "task_id": request.task_id,
                "keyword": request.keyword,
                "sort_order": request.sort_order,
            },
        )
    except InvalidOperationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Failed to perform advanced note search", exc_info=exc)
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@collection_router.post("/batch-update", response_model=NoteBatchUpdateResponse)
async def batch_update_notes_endpoint(
    request: NoteBatchUpdateRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> NoteBatchUpdateResponse:
    """Batch update notes using the advanced selection tools."""

    try:
        return await note_service.batch_update_notes(
            db,
            user_id=current_user.id,
            request=request,
        )
    except InvalidOperationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Failed to batch update notes", exc_info=exc)
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@collection_router.post("/batch-delete", response_model=NoteBatchDeleteResponse)
async def batch_delete_notes_endpoint(
    request: NoteBatchDeleteRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> NoteBatchDeleteResponse:
    """Batch delete notes selected via advanced search."""

    try:
        return await note_service.batch_delete_notes(
            db,
            user_id=current_user.id,
            request=request,
        )
    except InvalidOperationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Failed to batch delete notes", exc_info=exc)
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@resource_router.put("", response_model=NoteResponse)
async def update_note(
    note_id: UUID,
    note: NoteUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> NoteResponse:
    """
    Update a specific note.

    This is a partial update. Only include the fields you want to change.
    - To update/replace associations like `person_ids` or `tag_ids`, provide the new array of IDs.
    - To clear all associations for a type, provide an empty array (e.g., `"person_ids": []`).
    - To leave associations untouched, omit the key (e.g., do not send `person_ids` at all).

    Args:
        note_id: Note ID
        note: Updated note data
        db: Database session

    Returns:
        Updated note

    Raises:
        HTTPException: If note not found
    """
    try:
        db_note = await note_service.update_note(
            db,
            user_id=current_user.id,
            note_id=note_id,
            note_in=note,
        )

        associations = await note_service.get_notes_with_associations(
            db,
            user_id=current_user.id,
            notes=[db_note],  # type: ignore[list-item]
        )
        assoc = associations.get(db_note.id, {}) if associations else {}

        return build_note_response(
            db_note,
            persons=assoc.get("persons", []),
            task=assoc.get("task"),
            timelogs=assoc.get("timelogs"),
            include_timelogs=True,
        )
    except NoteNotFoundError:
        raise HTTPException(status_code=404, detail="Note not found")
    except InvalidOperationError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except HTTPException as exc:
        raise exc
    except Exception:
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@resource_router.delete("", status_code=204)
async def delete_note(
    note_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """
    Soft delete a note (mark as deleted but keep data)

    This endpoint marks a note as deleted without actually removing
    the data from the database, supporting data recovery if needed.

    Note: When a note is soft deleted:
    - The note itself is marked as deleted
    - Associated Association records (person links) are soft deleted
    - Tag associations in tag_associations table remain but are filtered out in queries
      since tag_associations doesn't support soft delete

    Args:
        note_id: Note ID to delete
        db: Database session

    Raises:
        HTTPException: If note not found or already deleted
    """
    try:
        await note_service.delete_note(db, user_id=current_user.id, note_id=note_id)
        return None
    except NoteNotFoundError:
        raise HTTPException(status_code=404, detail="Note not found")
    except HTTPException as exc:
        raise exc
    except Exception:
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


# Note Tags endpoints
@resource_router.post("/tags/{tag_id:uuid}", response_model=NoteResponse)
async def add_tag_to_note(
    note_id: UUID,
    tag_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> NoteResponse:
    """
    Add a tag to a note

    Args:
        note_id: Note ID
        tag_id: Tag ID
        db: Database session

    Returns:
        Updated note with tags

    Raises:
        HTTPException: If note or tag not found
    """
    try:
        note = await note_service.add_tag_to_note(
            db,
            user_id=current_user.id,
            note_id=note_id,
            tag_id=tag_id,
        )

        associations = await note_service.get_notes_with_associations(
            db,
            user_id=current_user.id,
            notes=[note],
        )
        assoc = associations.get(note.id, {}) if associations else {}

        return build_note_response(
            note,
            persons=assoc.get("persons", []),
            task=assoc.get("task"),
            timelogs=assoc.get("timelogs"),
            include_timelogs=True,
        )
    except NoteNotFoundError:
        raise HTTPException(status_code=404, detail="Note not found")
    except TagNotFoundError:
        raise HTTPException(status_code=404, detail="Tag not found")
    except TagAlreadyAssociatedError:
        raise HTTPException(
            status_code=400,
            detail="Tag is already associated with this note",
        )
    except HTTPException as exc:
        raise exc
    except Exception:
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@resource_router.delete("/tags/{tag_id:uuid}", response_model=NoteResponse)
async def remove_tag_from_note(
    note_id: UUID,
    tag_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> NoteResponse:
    """
    Remove a tag from a note

    Args:
        note_id: Note ID
        tag_id: Tag ID
        db: Database session

    Returns:
        Updated note without the tag

    Raises:
        HTTPException: If note or tag not found
    """
    try:
        note = await note_service.remove_tag_from_note(
            db,
            user_id=current_user.id,
            note_id=note_id,
            tag_id=tag_id,
        )

        associations = await note_service.get_notes_with_associations(
            db,
            user_id=current_user.id,
            notes=[note],
        )
        assoc = associations.get(note.id, {}) if associations else {}

        return build_note_response(
            note,
            persons=assoc.get("persons", []),
            task=assoc.get("task"),
            timelogs=assoc.get("timelogs"),
            include_timelogs=True,
        )
    except NoteNotFoundError:
        raise HTTPException(status_code=404, detail="Note not found")
    except TagNotFoundError:
        raise HTTPException(status_code=404, detail="Tag not found")
    except TagNotAssociatedError:
        raise HTTPException(
            status_code=400,
            detail="Tag is not associated with this note",
        )
    except HTTPException as exc:
        raise exc
    except Exception:
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


router.include_router(collection_router)
router.include_router(resource_router)
