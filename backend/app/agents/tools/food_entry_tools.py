"""Food entry tools exposed to the agent layer."""

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
from app.handlers import food_entries as food_entry_service
from app.handlers.food_entries import (
    FoodEntryNotFoundError,
    InvalidDateError,
    InvalidMealTypeError,
)

logger = get_logger(__name__)


class ListFoodEntriesArgs(BaseModel):
    """Arguments for listing food diary entries."""

    start_date: Optional[str] = Field(
        None, description="Filter entries on or after this date (YYYY-MM-DD)."
    )
    end_date: Optional[str] = Field(
        None, description="Filter entries on or before this date (YYYY-MM-DD)."
    )
    meal_type: Optional[str] = Field(
        None,
        description="Optional meal type (breakfast, lunch, dinner, snack, other).",
    )
    limit: int = Field(
        50,
        ge=1,
        le=500,
        description="Maximum number of food entries to return (1-500).",
    )
    offset: int = Field(0, ge=0, description="Number of records to skip.")


class ListFoodEntriesTool(AbstractTool):
    """Tool that lists food entries with optional date and meal filters."""

    name = "list_food_entries"
    description = (
        "List food diary entries for the current user."
        " This tool is read-only and does not modify any data."
    )
    args_schema = ListFoodEntriesArgs

    async def execute(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        meal_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ToolResult:
        try:
            db = self._ensure_db()
            entries = await food_entry_service.list_food_entries(
                db=db,
                user_id=self.user_id,
                start_date=start_date,
                end_date=end_date,
                meal_type=meal_type,
                limit=limit,
                offset=offset,
            )
            return create_tool_response(
                data={
                    "entries": [
                        serialize_entity(entry, "food_entry") for entry in entries
                    ],
                    "count": len(entries),
                    "limit": limit,
                    "offset": offset,
                    "start_date": start_date,
                    "end_date": end_date,
                    "meal_type": meal_type,
                }
            )
        except InvalidMealTypeError as exc:
            return create_tool_error(
                "Invalid meal type",
                kind="validation_error",
                detail=str(exc),
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(logger, f"Error listing food entries: {exc}", sys.exc_info())
            return create_tool_error("Failed to list food entries", detail=str(exc))


class GetFoodEntryDetailArgs(BaseModel):
    """Arguments for retrieving a single food entry."""

    entry_id: UUID = Field(..., description="Identifier of the food entry.")


class GetFoodEntryDetailTool(AbstractTool):
    """Tool that fetches details for a specific food diary entry."""

    name = "get_food_entry_detail"
    description = (
        "Retrieve information about a single food diary entry."
        " Read-only helper for diary inspections."
    )
    args_schema = GetFoodEntryDetailArgs

    async def execute(self, entry_id: UUID) -> ToolResult:
        try:
            db = self._ensure_db()
            entry = await food_entry_service.get_food_entry(
                db=db, user_id=self.user_id, entry_id=entry_id
            )
            return create_tool_response(
                data={"entry": serialize_entity(entry, "food_entry")}
            )
        except FoodEntryNotFoundError as exc:
            return create_tool_error(
                "Food entry not found",
                kind="not_found",
                detail=str(exc),
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(logger, f"Error retrieving food entry: {exc}", sys.exc_info())
            return create_tool_error("Failed to retrieve food entry", detail=str(exc))


class GetDailyNutritionSummaryArgs(BaseModel):
    """Arguments for retrieving a daily nutrition summary."""

    date: str = Field(..., description="Date to summarize (YYYY-MM-DD).")


class GetDailyNutritionSummaryTool(AbstractTool):
    """Tool that summarizes nutrition totals for a specific day."""

    name = "get_daily_nutrition_summary"
    description = (
        "Calculate caloric and macronutrient totals for a specific date."
        " Aggregation only; underlying entries remain unchanged."
    )
    args_schema = GetDailyNutritionSummaryArgs

    async def execute(self, date: str) -> ToolResult:
        try:
            db = self._ensure_db()
            summary = await food_entry_service.get_daily_nutrition_summary(
                db=db, user_id=self.user_id, date_str=date
            )
            return create_tool_response(
                data={"summary": serialize_entity(summary, "daily_nutrition")}
            )
        except InvalidDateError as exc:
            return create_tool_error(
                "Invalid date",
                kind="validation_error",
                detail=str(exc),
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_exception(
                logger, f"Error retrieving nutrition summary: {exc}", sys.exc_info()
            )
            return create_tool_error(
                "Failed to retrieve nutrition summary", detail=str(exc)
            )


__all__ = [
    "ListFoodEntriesTool",
    "GetFoodEntryDetailTool",
    "GetDailyNutritionSummaryTool",
]
