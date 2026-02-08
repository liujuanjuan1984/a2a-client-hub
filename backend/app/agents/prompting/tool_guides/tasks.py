"""Tool guide definitions for the tasks domain."""

from app.agents.prompting.builder import IntentTrigger, ToolArgumentGuide, ToolGuide
from app.agents.prompting.registry import register_tool

register_tool(
    ToolGuide(
        name="list_tasks_by_planning_cycle",
        purpose="List tasks for a specific planning cycle (day/week/month/year) to review progress.",
        arguments=(
            ToolArgumentGuide(
                name="planning_cycle_type",
                type_hint="string",
                required=True,
                description="Planning cycle type: day, week, month, or year.",
            ),
            ToolArgumentGuide(
                name="planning_cycle_start_date",
                type_hint="string",
                required=True,
                description="Start date of the cycle in ISO format (YYYY-MM-DD).",
            ),
            ToolArgumentGuide(
                name="skip",
                type_hint="int",
                required=False,
                description="Offset for pagination (0-1000).",
                default="0",
            ),
            ToolArgumentGuide(
                name="limit",
                type_hint="int",
                required=False,
                description="Maximum number of tasks to return (1-500).",
                default="50",
            ),
        ),
        example_arguments={
            "planning_cycle_type": "week",
            "planning_cycle_start_date": "2025-10-06",
            "skip": 0,
            "limit": 20,
        },
        triggers=(
            IntentTrigger(
                text="User asks for tasks for this week/month or wants a cycle review."
            ),
            IntentTrigger(
                text="Needs a structured list of tasks for a specific planning window."
            ),
        ),
    )
)


register_tool(
    ToolGuide(
        name="list_tasks_by_vision_and_status",
        purpose="List tasks by vision and optional status to focus on strategic goals.",
        arguments=(
            ToolArgumentGuide(
                name="vision_id",
                type_hint="uuid",
                required=True,
                description="Vision ID used to scope the task list.",
            ),
            ToolArgumentGuide(
                name="status",
                type_hint="string",
                required=False,
                description="Optional status filter such as todo, in_progress, done, etc.",
            ),
            ToolArgumentGuide(
                name="skip",
                type_hint="int",
                required=False,
                description="Offset for pagination (0-1000).",
                default="0",
            ),
            ToolArgumentGuide(
                name="limit",
                type_hint="int",
                required=False,
                description="Maximum number of tasks to return (1-500).",
                default="50",
            ),
        ),
        example_arguments={
            "vision_id": "11111111-2222-3333-4444-555555555555",
            "status": "in_progress",
            "skip": 0,
            "limit": 20,
        },
        triggers=(
            IntentTrigger(
                text="User wants to review progress of a specific vision's tasks."
            ),
            IntentTrigger(
                text="Needs to filter tasks by status, e.g., 'incomplete tasks under this vision'."
            ),
        ),
    )
)


register_tool(
    ToolGuide(
        name="get_task_detail",
        purpose="Retrieve the detail of a task, optionally including subtasks.",
        arguments=(
            ToolArgumentGuide(
                name="task_id",
                type_hint="uuid",
                required=True,
                description="Identifier of the target task.",
            ),
            ToolArgumentGuide(
                name="include_subtasks",
                type_hint="bool",
                required=False,
                description="Whether to include subtasks; defaults to true.",
                default="true",
            ),
        ),
        example_arguments={
            "task_id": "aaaa0000-bbbb-cccc-dddd-eeeeffffffff",
            "include_subtasks": True,
        },
        triggers=(
            IntentTrigger(
                text="User wants to inspect the detail or subtasks of a specific task."
            ),
        ),
    )
)


