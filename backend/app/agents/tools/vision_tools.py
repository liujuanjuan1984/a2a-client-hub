"""Vision-related tools exposed to the agent layer."""

import sys
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.agents.tools.arg_utils import normalize_uuid_list, parse_uuid_list_argument
from app.agents.tools.audit_utils import audit_for_entity
from app.agents.tools.base import AbstractTool, ToolMetadata
from app.agents.tools.responses import (
    ToolResult,
    create_tool_error,
    create_tool_response,
)
from app.core.logging import get_logger, log_exception
from app.handlers import tasks as task_service
from app.handlers import visions as vision_service
from app.handlers.visions import (
    InvalidVisionStatusError,
    VisionAlreadyExistsError,
    VisionNotFoundError,
)
from app.schemas.vision import VisionCreate, VisionUpdate
from app.serialization.entities import build_vision_response, serialize_task

logger = get_logger(__name__)


class ListVisionsArgs(BaseModel):
    """Arguments for listing visions."""

    status: Optional[str] = Field(
        None, description="Optional status filter (active, archived, fruit)."
    )
    name: Optional[str] = Field(None, description="Exact vision name to filter.")
    skip: int = Field(0, ge=0, le=1000, description="Number of visions to skip.")
    limit: int = Field(
        20,
        ge=1,
        le=200,
        description="Maximum number of visions to return (1-200).",
    )


