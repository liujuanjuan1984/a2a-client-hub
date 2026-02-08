"""Tag management tools for the agent layer."""

import sys
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.agents.tools.audit_utils import audit_for_entity, ensure_snapshot
from app.agents.tools.base import AbstractTool, ToolMetadata
from app.agents.tools.responses import (
    ToolResult,
    create_tool_error,
    create_tool_response,
)
from app.core.logging import get_logger, log_exception
from app.handlers import tags as tag_service
from app.handlers.tags import TagAlreadyExistsError, TagNotFoundError
from app.schemas.tag import TagCreate, TagUpdate
from app.serialization.entities import serialize_tag

logger = get_logger(__name__)

# To avoid oversize payloads exceeding AgentMessage content limits (10k chars)
MAX_TAG_RESULTS = 60
MAX_DESCRIPTION_LENGTH = 160


def _serialize_tag_summary(tag) -> dict:
    """Serialize tag with a compact subset of fields."""

    description = (tag.description or "").strip()
    if description and len(description) > MAX_DESCRIPTION_LENGTH:
        description = description[: MAX_DESCRIPTION_LENGTH - 1] + "…"

    payload = serialize_tag(tag)
    payload = {
        "id": payload.get("id"),
        "name": payload.get("name"),
        "entity_type": payload.get("entity_type"),
        "category": payload.get("category"),
    }
    if description:
        payload["description"] = description
    return payload


