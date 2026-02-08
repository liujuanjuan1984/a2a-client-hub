"""Person-related tools exposed to the agent layer."""

import sys
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.agents.tools.arg_utils import normalize_uuid_list, parse_uuid_list_argument
from app.agents.tools.audit_utils import audit_for_entity, ensure_snapshot
from app.agents.tools.base import AbstractTool, ToolMetadata
from app.agents.tools.responses import (
    ToolResult,
    create_tool_error,
    create_tool_response,
    serialize_entity,
)
from app.core.logging import get_logger, log_exception
from app.handlers import persons as person_service
from app.handlers.persons import (
    AnniversaryNotFoundError,
    PersonNotFoundError,
    TagNotFoundError,
)
from app.schemas.person import (
    AnniversaryCreate,
    AnniversaryUpdate,
    PersonCreate,
    PersonUpdate,
)

logger = get_logger(__name__)


class ListPersonsArgs(BaseModel):
    """Arguments for listing persons."""

    search: Optional[str] = Field(
        None, description="Optional search keyword for name or nickname."
    )
    tag: Optional[str] = Field(
        None, description="Optional tag name filter (case-insensitive)."
    )
    nickname_exact: Optional[str] = Field(
        None, description="Exact nickname match for deduplication."
    )
    skip: int = Field(0, ge=0, le=1000, description="Number of records to skip.")
    limit: int = Field(
        20,
        ge=1,
        le=200,
        description="Maximum number of persons to return (1-200).",
    )