class ListVisionsTool(AbstractTool):
    """Tool that lists visions for the current user."""

    name = "list_visions"
    description = (
        "List visions with optional status filtering."
        " Read-only helper for planning overviews."
    )
    args_schema = ListVisionsArgs

    async def execute(
        self,
        status: Optional[str] = None,
        name: Optional[str] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> ToolResult:
        try:
            db = self._ensure_db()
            visions = await vision_service.list_visions(
                db=db,
                user_id=self.user_id,
                skip=skip,
                limit=limit,
                status_filter=status,
                name=name,
            )
            payload = {
                "visions": [
                    build_vision_response(vision).model_dump(mode="json")
                    for vision in visions
                ],
                "count": len(visions),
                "skip": skip,
                "limit": limit,
                "status": status,
            }
            return create_tool_response(data=payload)
        except InvalidVisionStatusError as exc:
            return create_tool_error(
                "Invalid vision filter",
                kind="validation_error",
                detail=str(exc),
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(logger, f"Error listing visions: {exc}", sys.exc_info())
            return create_tool_error("Failed to list visions", detail=str(exc))


class GetVisionDetailArgs(BaseModel):
    """Arguments for retrieving a specific vision."""

    vision_id: UUID = Field(..., description="Vision identifier to retrieve.")
    include_tasks: bool = Field(
        False,
        description="Whether to include hierarchical tasks associated with the vision.",
    )


class GetVisionDetailTool(AbstractTool):
    """Tool that returns a single vision with optional task hierarchy."""

    name = "get_vision_detail"
    description = (
        "Retrieve a vision and, optionally, all of its tasks." " Read-only operation."
    )
    args_schema = GetVisionDetailArgs

    async def execute(self, vision_id: UUID, include_tasks: bool = False) -> ToolResult:
        try:
            db = self._ensure_db()
            vision = await vision_service.get_vision(
                db=db, user_id=self.user_id, vision_id=vision_id
            )
            if vision is None:
                raise VisionNotFoundError("Vision not found")

            vision_payload = build_vision_response(vision).model_dump(mode="json")

            if include_tasks:
                hierarchy = await task_service.get_vision_task_hierarchy(
                    db=db, user_id=self.user_id, vision_id=vision_id
                )
                vision_payload["tasks"] = [
                    serialize_task(root, include_persons=True, include_subtasks=True)
                    for root in hierarchy.root_tasks
                    if root is not None
                ]
            else:
                vision_payload["tasks"] = []

            return create_tool_response(data={"vision": vision_payload})
        except VisionNotFoundError as exc:
            return create_tool_error(
                "Vision not found",
                kind="not_found",
                detail=str(exc),
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(
                logger, f"Error retrieving vision detail: {exc}", sys.exc_info()
            )
            return create_tool_error(
                "Failed to retrieve vision detail", detail=str(exc)
            )


class CreateVisionArgs(BaseModel):
    """Arguments for creating a vision."""

    name: str = Field(..., min_length=1, max_length=200, description="Vision name")
    description: Optional[str] = Field(
        None, description="Detailed description of this vision and its significance"
    )
    dimension_id: Optional[UUID] = Field(
        None,
        description=(
            "Default dimension for this vision. Tasks and quick time entries may inherit this."
        ),
    )
    person_ids: Optional[list[UUID]] = Field(
        None, description="List of person IDs to associate with this vision"
    )

    @field_validator("person_ids", mode="before")
    @classmethod
    def _coerce_person_ids(cls, value):
        return parse_uuid_list_argument(value, field_name="person_ids")


class CreateVisionTool(AbstractTool):
    """Tool that creates a new vision."""

    name = "create_vision"
    description = "Create and persist a new vision with optional person associations."
    args_schema = CreateVisionArgs
    metadata = ToolMetadata(
        read_only=False,
        requires_confirmation=False,
        idempotent=False,
        labels=("vision", "write"),
        default_timeout=30.0,
    )

    async def execute(
        self,
        name: str,
        description: Optional[str] = None,
        dimension_id: Optional[UUID] = None,
        person_ids: Optional[list[UUID]] = None,
    ) -> ToolResult:
        try:
            normalized_person_ids = normalize_uuid_list(person_ids)
            vision_data = VisionCreate(
                name=name,
                description=description,
                dimension_id=dimension_id,
                person_ids=normalized_person_ids,
            )
            db = self._ensure_db()
            vision = await vision_service.create_vision(
                db=db, user_id=self.user_id, vision_in=vision_data
            )
            vision_payload = build_vision_response(vision).model_dump(mode="json")
            audit = audit_for_entity(
                "visions.create",
                entity_type="vision",
                entity_id=getattr(vision, "id", None),
                after_snapshot=vision_payload,
            )
            return create_tool_response(data={"vision": vision_payload}, audit=audit)
        except VisionAlreadyExistsError as exc:
            return create_tool_error(
                "Vision already exists",
                kind="validation_error",
                detail=str(exc),
            )
        except VisionNotFoundError as exc:
            return create_tool_error(
                "Person not found",
                kind="validation_error",
                detail=str(exc),
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(logger, f"Error creating vision: {exc}", sys.exc_info())
            return create_tool_error("Failed to create vision", detail=str(exc))


class UpdateVisionArgs(BaseModel):
    """
    Arguments for updating a vision.

    Omit optional fields to keep their existing values. For nullable fields
    (description, dimension_id, person_ids) provide explicit null/[] to clear them.
    """

    vision_id: UUID = Field(..., description="Vision identifier to update.")
    name: Optional[str] = Field(
        None,
        min_length=1,
        max_length=200,
        description="Updated vision name; omit to keep current value (cannot be null).",
    )
    description: Optional[str] = Field(
        None,
        description="Updated detailed description; omit to keep it or set null to remove it.",
    )
    status: Optional[str] = Field(
        None,
        description="Updated vision status; omit to keep current status (cannot be null).",
    )
    dimension_id: Optional[UUID] = Field(
        None,
        description=(
            "Updated default dimension; omit to keep it or set null to fall back to the user's default."
        ),
    )
    person_ids: Optional[list[UUID]] = Field(
        None,
        description="Updated person associations; omit to keep them or pass null/[] to clear all links.",
    )

    @field_validator("person_ids", mode="before")
    @classmethod
    def _coerce_person_ids(cls, value):
        return parse_uuid_list_argument(value, field_name="person_ids")


class UpdateVisionTool(AbstractTool):
    """Tool that updates an existing vision."""

    name = "update_vision"
    description = (
        "Update an existing vision with new data. Omit properties to leave them unchanged; "
        "set nullable ones (description, dimension/person links) to null/[] to clear them."
    )
    args_schema = UpdateVisionArgs
    metadata = ToolMetadata(
        read_only=False,
        requires_confirmation=False,
        idempotent=False,
        labels=("vision", "write"),
        default_timeout=30.0,
    )

    async def execute(
        self,
        vision_id: UUID,
        name: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None,
        dimension_id: Optional[UUID] = None,
        person_ids: Optional[list[UUID]] = None,
    ) -> ToolResult:
        try:
            db = self._ensure_db()
            existing = await vision_service.get_vision(
                db=db, user_id=self.user_id, vision_id=vision_id
            )
            if existing is None:
                raise VisionNotFoundError("Vision not found")
            before_payload = build_vision_response(existing).model_dump(mode="json")

            normalized_person_ids = normalize_uuid_list(person_ids)
            update_data = VisionUpdate(
                name=name,
                description=description,
                status=status,
                dimension_id=dimension_id,
                person_ids=normalized_person_ids,
            )
            vision = await vision_service.update_vision(
                db=db,
                user_id=self.user_id,
                vision_id=vision_id,
                update_in=update_data,
            )
            if vision is None:
                raise VisionNotFoundError("Vision not found")

            updated_payload = build_vision_response(vision).model_dump(mode="json")
            audit = audit_for_entity(
                "visions.update",
                entity_type="vision",
                entity_id=vision_id,
                before_snapshot=before_payload,
                after_snapshot=updated_payload,
            )
            return create_tool_response(
                data={"vision": updated_payload},
                audit=audit,
            )
        except VisionNotFoundError as exc:
            return create_tool_error(
                "Vision not found",
                kind="not_found",
                detail=str(exc),
            )
        except VisionAlreadyExistsError as exc:
            return create_tool_error(
                "Vision name already exists",
                kind="validation_error",
                detail=str(exc),
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(logger, f"Error updating vision: {exc}", sys.exc_info())
            return create_tool_error("Failed to update vision", detail=str(exc))


class DeleteVisionArgs(BaseModel):
    """Arguments for deleting a vision."""

    vision_id: UUID = Field(..., description="Vision identifier to delete.")


class DeleteVisionTool(AbstractTool):
    """Tool that deletes a vision."""

    name = "delete_vision"
    description = "Delete a vision."
    args_schema = DeleteVisionArgs
    metadata = ToolMetadata(
        read_only=False,
        requires_confirmation=False,
        idempotent=False,
        labels=("vision", "write"),
        default_timeout=20.0,
    )

    async def execute(self, vision_id: UUID) -> ToolResult:
        try:
            db = self._ensure_db()
            success = await vision_service.delete_vision(
                db=db,
                user_id=self.user_id,
                vision_id=vision_id,
                hard_delete=False,
            )
            if not success:
                raise VisionNotFoundError("Vision not found")

            audit = audit_for_entity(
                "visions.delete",
                entity_type="vision",
                entity_id=vision_id,
                extra={"hard_delete": False},
            )
            return create_tool_response(data={"vision_id": str(vision_id)}, audit=audit)
        except VisionNotFoundError as exc:
            return create_tool_error(
                "Vision not found",
                kind="not_found",
                detail=str(exc),
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(logger, f"Error deleting vision: {exc}", sys.exc_info())
            return create_tool_error("Failed to delete vision", detail=str(exc))


__all__ = [
    "ListVisionsTool",
    "GetVisionDetailTool",
    "CreateVisionTool",
    "UpdateVisionTool",
    "DeleteVisionTool",
]