class CreateTagArgs(BaseModel):
    """Arguments for creating a new tag."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Tag name (e.g., 'family', 'important')",
    )
    entity_type: str = Field(
        "general",
        description="Entity type: 'person', 'note', 'task', 'vision', or 'general'",
    )
    category: str = Field(
        "general",
        description="Tag category: 'general' or 'location'",
    )
    description: Optional[str] = Field(
        None, description="Optional description explaining the purpose of this tag"
    )
    color: Optional[str] = Field(
        None,
        max_length=7,
        description="Hex color code for this tag (e.g., '#3B82F6')",
    )


class CreateTagTool(AbstractTool):
    """Tool for creating new tags."""

    name = "create_tag"
    description = (
        "Create a new tag or return the existing one if it already exists."
        " Persists changes to the user's tag catalog."
    )
    args_schema = CreateTagArgs
    metadata = ToolMetadata(
        read_only=False,
        requires_confirmation=False,
        idempotent=False,
        labels=("tag", "write"),
        default_timeout=20.0,
    )

    async def execute(
        self,
        name: str,
        entity_type: str = "general",
        category: str = "general",
        description: Optional[str] = None,
        color: Optional[str] = None,
    ) -> ToolResult:
        try:
            db = self._ensure_db()
            tag_in = TagCreate(
                name=name,
                entity_type=entity_type,
                category=category,
                description=description,
                color=color,
            )
            tag = await tag_service.create_tag(
                db=db, user_id=self.user_id, tag_in=tag_in
            )
            tag_payload = _serialize_tag_summary(tag)
            audit = audit_for_entity(
                "tags.create",
                entity_type="tag",
                entity_id=getattr(tag, "id", None),
                after_snapshot=tag_payload,
            )
            return create_tool_response(data={"tag": tag_payload}, audit=audit)
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(logger, f"Error creating tag: {exc}", sys.exc_info())
            return create_tool_error("Error creating tag", detail=str(exc))


class ListTagsArgs(BaseModel):
    """Arguments for listing tags."""

    entity_type: Optional[str] = Field(
        None,
        description="Optional entity filter: 'person', 'note', 'task', 'vision', 'general'",
    )
    category: Optional[str] = Field(
        None,
        description="Optional category filter: 'general', 'location'",
    )
    name: Optional[str] = Field(
        None, description="Exact tag name to filter (case-insensitive, normalized)."
    )


class ListTagsTool(AbstractTool):
    """Tool for listing tags."""

    name = "list_tags"
    description = (
        "List all tags, optionally filtered by entity type." " Read-only lookup."
    )
    args_schema = ListTagsArgs

    async def execute(
        self,
        entity_type: Optional[str] = None,
        category: Optional[str] = None,
        name: Optional[str] = None,
    ) -> ToolResult:
        try:
            db = self._ensure_db()
            filters = {}
            if entity_type:
                filters["entity_type"] = entity_type
            if category:
                filters["category"] = category
            if name:
                filters["name"] = name
            tags = await tag_service.list_tags(db=db, user_id=self.user_id, **filters)
            total = len(tags)
            limited_tags = tags[:MAX_TAG_RESULTS]
            serialized = [_serialize_tag_summary(tag) for tag in limited_tags]
            return create_tool_response(
                data={
                    "tags": serialized,
                    "returned": len(serialized),
                    "count": total,
                    "has_more": total > len(serialized),
                }
            )

        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(logger, f"Error listing tags: {exc}", sys.exc_info())
            return create_tool_error("Error listing tags", detail=str(exc))


class GetTagUsageArgs(BaseModel):
    """Arguments for getting tag usage information."""

    tag_id: UUID = Field(..., description="ID of the tag to inspect")


class GetTagUsageTool(AbstractTool):
    """Tool for retrieving tag usage statistics."""

    name = "get_tag_usage"
    description = (
        "Retrieve usage statistics for a specific tag."
        " Read-only helper for analytics."
    )
    args_schema = GetTagUsageArgs

    async def execute(self, tag_id: UUID) -> ToolResult:
        try:
            db = self._ensure_db()
            usage_info = await tag_service.get_tag_usage(
                db=db, user_id=self.user_id, tag_id=tag_id
            )
            if not usage_info:
                return create_tool_error("Tag not found", kind="not_found")

            usage_by_type = usage_info.get("usage_by_entity_type", {})
            payload = {
                "tag": {
                    "id": tag_id,
                    "name": usage_info.get("tag_name"),
                    "entity_type": usage_info.get("entity_type"),
                    "category": usage_info.get("category"),
                },
                "usage_by_entity_type": usage_by_type,
                "total_usage": usage_info.get("total_usage", 0),
            }
            return create_tool_response(data=payload)

        except TagNotFoundError:
            return create_tool_error("Tag not found", kind="not_found")
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(logger, f"Error getting tag usage: {exc}", sys.exc_info())
            return create_tool_error("Error getting tag usage", detail=str(exc))


class UpdateTagArgs(BaseModel):
    """
    Arguments for updating a tag.

    Omit optional fields to leave the stored value unchanged. For nullable fields
    (description, color) pass explicit null to clear the saved value.
    """

    tag_id: UUID = Field(..., description="ID of the tag to update")
    name: Optional[str] = Field(
        None,
        description="Updated tag name; omit to keep current value (cannot be set to null).",
    )
    entity_type: Optional[str] = Field(
        None,
        description="Updated entity type; omit to keep current value (cannot be set to null).",
    )
    category: Optional[str] = Field(
        None,
        description="Updated category; omit to keep current value (cannot be set to null).",
    )
    description: Optional[str] = Field(
        None,
        description="Updated description; omit to keep current text or set null to remove it.",
    )
    color: Optional[str] = Field(
        None,
        description="Updated hex color code; omit to keep current color or set null to clear it.",
    )


class UpdateTagTool(AbstractTool):
    """Tool that updates an existing tag."""

    name = "update_tag"
    description = (
        "Update an existing tag's attributes. Omit any property to keep it unchanged; "
        "set nullable fields (e.g., description/color) to null to clear them."
    )
    args_schema = UpdateTagArgs
    metadata = ToolMetadata(
        read_only=False,
        requires_confirmation=False,
        idempotent=False,
        labels=("tag", "write"),
        default_timeout=20.0,
    )

    async def execute(
        self,
        tag_id: UUID,
        name: Optional[str] = None,
        entity_type: Optional[str] = None,
        category: Optional[str] = None,
        description: Optional[str] = None,
        color: Optional[str] = None,
    ) -> ToolResult:
        try:
            db = self._ensure_db()
            existing = await tag_service.get_tag(
                db=db, user_id=self.user_id, tag_id=tag_id
            )
            if existing is None:
                raise TagNotFoundError("Tag not found")
            before = ensure_snapshot(existing, "tag")

            update_in = TagUpdate(
                name=name,
                entity_type=entity_type,
                category=category,
                description=description,
                color=color,
            )
            tag = await tag_service.update_tag(
                db=db, user_id=self.user_id, tag_id=tag_id, update_in=update_in
            )
            if tag is None:
                raise TagNotFoundError("Tag not found")

            payload = serialize_tag(tag)
            audit = audit_for_entity(
                "tags.update",
                entity_type="tag",
                entity_id=tag_id,
                before_snapshot=before,
                after_snapshot=payload,
            )
            return create_tool_response(data={"tag": payload}, audit=audit)
        except TagAlreadyExistsError as exc:
            return create_tool_error(
                "Tag already exists",
                kind="validation_error",
                detail=str(exc),
            )
        except TagNotFoundError as exc:
            return create_tool_error("Tag not found", kind="not_found", detail=str(exc))
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(logger, f"Error updating tag: {exc}", sys.exc_info())
            return create_tool_error("Error updating tag", detail=str(exc))


class DeleteTagArgs(BaseModel):
    """Arguments for deleting a tag."""

    tag_id: UUID = Field(..., description="ID of the tag to delete")


class DeleteTagTool(AbstractTool):
    """Tool that deletes a tag."""

    name = "delete_tag"
    description = "Delete a tag."
    args_schema = DeleteTagArgs
    metadata = ToolMetadata(
        read_only=False,
        requires_confirmation=False,
        idempotent=False,
        labels=("tag", "write"),
        default_timeout=20.0,
    )

    async def execute(self, tag_id: UUID) -> ToolResult:
        try:
            db = self._ensure_db()
            success = await tag_service.delete_tag(
                db=db, user_id=self.user_id, tag_id=tag_id, hard_delete=False
            )
            if not success:
                raise TagNotFoundError("Tag not found")
            audit = audit_for_entity(
                "tags.delete",
                entity_type="tag",
                entity_id=tag_id,
                extra={"hard_delete": False},
            )
            return create_tool_response(data={"tag_id": str(tag_id)}, audit=audit)
        except TagNotFoundError as exc:
            return create_tool_error("Tag not found", kind="not_found", detail=str(exc))
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(logger, f"Error deleting tag: {exc}", sys.exc_info())
            return create_tool_error("Error deleting tag", detail=str(exc))


__all__ = [
    "CreateTagTool",
    "ListTagsTool",
    "GetTagUsageTool",
    "UpdateTagTool",
    "DeleteTagTool",
]
