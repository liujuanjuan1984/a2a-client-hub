"""Tool guide definitions for the habits domain."""

from app.agents.prompting.builder import IntentTrigger, ToolArgumentGuide, ToolGuide
from app.agents.prompting.registry import register_tool

register_tool(
    ToolGuide(
        name="list_habits",
        purpose="List the user's habits with optional status filtering.",
        arguments=(
            ToolArgumentGuide(
                name="status",
                type_hint="string",
                required=False,
                description="Optional habit status filter: active, completed, paused, expired.",
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
        example_arguments={"status": "active", "page": 1, "size": 10},
        triggers=(
            IntentTrigger(text="User wants to review active or completed habits."),
        ),
    )
)


register_tool(
    ToolGuide(
        name="get_habit_overview",
        purpose="Retrieve a single habit together with its computed statistics.",
        arguments=(
            ToolArgumentGuide(
                name="habit_id",
                type_hint="uuid",
                required=True,
                description="Identifier of the habit to inspect.",
            ),
        ),
        example_arguments={"habit_id": "99999999-1111-2222-3333-444444444444"},
        triggers=(
            IntentTrigger(
                text="User asks for the overall progress or streak of a specific habit."
            ),
        ),
    )
)


register_tool(
    ToolGuide(
        name="create_habit",
        purpose="Create a new habit with a start date, duration, and optional linked task.",
        arguments=(
            ToolArgumentGuide(
                name="title",
                type_hint="string",
                required=True,
                description="Habit title describing the behaviour to build.",
            ),
            ToolArgumentGuide(
                name="start_date",
                type_hint="string",
                required=True,
                description="Start date in ISO format (YYYY-MM-DD).",
            ),
            ToolArgumentGuide(
                name="duration_days",
                type_hint="int",
                required=True,
                description="Duration in days (>=1) representing the habit commitment window.",
            ),
            ToolArgumentGuide(
                name="description",
                type_hint="string",
                required=False,
                description="Optional description such as success criteria or reminders.",
            ),
            ToolArgumentGuide(
                name="task_id",
                type_hint="uuid",
                required=False,
                description="Associated task ID when the habit is tied to a task.",
            ),
        ),
        example_arguments={
            "title": "Read for 30 minutes every evening",
            "start_date": "2025-10-12",
            "duration_days": 30,
            "description": "Capture takeaways and summarize on weekends.",
        },
        triggers=(
            IntentTrigger(text="User wants to establish a new daily or weekly habit."),
        ),
    )
)


register_tool(
    ToolGuide(
        name="update_habit",
        purpose=(
            "Update habit metadata such as title, timeframe, or status (partial update). "
            "Skip parameters you don't want to touch; send null only for nullable fields (description, task_id) to clear them."
        ),
        arguments=(
            ToolArgumentGuide(
                name="habit_id",
                type_hint="uuid",
                required=True,
                description="Identifier of the habit to update.",
            ),
            ToolArgumentGuide(
                name="title",
                type_hint="string",
                required=False,
                description="New habit title.",
            ),
            ToolArgumentGuide(
                name="description",
                type_hint="string",
                required=False,
                description="Updated description or context.",
            ),
            ToolArgumentGuide(
                name="start_date",
                type_hint="string",
                required=False,
                description="Updated start date (YYYY-MM-DD).",
            ),
            ToolArgumentGuide(
                name="duration_days",
                type_hint="int",
                required=False,
                description="Updated duration in days.",
            ),
            ToolArgumentGuide(
                name="status",
                type_hint="string",
                required=False,
                description="Updated habit status (e.g., active, completed, expired).",
            ),
            ToolArgumentGuide(
                name="task_id",
                type_hint="uuid",
                required=False,
                description="New associated task ID.",
            ),
        ),
        example_arguments={
            "habit_id": "55555555-aaaa-bbbb-cccc-666666666666",
            "status": "completed",
            "duration_days": 21,
            "description": "Checked in for 21 straight days and hit the milestone.",
            "task_id": None,
        },
        triggers=(
            IntentTrigger(
                text="User wants to adjust the habit's goal, duration, or status."
            ),
        ),
    )
)


register_tool(
    ToolGuide(
        name="delete_habit",
        purpose="Delete a habit.",
        arguments=(
            ToolArgumentGuide(
                name="habit_id",
                type_hint="uuid",
                required=True,
                description="Habit ID to remove.",
            ),
        ),
        example_arguments={
            "habit_id": "77777777-aaaa-bbbb-cccc-888888888888",
        },
        triggers=(IntentTrigger(text="User explicitly asks to delete a habit."),),
    )
)


register_tool(
    ToolGuide(
        name="log_habit_action",
        purpose="Find a habit action by date and update its status/notes.",
        arguments=(
            ToolArgumentGuide(
                name="habit_id",
                type_hint="uuid",
                required=True,
                description="Habit identifier.",
            ),
            ToolArgumentGuide(
                name="action_date",
                type_hint="string",
                required=True,
                description="Date of the action to update (YYYY-MM-DD).",
            ),
            ToolArgumentGuide(
                name="status",
                type_hint="string",
                required=True,
                description="New action status (pending, done, skip, miss).",
            ),
            ToolArgumentGuide(
                name="notes",
                type_hint="string",
                required=False,
                description="Optional notes describing the check-in.",
            ),
            ToolArgumentGuide(
                name="window_days",
                type_hint="int",
                required=False,
                description="Days to search before/after the date (default 3, max 50).",
                default="3",
            ),
        ),
        example_arguments={
            "habit_id": "12121212-3434-5656-7878-909090909090",
            "action_date": "2025-10-29",
            "status": "done",
            "notes": "Completed a 5 km morning run.",
        },
        triggers=(
            IntentTrigger(
                text='User says "mark yesterday\'s habit as done and add a note."'
            ),
        ),
    )
)
