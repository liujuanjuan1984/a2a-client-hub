"""Tool guide definitions for the food domain."""

from app.agents.prompting.builder import IntentTrigger, ToolArgumentGuide, ToolGuide
from app.agents.prompting.registry import register_tool

register_tool(
    ToolGuide(
        name="list_foods",
        purpose="Retrieve foods in the catalogue, optionally filtering by keyword or common foods only.",
        arguments=(
            ToolArgumentGuide(
                name="search",
                type_hint="string",
                required=False,
                description="Fuzzy search by food name.",
            ),
            ToolArgumentGuide(
                name="common_only",
                type_hint="bool",
                required=False,
                description="Return only common/shared foods if true.",
                default="false",
            ),
            ToolArgumentGuide(
                name="limit",
                type_hint="int",
                required=False,
                description="Maximum foods to return (1-200).",
                default="20",
            ),
            ToolArgumentGuide(
                name="offset",
                type_hint="int",
                required=False,
                description="Offset for pagination.",
                default="0",
            ),
        ),
        example_arguments={
            "search": "chicken breast",
            "common_only": False,
            "limit": 10,
        },
        triggers=(
            IntentTrigger(
                text="User wants to find nutritional information or log a meal item."
            ),
        ),
    )
)


register_tool(
    ToolGuide(
        name="get_food_detail",
        purpose="Retrieve detailed nutrition information for a specific food item.",
        arguments=(
            ToolArgumentGuide(
                name="food_id",
                type_hint="uuid",
                required=True,
                description="Identifier of the food to inspect.",
            ),
        ),
        example_arguments={"food_id": "90909090-aaaa-bbbb-cccc-808080808080"},
        triggers=(
            IntentTrigger(text="User needs nutrition details for a specific food."),
        ),
    )
)


register_tool(
    ToolGuide(
        name="list_food_entries",
        purpose="List food diary entries by date range or meal type to review intake.",
        arguments=(
            ToolArgumentGuide(
                name="start_date",
                type_hint="string",
                required=False,
                description="Start date (YYYY-MM-DD).",
            ),
            ToolArgumentGuide(
                name="end_date",
                type_hint="string",
                required=False,
                description="End date (YYYY-MM-DD).",
            ),
            ToolArgumentGuide(
                name="meal_type",
                type_hint="string",
                required=False,
                description="Optional meal type filter (breakfast, lunch, dinner, snack, other).",
            ),
            ToolArgumentGuide(
                name="limit",
                type_hint="int",
                required=False,
                description="Maximum entries to return (1-500).",
                default="50",
            ),
            ToolArgumentGuide(
                name="offset",
                type_hint="int",
                required=False,
                description="Offset for pagination.",
                default="0",
            ),
        ),
        example_arguments={
            "start_date": "2025-10-05",
            "end_date": "2025-10-11",
            "meal_type": "dinner",
            "limit": 20,
        },
        triggers=(
            IntentTrigger(text="User wants to review dietary logs for a given period."),
        ),
    )
)


register_tool(
    ToolGuide(
        name="get_food_entry_detail",
        purpose="Inspect the details of a specific food diary entry.",
        arguments=(
            ToolArgumentGuide(
                name="entry_id",
                type_hint="uuid",
                required=True,
                description="Identifier of the food entry.",
            ),
        ),
        example_arguments={"entry_id": "71717171-aaaa-bbbb-cccc-727272727272"},
        triggers=(
            IntentTrigger(
                text="User wants to verify or reference a specific diary entry."
            ),
        ),
    )
)


register_tool(
    ToolGuide(
        name="get_daily_nutrition_summary",
        purpose="Aggregate caloric and macronutrient totals for a specific date.",
        arguments=(
            ToolArgumentGuide(
                name="date",
                type_hint="string",
                required=True,
                description="Target date in YYYY-MM-DD format.",
            ),
        ),
        example_arguments={"date": "2025-10-10"},
        triggers=(
            IntentTrigger(
                text="User wants a daily overview of calories/macros consumed."
            ),
        ),
    )
)