class ListPersonsTool(AbstractTool):
    """Tool that lists people in the user's relationship graph."""

    name = "list_persons"
    description = (
        "List people with optional search and tag filters."
        " Read-only helper for relationship overviews."
    )
    args_schema = ListPersonsArgs

    async def execute(
        self,
        search: Optional[str] = None,
        tag: Optional[str] = None,
        nickname_exact: Optional[str] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> ToolResult:
        try:
            db = self._ensure_db()
            persons, total = await person_service.list_persons(
                db=db,
                user_id=self.user_id,
                skip=skip,
                limit=limit,
                tag_filter=tag,
                search=search,
                nickname_exact=nickname_exact,
            )
            serialized = [
                serialize_entity(person, "person_summary") for person in persons
            ]
            return create_tool_response(
                data={
                    "persons": serialized,
                    "count": len(serialized),
                    "total": total,
                    "skip": skip,
                    "limit": limit,
                    "search": search,
                    "tag": tag,
                }
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(logger, f"Error listing persons: {exc}", sys.exc_info())
            return create_tool_error("Failed to list persons", detail=str(exc))


class GetPersonActivitiesArgs(BaseModel):
    """Arguments for retrieving a person's activity timeline."""

    person_id: UUID = Field(..., description="The person ID to query.")
    page: int = Field(1, ge=1, le=1000, description="Page number (1-1000).")
    size: int = Field(
        20,
        ge=1,
        le=200,
        description="Maximum number of activities to return (1-200).",
    )
    activity_type: Optional[
        Literal["vision", "task", "planned_event", "actual_event", "note"]
    ] = Field(None, description="Optional activity type filter.")


class GetPersonActivitiesTool(AbstractTool):
    """Tool that retrieves consolidated activities associated with a person."""

    name = "get_person_activities"
    description = (
        "Retrieve the activity timeline (visions, tasks, events, notes) for a person."
        " Read-only aggregation that does not modify data."
    )
    args_schema = GetPersonActivitiesArgs

    async def execute(
        self,
        person_id: UUID,
        page: int = 1,
        size: int = 20,
        activity_type: Optional[
            Literal["vision", "task", "planned_event", "actual_event", "note"]
        ] = None,
    ) -> ToolResult:
        try:
            db = self._ensure_db()
            person = await person_service.get_person(
                db=db, user_id=self.user_id, person_id=person_id
            )
            if person is None:
                raise PersonNotFoundError("Person not found")

            timeline = await person_service.get_person_activities(
                db=db,
                user_id=self.user_id,
                person_id=person_id,
                page=page,
                size=size,
                activity_type=activity_type,
            )
            serialized = [
                serialize_entity(item, "person_activity") for item in timeline.items
            ]
            person_summary = serialize_entity(person, "person")
            return create_tool_response(
                data={
                    "person": person_summary,
                    "activities": serialized,
                    "count": len(serialized),
                    "total": timeline.pagination.total,
                    "page": page,
                    "size": size,
                    "pages": timeline.pagination.pages,
                }
            )
        except PersonNotFoundError as exc:
            return create_tool_error(
                "Person not found",
                kind="not_found",
                detail=str(exc),
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(
                logger, f"Error retrieving person activities: {exc}", sys.exc_info()
            )
            return create_tool_error(
                "Failed to retrieve person activities", detail=str(exc)
            )


class CreatePersonArgs(PersonCreate):
    """Arguments for creating a person."""

    @field_validator("tag_ids", mode="before")
    @classmethod
    def _coerce_tag_ids(cls, value):
        return parse_uuid_list_argument(value, field_name="tag_ids")


class CreatePersonTool(AbstractTool):
    """Tool that creates a new person."""

    name = "create_person"
    description = (
        "Create and persist a new person record with optional tags and details."
    )
    args_schema = CreatePersonArgs
    metadata = ToolMetadata(
        read_only=False,
        requires_confirmation=False,
        idempotent=False,
        labels=("person", "write"),
        default_timeout=30.0,
    )

    async def execute(
        self,
        name: Optional[str] = None,
        nicknames: Optional[list[str]] = None,
        birth_date: Optional[str] = None,
        location: Optional[str] = None,
        tag_ids: Optional[list[UUID]] = None,
    ) -> ToolResult:
        try:
            normalized_tag_ids = normalize_uuid_list(tag_ids)
            person_data = PersonCreate(
                name=name,
                nicknames=nicknames,
                birth_date=birth_date,
                location=location,
                tag_ids=normalized_tag_ids,
            )
            db = self._ensure_db()
            person = await person_service.create_person(
                db=db, user_id=self.user_id, person_in=person_data
            )
            serialized = serialize_entity(person, "person")
            audit = audit_for_entity(
                "persons.create",
                entity_type="person",
                entity_id=getattr(person, "id", None),
                after_snapshot=serialized,
            )
            return create_tool_response(data={"person": serialized}, audit=audit)
        except TagNotFoundError as exc:
            return create_tool_error(
                "Tag not found",
                kind="validation_error",
                detail=str(exc),
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(logger, f"Error creating person: {exc}", sys.exc_info())
            return create_tool_error("Failed to create person", detail=str(exc))


class UpdatePersonArgs(PersonUpdate):
    """
    Arguments for updating a person.

    Omit optional fields to keep the stored value. Set nullable fields (name, nicknames,
    birth_date, location, tag_ids) to null/[] to clear them.
    """

    person_id: UUID = Field(..., description="Person identifier to update.")

    @field_validator("tag_ids", mode="before")
    @classmethod
    def _coerce_tag_ids(cls, value):
        return parse_uuid_list_argument(value, field_name="tag_ids")


class UpdatePersonTool(AbstractTool):
    """Tool that updates an existing person."""

    name = "update_person"
    description = (
        "Update an existing person with new data. Omit properties to keep them "
        "unchanged; set nullable ones to null/[] to clear stored values."
    )
    args_schema = UpdatePersonArgs
    metadata = ToolMetadata(
        read_only=False,
        requires_confirmation=False,
        idempotent=False,
        labels=("person", "write"),
        default_timeout=30.0,
    )

    async def execute(
        self,
        person_id: UUID,
        name: Optional[str] = None,
        nicknames: Optional[list[str]] = None,
        birth_date: Optional[str] = None,
        location: Optional[str] = None,
        tag_ids: Optional[list[UUID]] = None,
    ) -> ToolResult:
        try:
            db = self._ensure_db()
            existing = await person_service.get_person(
                db=db, user_id=self.user_id, person_id=person_id
            )
            if existing is None:
                raise PersonNotFoundError("Person not found")
            before_snapshot = ensure_snapshot(existing, "person")

            normalized_tag_ids = normalize_uuid_list(tag_ids)
            update_data = PersonUpdate(
                name=name,
                nicknames=nicknames,
                birth_date=birth_date,
                location=location,
                tag_ids=normalized_tag_ids,
            )
            person = await person_service.update_person(
                db=db,
                user_id=self.user_id,
                person_id=person_id,
                update_in=update_data,
            )
            if person is None:
                raise PersonNotFoundError("Person not found")

            serialized = serialize_entity(person, "person")
            audit = audit_for_entity(
                "persons.update",
                entity_type="person",
                entity_id=person_id,
                before_snapshot=before_snapshot,
                after_snapshot=serialized,
            )
            return create_tool_response(data={"person": serialized}, audit=audit)
        except PersonNotFoundError as exc:
            return create_tool_error(
                "Person not found",
                kind="not_found",
                detail=str(exc),
            )
        except TagNotFoundError as exc:
            return create_tool_error(
                "Tag not found",
                kind="validation_error",
                detail=str(exc),
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(logger, f"Error updating person: {exc}", sys.exc_info())
            return create_tool_error("Failed to update person", detail=str(exc))


class DeletePersonArgs(BaseModel):
    """Arguments for deleting a person."""

    person_id: UUID = Field(..., description="Person identifier to delete.")


class DeletePersonTool(AbstractTool):
    """Tool that deletes a person."""

    name = "delete_person"
    description = "Delete a person."
    args_schema = DeletePersonArgs
    metadata = ToolMetadata(
        read_only=False,
        requires_confirmation=False,
        idempotent=False,
        labels=("person", "write"),
        default_timeout=20.0,
    )

    async def execute(self, person_id: UUID) -> ToolResult:
        try:
            db = self._ensure_db()
            existing = await person_service.get_person(
                db=db, user_id=self.user_id, person_id=person_id
            )
            if existing is None:
                raise PersonNotFoundError("Person not found")
            before_snapshot = ensure_snapshot(existing, "person")

            success = await person_service.delete_person(
                db=db,
                user_id=self.user_id,
                person_id=person_id,
                hard_delete=False,
            )
            if not success:
                raise PersonNotFoundError("Person not found")

            audit = audit_for_entity(
                "persons.delete",
                entity_type="person",
                entity_id=person_id,
                before_snapshot=before_snapshot,
                extra={"hard_delete": False},
            )
            return create_tool_response(
                data={
                    "message": f"Person {person_id} successfully deleted",
                    "person_id": person_id,
                },
                audit=audit,
            )
        except PersonNotFoundError as exc:
            return create_tool_error(
                "Person not found",
                kind="not_found",
                detail=str(exc),
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(logger, f"Error deleting person: {exc}", sys.exc_info())
            return create_tool_error("Failed to delete person", detail=str(exc))


class GetPersonDetailArgs(BaseModel):
    """Arguments for retrieving a specific person."""

    person_id: UUID = Field(..., description="Person identifier to retrieve.")


class GetPersonDetailTool(AbstractTool):
    """Tool that returns details for a single person."""

    name = "get_person_detail"
    description = (
        "Retrieve a person's complete details including tags and anniversaries."
        " Read-only helper for inspection."
    )
    args_schema = GetPersonDetailArgs

    async def execute(self, person_id: UUID) -> ToolResult:
        try:
            db = self._ensure_db()
            person = await person_service.get_person(
                db=db, user_id=self.user_id, person_id=person_id
            )
            if person is None:
                raise PersonNotFoundError("Person not found")

            return create_tool_response(
                data={"person": serialize_entity(person, "person")}
            )
        except PersonNotFoundError as exc:
            return create_tool_error(
                "Person not found",
                kind="not_found",
                detail=str(exc),
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(
                logger, f"Error retrieving person detail: {exc}", sys.exc_info()
            )
            return create_tool_error(
                "Failed to retrieve person detail", detail=str(exc)
            )


class CreateAnniversaryArgs(BaseModel):
    """Arguments for creating an anniversary for a person."""

    person_id: UUID = Field(
        ..., description="Person identifier to attach the anniversary to."
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Anniversary name (e.g., 'Wedding').",
    )
    date: str = Field(..., description="Anniversary date in YYYY-MM-DD format.")


class CreateAnniversaryTool(AbstractTool):
    """Tool that creates a new anniversary for a person."""

    name = "create_anniversary"
    description = (
        "Create a commemorative date for a contact (e.g., first met, wedding)."
    )
    args_schema = CreateAnniversaryArgs
    metadata = ToolMetadata(
        read_only=False,
        requires_confirmation=False,
        idempotent=False,
        labels=("person", "write"),
        default_timeout=20.0,
    )

    async def execute(self, person_id: UUID, name: str, date: str) -> ToolResult:
        try:
            db = self._ensure_db()
            anniversary = await person_service.create_anniversary(
                db=db,
                user_id=self.user_id,
                person_id=person_id,
                anniversary_data=AnniversaryCreate(name=name, date=date),
            )
            serialized = serialize_entity(anniversary, "anniversary")
            audit = audit_for_entity(
                "persons.anniversary.create",
                entity_type="anniversary",
                entity_id=getattr(anniversary, "id", None),
                after_snapshot=serialized,
                extra={"person_id": person_id},
            )
            return create_tool_response(data={"anniversary": serialized}, audit=audit)
        except PersonNotFoundError as exc:
            return create_tool_error(
                "Person not found",
                kind="not_found",
                detail=str(exc),
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(logger, f"Error creating anniversary: {exc}", sys.exc_info())
            return create_tool_error("Failed to create anniversary", detail=str(exc))


class ListAnniversariesArgs(BaseModel):
    """Arguments for listing anniversaries of a person."""

    person_id: UUID = Field(..., description="Person identifier to inspect.")


class ListAnniversariesTool(AbstractTool):
    """Tool that lists anniversaries associated with a person."""

    name = "list_anniversaries"
    description = "List all anniversaries tied to a contact. Read-only helper."
    args_schema = ListAnniversariesArgs

    async def execute(self, person_id: UUID) -> ToolResult:
        try:
            db = self._ensure_db()
            anniversaries = await person_service.get_person_anniversaries(
                db=db, user_id=self.user_id, person_id=person_id
            )
            serialized = [
                serialize_entity(item, "anniversary") for item in anniversaries
            ]
            return create_tool_response(
                data={
                    "person_id": person_id,
                    "anniversaries": serialized,
                    "count": len(serialized),
                }
            )
        except PersonNotFoundError as exc:
            return create_tool_error(
                "Person not found",
                kind="not_found",
                detail=str(exc),
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(logger, f"Error listing anniversaries: {exc}", sys.exc_info())
            return create_tool_error("Failed to list anniversaries", detail=str(exc))


class DeleteAnniversaryArgs(BaseModel):
    """Arguments for deleting an anniversary."""

    person_id: UUID = Field(..., description="Owner person identifier.")
    anniversary_id: UUID = Field(..., description="Anniversary identifier to delete.")


class DeleteAnniversaryTool(AbstractTool):
    """Tool that deletes an anniversary for a person."""

    name = "delete_anniversary"
    description = "Delete a contact's anniversary record (permanent)."
    args_schema = DeleteAnniversaryArgs
    metadata = ToolMetadata(
        read_only=False,
        requires_confirmation=False,
        idempotent=False,
        labels=("person", "write"),
        default_timeout=20.0,
    )

    async def execute(self, person_id: UUID, anniversary_id: UUID) -> ToolResult:
        try:
            db = self._ensure_db()
            await person_service.delete_anniversary(
                db=db,
                user_id=self.user_id,
                person_id=person_id,
                anniversary_id=anniversary_id,
            )

            audit = audit_for_entity(
                "persons.anniversary.delete",
                entity_type="anniversary",
                entity_id=anniversary_id,
                before_snapshot={
                    "person_id": person_id,
                    "anniversary_id": anniversary_id,
                },
            )
            return create_tool_response(
                data={
                    "message": "Anniversary deleted",
                    "person_id": person_id,
                    "anniversary_id": anniversary_id,
                },
                audit=audit,
            )
        except (PersonNotFoundError, AnniversaryNotFoundError) as exc:
            return create_tool_error(
                "Anniversary not found",
                kind="not_found",
                detail=str(exc),
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(logger, f"Error deleting anniversary: {exc}", sys.exc_info())
            return create_tool_error("Failed to delete anniversary", detail=str(exc))


class UpdateAnniversaryArgs(BaseModel):
    """
    Arguments for updating an anniversary.

    Omit fields to keep their values. Anniversary name/date cannot be cleared, so null is invalid.
    """

    person_id: UUID = Field(..., description="Owner person identifier.")
    anniversary_id: UUID = Field(..., description="Anniversary identifier to update.")
    name: Optional[str] = Field(
        None,
        min_length=1,
        max_length=200,
        description="Updated anniversary name; omit to keep it (cannot be null).",
    )
    date: Optional[str] = Field(
        None,
        description="Updated anniversary date (YYYY-MM-DD); omit to keep it (cannot be null).",
    )


class UpdateAnniversaryTool(AbstractTool):
    """Tool that updates an anniversary for a person."""

    name = "update_anniversary"
    description = (
        "Update a contact's anniversary name or date. Omit fields to keep them; "
        "anniversary attributes cannot be cleared via null."
    )
    args_schema = UpdateAnniversaryArgs
    metadata = ToolMetadata(
        read_only=False,
        requires_confirmation=False,
        idempotent=False,
        labels=("person", "write"),
        default_timeout=20.0,
    )

    async def execute(
        self,
        person_id: UUID,
        anniversary_id: UUID,
        name: Optional[str] = None,
        date: Optional[str] = None,
    ) -> ToolResult:
        try:
            update_payload = AnniversaryUpdate(name=name, date=date)
            db = self._ensure_db()
            anniversary = await person_service.update_anniversary(
                db=db,
                user_id=self.user_id,
                person_id=person_id,
                anniversary_id=anniversary_id,
                update_data=update_payload,
            )

            serialized = serialize_entity(anniversary, "anniversary")
            audit = audit_for_entity(
                "persons.anniversary.update",
                entity_type="anniversary",
                entity_id=anniversary_id,
                after_snapshot=serialized,
                extra={"person_id": person_id},
            )
            return create_tool_response(data={"anniversary": serialized}, audit=audit)
        except (PersonNotFoundError, AnniversaryNotFoundError) as exc:
            return create_tool_error(
                "Anniversary not found",
                kind="not_found",
                detail=str(exc),
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(logger, f"Error updating anniversary: {exc}", sys.exc_info())
            return create_tool_error("Failed to update anniversary", detail=str(exc))


__all__ = [
    "ListPersonsTool",
    "GetPersonActivitiesTool",
    "CreatePersonTool",
    "UpdatePersonTool",
    "DeletePersonTool",
    "GetPersonDetailTool",
    "CreateAnniversaryTool",
    "ListAnniversariesTool",
    "DeleteAnniversaryTool",
    "UpdateAnniversaryTool",
]