register_tool(
    ToolGuide(
        name="create_task",
        purpose="Create a new task with optional priority, planning cycle, and associations.",
        arguments=(
            ToolArgumentGuide(
                name="content",
                type_hint="string",
                required=True,
                description="Task title or description summarising the work to be done.",
            ),
            ToolArgumentGuide(
                name="vision_id",
                type_hint="uuid",
                required=True,
                description="Vision ID to anchor the task under the correct goal.",
            ),
            ToolArgumentGuide(
                name="parent_task_id",
                type_hint="uuid",
                required=False,
                description="Parent task ID when creating a subtask.",
            ),
            ToolArgumentGuide(
                name="notes",
                type_hint="string",
                required=False,
                description="Additional notes such as acceptance criteria or context.",
            ),
            ToolArgumentGuide(
                name="priority",
                type_hint="int",
                required=False,
                description="Priority score; higher numbers mean higher priority (default 0).",
                default="0",
            ),
            ToolArgumentGuide(
                name="estimated_effort",
                type_hint="int",
                required=False,
                description="Estimated effort in minutes.",
            ),
            ToolArgumentGuide(
                name="planning_cycle_type",
                type_hint="string",
                required=False,
                description="Optional planning cycle type (year/month/week/day).",
            ),
            ToolArgumentGuide(
                name="planning_cycle_start_date",
                type_hint="string",
                required=False,
                description="Start date of the cycle in ISO format.",
            ),
            ToolArgumentGuide(
                name="planning_cycle_days",
                type_hint="int",
                required=False,
                description="Duration of the planning cycle in days (positive integer).",
            ),
            ToolArgumentGuide(
                name="display_order",
                type_hint="int",
                required=False,
                description="Display order within the same parent (default 0).",
                default="0",
            ),
            ToolArgumentGuide(
                name="person_ids",
                type_hint="list[uuid]",
                required=False,
                description="List of person IDs linked to the task.",
                default="[]",
            ),
        ),
        example_arguments={
            "content": "Complete the quarterly market research report",
            "vision_id": "12345678-aaaa-bbbb-cccc-1234567890ab",
            "priority": 2,
            "estimated_effort": 240,
            "planning_cycle_type": "month",
            "planning_cycle_start_date": "2025-10-01",
            "person_ids": ["person-marketing"],
        },
        triggers=(
            IntentTrigger(text="User explicitly asks to create or add a task."),
            IntentTrigger(
                text="User plans a new action item with target or timeframe."
            ),
        ),
    )
)


register_tool(
    ToolGuide(
        name="delete_task",
        purpose="Delete a task.",
        arguments=(
            ToolArgumentGuide(
                name="task_id",
                type_hint="uuid",
                required=True,
                description="Identifier of the task to delete.",
            ),
        ),
        example_arguments={
            "task_id": "bbbb0000-bbbb-cccc-dddd-eeeeffffffff",
        },
        triggers=(IntentTrigger(text="User wants to remove or archive a task."),),
    )
)


register_tool(
    ToolGuide(
        name="update_task",
        purpose=(
            "Update an existing task's fields such as status, notes, or planning info. "
            "Leave any field out to keep it unchanged; send explicit null/[] to clear nullable fields "
            "(notes, estimated_effort, planning_cycle_*, parent_task_id, person_ids)."
        ),
        arguments=(
            ToolArgumentGuide(
                name="task_id",
                type_hint="uuid",
                required=True,
                description="Identifier of the task to update.",
            ),
            ToolArgumentGuide(
                name="status",
                type_hint="string",
                required=False,
                description="New task status such as todo, in_progress, or done.",
            ),
            ToolArgumentGuide(
                name="content",
                type_hint="string",
                required=False,
                description="Updated task title or description.",
            ),
            ToolArgumentGuide(
                name="notes",
                type_hint="string",
                required=False,
                description="Additional notes or progress comments.",
            ),
            ToolArgumentGuide(
                name="priority",
                type_hint="int",
                required=False,
                description="Updated priority score; higher means more important.",
            ),
            ToolArgumentGuide(
                name="estimated_effort",
                type_hint="int",
                required=False,
                description="Updated estimated effort in minutes.",
            ),
            ToolArgumentGuide(
                name="planning_cycle_type",
                type_hint="string",
                required=False,
                description="New planning cycle type, if the cadence changes.",
            ),
            ToolArgumentGuide(
                name="planning_cycle_start_date",
                type_hint="string",
                required=False,
                description="Updated planning cycle start date (YYYY-MM-DD).",
            ),
            ToolArgumentGuide(
                name="planning_cycle_days",
                type_hint="int",
                required=False,
                description="Updated length of the planning cycle in days.",
            ),
            ToolArgumentGuide(
                name="parent_task_id",
                type_hint="uuid",
                required=False,
                description="Set when re-parenting the task.",
            ),
            ToolArgumentGuide(
                name="person_ids",
                type_hint="list[uuid]",
                required=False,
                description="Updated list of associated people.",
                default="[]",
            ),
        ),
        example_arguments={
            "task_id": "fedcba98-7654-3210-fedc-ba9876543210",
            "status": "in_progress",
            "notes": None,
            "planning_cycle_type": None,
            "planning_cycle_start_date": None,
            "planning_cycle_days": None,
            "parent_task_id": None,
            "person_ids": [],
        },
        triggers=(
            IntentTrigger(
                text="User requests to update status, progress, or assignees of a task."
            ),
            IntentTrigger(
                text="Needs to adjust priority or planning information of an existing task."
            ),
        ),
    )
)
