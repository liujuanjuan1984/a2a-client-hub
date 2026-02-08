"""Tool guide definitions for the notes domain."""

from app.agents.prompting.builder import IntentTrigger, ToolArgumentGuide, ToolGuide
from app.agents.prompting.registry import register_tool

register_tool(
    ToolGuide(
        name="create_note",
        purpose="Create a new note and optionally link it to people, tags, or a task.",
        arguments=(
            ToolArgumentGuide(
                name="content",
                type_hint="string",
                required=True,
                description="The body of the note. Capture the full detail the user wants to record.",
            ),
            ToolArgumentGuide(
                name="person_ids",
                type_hint="list[string]",
                required=False,
                description="Optional list of person IDs to associate relevant contacts.",
                default="[]",
            ),
            ToolArgumentGuide(
                name="tag_ids",
                type_hint="list[string]",
                required=False,
                description="Optional list of tag IDs that categorise the note.",
                default="[]",
            ),
            ToolArgumentGuide(
                name="task_id",
                type_hint="uuid",
                required=False,
                description="Optional task ID when the note is linked to a task.",
            ),
        ),
        example_arguments={
            "content": "Meeting minutes: reviewed OKR progress and scheduled next week's market research follow-up.",
            "tag_ids": ["tag-meeting"],
            "person_ids": ["person-lihua"],
            "task_id": "00000000-0000-0000-0000-000000000000",
        },
        triggers=(
            IntentTrigger(
                text="User asks to record or create a note (e.g., 'log this note')."
            ),
            IntentTrigger(
                text="User shares information that should be stored for later reference."
            ),
        ),
    )
)


register_tool(
    ToolGuide(
        name="update_note",
        purpose=(
            "Update an existing note's content and linked tags, persons, or task. "
            "Skip fields to keep them; send null/[] to clear associations (e.g., task_id, person_ids, tag_ids)."
        ),
        arguments=(
            ToolArgumentGuide(
                name="note_id",
                type_hint="uuid",
                required=True,
                description="Identifier of the note that should be modified.",
            ),
            ToolArgumentGuide(
                name="content",
                type_hint="string",
                required=False,
                description="Updated note body; omit to keep the existing text.",
            ),
            ToolArgumentGuide(
                name="person_ids",
                type_hint="list[string]",
                required=False,
                description="Replacement list of person IDs associated with the note.",
                default="[]",
            ),
            ToolArgumentGuide(
                name="tag_ids",
                type_hint="list[string]",
                required=False,
                description="Replacement list of tag IDs categorising the note.",
                default="[]",
            ),
            ToolArgumentGuide(
                name="task_id",
                type_hint="uuid",
                required=False,
                description="Replacement task ID; pass null to remove the link.",
            ),
        ),
        example_arguments={
            "note_id": "11111111-2222-3333-4444-555555555555",
            "content": "Addendum to the meeting notes: capture follow-up owners.",
            "tag_ids": ["tag-meeting", "tag-followup"],
            "person_ids": ["person-lihua"],
            "task_id": None,
        },
        triggers=(
            IntentTrigger(
                text="User wants to adjust an existing note or its linked metadata."
            ),
        ),
    )
)


register_tool(
    ToolGuide(
        name="get_latest_notes",
        purpose="Fetch the most recent notes in reverse chronological order, optionally filtered by keyword.",
        arguments=(
            ToolArgumentGuide(
                name="limit",
                type_hint="int",
                required=False,
                description="Maximum number of notes to return (1-50).",
                default="5",
            ),
            ToolArgumentGuide(
                name="keyword",
                type_hint="string",
                required=False,
                description="Optional keyword to fuzzy-filter notes by content.",
            ),
        ),
        example_arguments={"limit": 5, "keyword": "health"},
        triggers=(
            IntentTrigger(
                text="User requests a quick recap of latest notes (e.g., 'show my recent notes')."
            ),
            IntentTrigger(
                text="Need to review the most recent update on a theme saved in notes."
            ),
        ),
    )
)


register_tool(
    ToolGuide(
        name="search_notes",
        purpose="Search notes by keyword and return a list of matching entries.",
        arguments=(
            ToolArgumentGuide(
                name="keyword",
                type_hint="string",
                required=True,
                description="Required keyword that should appear in the note body.",
            ),
            ToolArgumentGuide(
                name="limit",
                type_hint="int",
                required=False,
                description="Maximum number of results to return (1-50).",
                default="10",
            ),
        ),
        example_arguments={"keyword": "annual plan", "limit": 10},
        triggers=(
            IntentTrigger(
                text="User asks to find or search a note about a specific topic."
            ),
            IntentTrigger(
                text="Needs to locate historical notes related to a keyword."
            ),
        ),
    )
)


register_tool(
    ToolGuide(
        name="list_notes_by_content",
        purpose="List existing notes whose content exactly matches the provided text (dedup before creating).",
        arguments=(
            ToolArgumentGuide(
                name="content",
                type_hint="string",
                required=True,
                description="Exact note content to match; leading/trailing whitespace will be trimmed.",
            ),
            ToolArgumentGuide(
                name="limit",
                type_hint="int",
                required=False,
                description="Maximum number of results to return (default 5, max 50).",
                default="5",
            ),
            ToolArgumentGuide(
                name="offset",
                type_hint="int",
                required=False,
                description="Result offset for pagination (default 0).",
                default="0",
            ),
        ),
        example_arguments={"content": "昨天和前同事吴昊语音，聊了商业变现闭环。"},
        triggers=(
            IntentTrigger(
                text="Before creating a new note, check if an identical note already exists."
            ),
        ),
    )
)


register_tool(
    ToolGuide(
        name="delete_note",
        purpose="Delete a note.",
        arguments=(
            ToolArgumentGuide(
                name="note_id",
                type_hint="uuid",
                required=True,
                description="Identifier of the note to delete.",
            ),
        ),
        example_arguments={
            "note_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeffffffff",
        },
        triggers=(IntentTrigger(text="User wants to remove or trash a note."),),
    )
)
