"""Note-related tools exposed to the agent layer."""

import json
import sys
from typing import Any, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.agents.tools.audit_utils import audit_for_entity
from app.agents.tools.base import AbstractTool, ToolMetadata
from app.agents.tools.responses import (
    ToolResult,
    create_tool_error,
    create_tool_response,
)
from app.core.logging import get_logger, log_exception
from app.handlers import notes as note_service
from app.handlers.notes import NoteNotFoundError, TagNotFoundError
from app.schemas.note import NoteCreate, NoteUpdate
from app.serialization.entities import build_note_response

logger = get_logger(__name__)


async def _populate_note_relationships(db, user_id: UUID, notes: List[Any]) -> None:
    if not notes:
        return

    associations = await note_service.get_notes_with_associations(
        db=db,
        user_id=user_id,
        notes=notes,
    )
    if not associations:
        return

    for note in notes:
        assoc = associations.get(note.id)
        if not assoc:
            continue
        note.persons = assoc.get("persons") or []  # type: ignore[attr-defined]
        note.task = assoc.get("task")  # type: ignore[attr-defined]
        note.timelogs = assoc.get("timelogs") or []  # type: ignore[attr-defined]


class CreateNoteArgs(BaseModel):
    """Arguments for creating a new note."""

    content: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="The content of the note to create",
    )
    person_ids: Optional[List[str]] = Field(
        None, description="List of person IDs to associate with this note"
    )
    tag_ids: Optional[List[str]] = Field(
        None, description="List of tag IDs to associate with this note"
    )
    task_id: Optional[UUID] = Field(
        None, description="Task ID to associate with this note"
    )

    @field_validator("person_ids", "tag_ids", mode="before")
    @classmethod
    def _coerce_json_list(cls, value):
        """Allow passing JSON-encoded list strings (agent sometimes serializes arrays as strings)."""

        if value is None:
            return value

        if isinstance(value, list):
            return value

        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return parsed
            except Exception:
                # Fallback: treat comma-separated string
                items = [v.strip() for v in value.split(",") if v.strip()]
                if items:
                    return items

        raise ValueError("person_ids/tag_ids must be a list or JSON array string")


