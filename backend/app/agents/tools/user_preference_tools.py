"""User preference tools exposed to the agent layer."""

import sys
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.agents.tools.audit_utils import audit_for_entity
from app.agents.tools.base import AbstractTool, ToolMetadata
from app.agents.tools.responses import (
    ToolResult,
    create_tool_error,
    create_tool_response,
    serialize_entity,
)
from app.core.logging import get_logger, log_exception
from app.handlers import user_preferences as preference_service

logger = get_logger(__name__)


class ListUserPreferencesArgs(BaseModel):
    """Arguments for listing user preferences."""

    module: Optional[str] = Field(
        None, description="Optional module key to filter preferences."
    )
    page: int = Field(1, ge=1, description="Page number (1-indexed).")
    size: int = Field(
        20,
        ge=1,
        le=200,
        description="Page size / number of preferences per page (1-200).",
    )


class ListUserPreferencesTool(AbstractTool):
    """Tool that lists preferences for the current user."""

    name = "list_user_preferences"
    description = (
        "List user preferences with optional module filtering."
        " Read-only helper for inspection."
    )
    args_schema = ListUserPreferencesArgs

    async def execute(
        self, module: Optional[str] = None, page: int = 1, size: int = 20
    ) -> ToolResult:
        try:
            db = self._ensure_db()
            (
                items,
                total,
                current_page,
                pages,
            ) = await preference_service.list_preferences(
                db=db,
                user_id=self.user_id,
                module=module,
                page=page,
                size=size,
            )
            return create_tool_response(
                data={
                    "items": [serialize_entity(item, "preference") for item in items],
                    "pagination": {
                        "page": current_page,
                        "size": size,
                        "total": total,
                        "pages": pages,
                    },
                    "meta": {"module": module},
                }
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(
                logger, f"Error listing user preferences: {exc}", sys.exc_info()
            )
            return create_tool_error("Failed to list user preferences", detail=str(exc))


class GetUserPreferenceArgs(BaseModel):
    """Arguments for retrieving a single preference."""

    key: str = Field(..., min_length=1, description="Preference key to retrieve.")
    include_meta: bool = Field(
        True, description="Whether to include metadata (allowed values, defaults)."
    )


class GetUserPreferenceTool(AbstractTool):
    """Tool that fetches a single user preference."""

    name = "get_user_preference"
    description = (
        "Retrieve a specific user preference, optionally with metadata."
        " Read-only operation."
    )
    args_schema = GetUserPreferenceArgs

    async def execute(self, key: str, include_meta: bool = True) -> ToolResult:
        try:
            db = self._ensure_db()
            pref = await preference_service.get_preference(
                db=db,
                user_id=self.user_id,
                key=key,
                with_meta=include_meta,
            )
            if pref is None:
                return create_tool_error(
                    "Preference not found",
                    kind="not_found",
                    detail="Preference key is not registered for this user.",
                )
            return create_tool_response(
                data={"preference": serialize_entity(pref, "preference")}
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(
                logger, f"Error retrieving user preference: {exc}", sys.exc_info()
            )
            return create_tool_error(
                "Failed to retrieve user preference", detail=str(exc)
            )


class SetUserPreferenceArgs(BaseModel):
    """Arguments for setting a user preference."""

    key: str = Field(..., min_length=1, description="Preference key to set.")
    value: Any = Field(..., description="Preference value to persist.")
    module: Optional[str] = Field(
        None,
        description="Optional module override when creating the preference for the first time.",
    )


class SetUserPreferenceTool(AbstractTool):
    """Tool that updates or creates a user preference."""

    name = "set_user_preference"
    description = (
        "Set (create or update) a user preference value, applying normalization rules."
        " Persists the change immediately."
    )
    args_schema = SetUserPreferenceArgs
    metadata = ToolMetadata(
        read_only=False,
        requires_confirmation=False,
        idempotent=False,
        labels=("user_preference", "write"),
        default_timeout=20.0,
    )

    async def execute(
        self, key: str, value: Any, module: Optional[str] = None
    ) -> ToolResult:
        try:
            db = self._ensure_db()
            before_snapshot = await preference_service.get_preference(
                db, user_id=self.user_id, key=key, with_meta=False
            )
            pref = await preference_service.set_preference_value(
                db=db, user_id=self.user_id, key=key, value=value, module=module
            )
            serialized = serialize_entity(pref, "preference")
            audit = audit_for_entity(
                "preferences.set",
                entity_type="user_preference",
                entity_id=getattr(pref, "id", None),
                before_snapshot=before_snapshot,
                after_snapshot=serialized,
                extra={"key": key},
            )
            return create_tool_response(
                data={"preference": serialized},
                audit=audit,
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(
                logger, f"Error setting user preference: {exc}", sys.exc_info()
            )
            return create_tool_error("Failed to set user preference", detail=str(exc))


__all__ = [
    "ListUserPreferencesTool",
    "GetUserPreferenceTool",
    "SetUserPreferenceTool",
]
