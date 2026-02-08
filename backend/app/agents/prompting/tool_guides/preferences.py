"""Tool guide definitions for the preferences domain."""

from app.agents.prompting.builder import IntentTrigger, ToolArgumentGuide, ToolGuide
from app.agents.prompting.registry import register_tool

register_tool(
    ToolGuide(
        name="list_user_preferences",
        purpose="List user preferences with optional module filter and pagination.",
        arguments=(
            ToolArgumentGuide(
                name="module",
                type_hint="string",
                required=False,
                description="Optional module key to limit the results to a specific module.",
            ),
            ToolArgumentGuide(
                name="page",
                type_hint="int",
                required=False,
                description="Page number (1-indexed).",
                default="1",
            ),
            ToolArgumentGuide(
                name="size",
                type_hint="int",
                required=False,
                description="Page size (1-200).",
                default="20",
            ),
        ),
        example_arguments={"module": "notifications", "page": 1, "size": 20},
        triggers=(
            IntentTrigger(text="User wants to review existing preference settings."),
        ),
    )
)


register_tool(
    ToolGuide(
        name="get_user_preference",
        purpose="Retrieve a single preference value, optionally including metadata.",
        arguments=(
            ToolArgumentGuide(
                name="key",
                type_hint="string",
                required=True,
                description="Preference key name.",
            ),
            ToolArgumentGuide(
                name="include_meta",
                type_hint="bool",
                required=False,
                description="Whether to return metadata such as allowed values (default true).",
                default="true",
            ),
        ),
        example_arguments={
            "key": "timeLog.auto_set_task_planning",
            "include_meta": True,
        },
        triggers=(
            IntentTrigger(
                text="User needs the current value or allowed range of a setting."
            ),
        ),
    )
)


register_tool(
    ToolGuide(
        name="set_user_preference",
        purpose="Update or create a user preference value and persist it immediately.",
        arguments=(
            ToolArgumentGuide(
                name="key",
                type_hint="string",
                required=True,
                description="Preference key to set.",
            ),
            ToolArgumentGuide(
                name="value",
                type_hint="any",
                required=True,
                description="New preference value; must satisfy the key's validation rules.",
            ),
            ToolArgumentGuide(
                name="module",
                type_hint="string",
                required=False,
                description="Optional module key when creating the preference for the first time.",
            ),
        ),
        example_arguments={
            "key": "notifications.digest.enabled",
            "value": True,
            "module": "notifications",
        },
        triggers=(
            IntentTrigger(
                text="User wants to enable/disable or modify a specific preference."
            ),
        ),
    )
)