class CreateNoteTool(AbstractTool):
    """Tool for creating new notes in the Common Compass Platform."""

    name = "create_note"
    description = "Create and persist a new note with optional associations to persons, tags, and tasks."
    args_schema = CreateNoteArgs
    metadata = ToolMetadata(
        read_only=False,
        requires_confirmation=False,
        idempotent=False,
        labels=("notes", "write"),
        default_timeout=30.0,
    )

    async def execute(
        self,
        content: str,
        person_ids: Optional[List[str]] = None,
        tag_ids: Optional[List[str]] = None,
        task_id: Optional[UUID] = None,
    ) -> ToolResult:
        try:
            db = self._ensure_db()
            note_in = NoteCreate(
                content=content, person_ids=person_ids, tag_ids=tag_ids, task_id=task_id
            )
            note = await note_service.create_note(
                db=db, user_id=self.user_id, note_in=note_in
            )
            await _populate_note_relationships(db, self.user_id, [note])

            note_data = build_note_response(note, include_timelogs=False).model_dump(
                mode="json"
            )
            audit = audit_for_entity(
                "notes.create",
                entity_type="note",
                entity_id=getattr(note, "id", None),
                after_snapshot=note_data,
            )
            return create_tool_response(data={"note": note_data}, audit=audit)

        except TagNotFoundError as exc:
            return create_tool_error(
                "Tag not found", kind="validation_error", detail=str(exc)
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(logger, f"Error creating note: {exc}", sys.exc_info())
            return create_tool_error("Error creating note", detail=str(exc))


class UpdateNoteArgs(BaseModel):
    """
    Arguments for updating an existing note.

    Omit optional fields to keep current values. Provide explicit null/[] for nullable
    fields (person_ids, tag_ids, task_id) to clear or unlink them.
    """

    note_id: UUID = Field(..., description="ID of the note to update")
    content: Optional[str] = Field(
        None,
        description="Updated note content; omit to keep unchanged (cannot be null).",
    )
    person_ids: Optional[List[str]] = Field(
        None,
        description="Replacement list of person IDs; omit to keep or pass null/[] to remove all.",
    )
    tag_ids: Optional[List[str]] = Field(
        None,
        description="Replacement list of tag IDs; omit to keep or pass null/[] to remove all.",
    )
    task_id: Optional[UUID] = Field(
        None, description="Replacement task ID; omit to keep or set null to unlink."
    )

    @field_validator("person_ids", "tag_ids", mode="before")
    @classmethod
    def _coerce_json_list(cls, value):
        if value is None:
            return value
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return parsed
            except Exception:
                items = [v.strip() for v in value.split(",") if v.strip()]
                if items:
                    return items
        raise ValueError("person_ids/tag_ids must be a list or JSON array string")


class UpdateNoteTool(AbstractTool):
    """Tool for updating an existing note and its relationships."""

    name = "update_note"
    description = (
        "Update an existing note's content, tags, persons, or linked task. Omit fields "
        "to keep them unchanged; set nullable ones (IDs) to null/[] to clear associations."
    )
    args_schema = UpdateNoteArgs
    metadata = ToolMetadata(
        read_only=False,
        requires_confirmation=False,
        idempotent=False,
        labels=("notes", "write"),
        default_timeout=30.0,
    )

    async def execute(
        self,
        note_id: UUID,
        content: Optional[str] = None,
        person_ids: Optional[List[str]] = None,
        tag_ids: Optional[List[str]] = None,
        task_id: Optional[UUID] = None,
    ) -> ToolResult:
        try:
            db = self._ensure_db()
            existing = await note_service.get_note(
                db=db, user_id=self.user_id, note_id=note_id
            )
            if existing is None:
                return create_tool_error(
                    "Note not found", kind="not_found", detail=str(note_id)
                )
            await _populate_note_relationships(db, self.user_id, [existing])
            before_data = build_note_response(
                existing, include_timelogs=False
            ).model_dump(mode="json")

            payload = NoteUpdate(
                content=content,
                person_ids=person_ids,
                tag_ids=tag_ids,
                task_id=task_id,
            )
            note = await note_service.update_note(
                db=db,
                user_id=self.user_id,
                note_id=note_id,
                update_in=payload,
            )
            if note is None:
                return create_tool_error(
                    "Note not found", kind="not_found", detail=str(note_id)
                )
            await _populate_note_relationships(db, self.user_id, [note])
            note_data = build_note_response(note, include_timelogs=False).model_dump(
                mode="json"
            )
            audit = audit_for_entity(
                "notes.update",
                entity_type="note",
                entity_id=note_id,
                before_snapshot=before_data,
                after_snapshot=note_data,
            )
            return create_tool_response(data={"note": note_data}, audit=audit)
        except TagNotFoundError as exc:
            return create_tool_error(
                "Tag not found", kind="validation_error", detail=str(exc)
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(logger, f"Error updating note: {exc}", sys.exc_info())
            return create_tool_error("Error updating note", detail=str(exc))


class GetLatestNotesArgs(BaseModel):
    """Arguments for retrieving latest notes."""

    limit: int = Field(
        5, ge=1, le=50, description="Maximum number of notes to retrieve (1-50)"
    )
    keyword: Optional[str] = Field(
        None, description="Optional keyword to search in note content"
    )


class GetLatestNotesTool(AbstractTool):
    """Tool for retrieving the latest notes."""

    name = "get_latest_notes"
    description = (
        "Retrieve the most recent notes, optionally filtered by keyword."
        " Read-only helper for quick review."
    )
    args_schema = GetLatestNotesArgs
    metadata = ToolMetadata(
        read_only=True,
        labels=("notes", "read"),
        default_timeout=20.0,
    )

    async def execute(
        self, limit: int = 5, keyword: Optional[str] = None
    ) -> ToolResult:
        try:
            db = self._ensure_db()
            notes = await note_service.list_notes(
                db=db,
                user_id=self.user_id,
                limit=limit,
                keyword=keyword,
            )
            if not notes:
                return create_tool_response(data={"notes": [], "count": 0})

            await _populate_note_relationships(db, self.user_id, notes)
            # Use Pydantic schema for proper serialization
            serialized = [
                build_note_response(note, include_timelogs=False).model_dump(
                    mode="json"
                )
                for note in notes
            ]
            return create_tool_response(
                data={"notes": serialized, "count": len(serialized)}
            )

        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(logger, f"Error retrieving notes: {exc}", sys.exc_info())
            return create_tool_error("Error retrieving notes", detail=str(exc))


class SearchNotesArgs(BaseModel):
    """Arguments for searching notes."""

    keyword: str = Field(
        ..., min_length=1, description="Keyword to search in note content"
    )
    limit: int = Field(
        10, ge=1, le=50, description="Maximum number of notes to retrieve (1-50)"
    )


class SearchNotesTool(AbstractTool):
    """Tool for searching notes by keyword."""

    name = "search_notes"
    description = (
        "Search notes by keyword in the Common Compass platform."
        " Read-only lookup operation."
    )
    args_schema = SearchNotesArgs
    metadata = ToolMetadata(
        read_only=True,
        labels=("notes", "read"),
        default_timeout=20.0,
    )

    async def execute(self, keyword: str, limit: int = 10) -> ToolResult:
        try:
            db = self._ensure_db()
            notes = await note_service.list_notes(
                db=db, user_id=self.user_id, limit=limit, keyword=keyword
            )
            if not notes:
                return create_tool_response(
                    data={"notes": [], "count": 0, "keyword": keyword}
                )

            await _populate_note_relationships(db, self.user_id, notes)
            # Use Pydantic schema for proper serialization
            serialized = [
                build_note_response(note, include_timelogs=False).model_dump(
                    mode="json"
                )
                for note in notes
            ]
            return create_tool_response(
                data={"notes": serialized, "count": len(serialized), "keyword": keyword}
            )

        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(logger, f"Error searching notes: {exc}", sys.exc_info())
            return create_tool_error("Error searching notes", detail=str(exc))


class ListNotesByContentArgs(BaseModel):
    """Arguments for listing notes by exact content (dedup helper)."""

    content: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="Exact note content to match (whitespace-trimmed before query)",
    )
    limit: int = Field(5, ge=1, le=50, description="Max results to return")
    offset: int = Field(0, ge=0, le=1000, description="Results offset")


class ListNotesByContentTool(AbstractTool):
    """Tool that lists notes whose content matches exactly (active notes only)."""

    name = "list_notes_by_content"
    description = (
        "List notes with content exactly matching the provided text."
        " Useful for deduplication before creating new notes."
    )
    args_schema = ListNotesByContentArgs
    metadata = ToolMetadata(
        read_only=True,
        labels=("notes", "read"),
        default_timeout=20.0,
    )

    async def execute(
        self, content: str, limit: int = 5, offset: int = 0
    ) -> ToolResult:
        try:
            db = self._ensure_db()
            notes = await note_service.list_notes(
                db=db,
                user_id=self.user_id,
                limit=limit,
                offset=offset,
                content_exact=content,
            )
            await _populate_note_relationships(db, self.user_id, notes)
            serialized = [
                build_note_response(note, include_timelogs=False).model_dump(
                    mode="json"
                )
                for note in notes
            ]
            return create_tool_response(
                data={"notes": serialized, "count": len(serialized)}
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(
                logger, f"Error listing notes by content: {exc}", sys.exc_info()
            )
            return create_tool_error("Error listing notes", detail=str(exc))


class DeleteNoteArgs(BaseModel):
    """Arguments for deleting a note."""

    note_id: UUID = Field(..., description="ID of the note to delete")


class DeleteNoteTool(AbstractTool):
    """Tool for deleting a note."""

    name = "delete_note"
    description = "Delete a note."
    args_schema = DeleteNoteArgs
    metadata = ToolMetadata(
        read_only=False,
        requires_confirmation=False,
        idempotent=False,
        labels=("notes", "write"),
        default_timeout=20.0,
    )

    async def execute(self, note_id: UUID) -> ToolResult:
        try:
            db = self._ensure_db()
            await note_service.delete_note(db=db, user_id=self.user_id, note_id=note_id)
            audit = audit_for_entity(
                "notes.delete",
                entity_type="note",
                entity_id=note_id,
                extra={"hard_delete": False},
            )
            return create_tool_response(data={"note_id": str(note_id)}, audit=audit)
        except NoteNotFoundError as exc:
            return create_tool_error(
                "Note not found", kind="not_found", detail=str(exc)
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(logger, f"Error deleting note: {exc}", sys.exc_info())
            return create_tool_error("Error deleting note", detail=str(exc))


__all__ = [
    "CreateNoteTool",
    "UpdateNoteTool",
    "GetLatestNotesTool",
    "SearchNotesTool",
    "ListNotesByContentTool",
    "DeleteNoteTool",
]
