"""Tool guide definitions for the timelog domain."""

from app.agents.prompting.builder import IntentTrigger, ToolArgumentGuide, ToolGuide
from app.agents.prompting.registry import register_tool

register_tool(
    ToolGuide(
        name="list_time_logs",
        purpose="Retrieve time logs within a time window (defaults to the last 7 days).",
        arguments=(
            ToolArgumentGuide(
                name="start",
                type_hint="datetime",
                required=False,
                description="Start datetime (inclusive); defaults to now minus seven days.",
            ),
            ToolArgumentGuide(
                name="end",
                type_hint="datetime",
                required=False,
                description="End datetime (inclusive); defaults to now.",
            ),
            ToolArgumentGuide(
                name="tracking_method",
                type_hint="string",
                required=False,
                description="Optional tracking method filter (manual, automatic, imported).",
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
        example_arguments={
            "start": "2025-10-05T00:00:00+08:00",
            "end": "2025-10-11T23:59:00+08:00",
            "tracking_method": "manual",
            "size": 20,
        },
        triggers=(
            IntentTrigger(
                text="User wants to review recent time allocation (e.g., 'what did I do this week?')."
            ),
        ),
    )
)


register_tool(
    ToolGuide(
        name="create_time_log",
        purpose="Create a new time log entry including location, energy level, tags, etc.",
        arguments=(
            ToolArgumentGuide(
                name="title",
                type_hint="string",
                required=True,
                description="Activity title describing the time block.",
            ),
            ToolArgumentGuide(
                name="start_time",
                type_hint="datetime",
                required=True,
                description="Start time with timezone awareness.",
            ),
            ToolArgumentGuide(
                name="end_time",
                type_hint="datetime",
                required=True,
                description="End time with timezone awareness.",
            ),
            ToolArgumentGuide(
                name="dimension_id",
                type_hint="uuid",
                required=False,
                description="Optional life dimension ID.",
            ),
            ToolArgumentGuide(
                name="tracking_method",
                type_hint="string",
                required=False,
                description="Tracking method; defaults to manual (also accepts automatic/imported).",
                default="manual",
            ),
            ToolArgumentGuide(
                name="location",
                type_hint="string",
                required=False,
                description="Activity location or context description.",
            ),
            ToolArgumentGuide(
                name="energy_level",
                type_hint="int",
                required=False,
                description="Energy level rating 1-5.",
            ),
            ToolArgumentGuide(
                name="notes",
                type_hint="string",
                required=False,
                description="Additional notes or reflections.",
            ),
            ToolArgumentGuide(
                name="tags",
                type_hint="list[string]",
                required=False,
                description="List of tags to categorise the activity.",
                default="[]",
            ),
            ToolArgumentGuide(
                name="task_id",
                type_hint="uuid",
                required=False,
                description="Associated task ID when the time block belongs to a task.",
            ),
            ToolArgumentGuide(
                name="person_ids",
                type_hint="list[uuid]",
                required=False,
                description="List of participant IDs.",
                default="[]",
            ),
        ),
        example_arguments={
            "title": "Draft the quarterly summary report",
            "start_time": "2025-10-11T09:00:00+08:00",
            "end_time": "2025-10-11T11:30:00+08:00",
            "energy_level": 4,
            "notes": "Deep focus session referencing market research data.",
            "tags": ["work", "report"],
        },
        triggers=(
            IntentTrigger(
                text="User records a new activity duration or backfills a past log."
            ),
        ),
    )
)


register_tool(
    ToolGuide(
        name="update_time_log",
        purpose=(
            "Update an existing time log's title, timings, or metadata. "
            "Omit fields to keep their values; use explicit null/[] to clear nullable ones "
            "(dimension_id, location, energy_level, notes, tags, task_id, person_ids)."
        ),
        arguments=(
            ToolArgumentGuide(
                name="event_id",
                type_hint="uuid",
                required=True,
                description="Identifier of the time log entry to update.",
            ),
            ToolArgumentGuide(
                name="title",
                type_hint="string",
                required=False,
                description="Updated title or summary.",
            ),
            ToolArgumentGuide(
                name="start_time",
                type_hint="datetime",
                required=False,
                description="Updated start time with timezone information.",
            ),
            ToolArgumentGuide(
                name="end_time",
                type_hint="datetime",
                required=False,
                description="Updated end time with timezone information.",
            ),
            ToolArgumentGuide(
                name="tracking_method",
                type_hint="string",
                required=False,
                description="Updated tracking method.",
            ),
            ToolArgumentGuide(
                name="location",
                type_hint="string",
                required=False,
                description="Updated location or context.",
            ),
            ToolArgumentGuide(
                name="energy_level",
                type_hint="int",
                required=False,
                description="Updated energy level (1-5).",
            ),
            ToolArgumentGuide(
                name="notes",
                type_hint="string",
                required=False,
                description="Updated notes or reflections.",
            ),
            ToolArgumentGuide(
                name="tags",
                type_hint="list[string]",
                required=False,
                description="Updated tags list.",
                default="[]",
            ),
            ToolArgumentGuide(
                name="task_id",
                type_hint="uuid",
                required=False,
                description="Updated associated task ID.",
            ),
            ToolArgumentGuide(
                name="person_ids",
                type_hint="list[uuid]",
                required=False,
                description="Updated participant list.",
                default="[]",
            ),
        ),
        example_arguments={
            "event_id": "aaaaaaaa-1234-5678-90ab-cccccccccccc",
            "end_time": "2025-10-11T12:00:00+08:00",
            "energy_level": 3,
            "notes": None,
            "location": None,
            "tags": [],
            "task_id": None,
            "person_ids": [],
        },
        triggers=(
            IntentTrigger(
                text="User needs to adjust timing, content, or add notes to an existing log."
            ),
        ),
    )
)


register_tool(
    ToolGuide(
        name="delete_time_log",
        purpose="Delete a time log entry.",
        arguments=(
            ToolArgumentGuide(
                name="event_id",
                type_hint="uuid",
                required=True,
                description="Identifier of the time log to remove.",
            ),
        ),
        example_arguments={
            "event_id": "bbbbbbbb-0000-1111-2222-333333333333",
        },
        triggers=(
            IntentTrigger(
                text="User states that a time log should be removed or undone."
            ),
        ),
    )
)
