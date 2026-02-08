"""Food-related tools exposed to the agent layer."""

import sys
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.agents.tools.base import AbstractTool
from app.agents.tools.responses import (
    ToolResult,
    create_tool_error,
    create_tool_response,
    serialize_entity,
)
from app.core.logging import get_logger, log_exception
from app.handlers import foods as food_service
from app.handlers.foods import (
    FoodNotFoundError,
    FoodOperationNotAllowedError,
    FoodPermissionDeniedError,
)

logger = get_logger(__name__)


class ListFoodsArgs(BaseModel):
    """Arguments for listing foods."""

    search: Optional[str] = Field(
        None, description="Optional keyword to search by name."
    )
    common_only: bool = Field(
        False, description="Whether to only return common/shared foods."
    )
    limit: int = Field(
        20,
        ge=1,
        le=200,
        description="Maximum number of foods to return (1-200).",
    )
    offset: int = Field(0, ge=0, description="Number of records to skip.")


class ListFoodsTool(AbstractTool):
    """Tool that lists foods accessible to the current user."""

    name = "list_foods"
    description = (
        "List foods with optional search and common-food filters."
        " This is a read-only lookup tool."
    )
    args_schema = ListFoodsArgs

    async def execute(
        self,
        search: Optional[str] = None,
        common_only: bool = False,
        limit: int = 20,
        offset: int = 0,
    ) -> ToolResult:
        try:
            db = self._ensure_db()
            foods = await food_service.list_foods(
                db=db,
                user_id=self.user_id,
                search=search,
                common_only=common_only,
                limit=limit,
                offset=offset,
            )
            return create_tool_response(
                data={
                    "foods": [serialize_entity(food, "food") for food in foods],
                    "count": len(foods),
                    "limit": limit,
                    "offset": offset,
                    "search": search,
                    "common_only": common_only,
                }
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(logger, f"Error listing foods: {exc}", sys.exc_info())
            return create_tool_error("Failed to list foods", detail=str(exc))


class GetFoodDetailArgs(BaseModel):
    """Arguments for retrieving a food item."""

    food_id: UUID = Field(..., description="Identifier of the food to retrieve.")


class GetFoodDetailTool(AbstractTool):
    """Tool that fetches details for a specific food item."""

    name = "get_food_detail"
    description = (
        "Retrieve detailed nutritional information for a single food."
        " Read-only helper for meal planning."
    )
    args_schema = GetFoodDetailArgs

    async def execute(self, food_id: UUID) -> ToolResult:
        try:
            db = self._ensure_db()
            food = await food_service.get_food(
                db=db, user_id=self.user_id, food_id=food_id
            )
            if food is None:
                raise FoodNotFoundError("Food not found")
            return create_tool_response(data={"food": serialize_entity(food, "food")})
        except (
            FoodNotFoundError,
            FoodPermissionDeniedError,
            FoodOperationNotAllowedError,
        ) as exc:
            return create_tool_error(
                "Food not accessible",
                kind="not_found",
                detail=str(exc),
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(
                logger, f"Error retrieving food detail: {exc}", sys.exc_info()
            )
            return create_tool_error("Failed to retrieve food detail", detail=str(exc))


__all__ = ["ListFoodsTool", "GetFoodDetailTool"]
