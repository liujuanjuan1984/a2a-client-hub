"""Tool guide definitions for the persons domain."""

from app.agents.prompting.builder import IntentTrigger, ToolArgumentGuide, ToolGuide
from app.agents.prompting.registry import register_tool

register_tool(
    ToolGuide(
        name="list_persons",
        purpose="List contacts with optional keyword or tag filters to quickly locate people.",
        arguments=(
            ToolArgumentGuide(
                name="search",
                type_hint="string",
                required=False,
                description="Optional keyword to match name or nickname.",
            ),
            ToolArgumentGuide(
                name="tag",
                type_hint="string",
                required=False,
                description="Filter by tag name (case-insensitive).",
            ),
            ToolArgumentGuide(
                name="skip",
                type_hint="int",
                required=False,
                description="Pagination offset (0-1000).",
                default="0",
            ),
            ToolArgumentGuide(
                name="limit",
                type_hint="int",
                required=False,
                description="Maximum number of contacts to return (1-200).",
                default="20",
            ),
        ),
        example_arguments={"search": "Wang", "tag": "colleague", "limit": 10},
        triggers=(
            IntentTrigger(
                text="User wants to browse or filter contacts (e.g., 'find colleagues named Wang')."
            ),
        ),
    )
)


register_tool(
    ToolGuide(
        name="get_person_activities",
        purpose="Aggregate a person's related activities (visions, tasks, events, notes).",
        arguments=(
            ToolArgumentGuide(
                name="person_id",
                type_hint="uuid",
                required=True,
                description="Identifier of the contact to inspect.",
            ),
            ToolArgumentGuide(
                name="page",
                type_hint="int",
                required=False,
                description="Page number (1-1000).",
                default="1",
            ),
            ToolArgumentGuide(
                name="size",
                type_hint="int",
                required=False,
                description="Maximum activities to return (1-200).",
                default="20",
            ),
            ToolArgumentGuide(
                name="activity_type",
                type_hint="string",
                required=False,
                description="Filter by activity type: vision, task, planned_event, actual_event, note.",
            ),
        ),
        example_arguments={
            "person_id": "22222222-aaaa-bbbb-cccc-333333333333",
            "size": 10,
        },
        triggers=(
            IntentTrigger(
                text="User wants to review recent interactions or shared activities with a person."
            ),
        ),
    )
)


register_tool(
    ToolGuide(
        name="create_person",
        purpose="Create a new contact with optional nicknames, birthday, and tags.",
        arguments=(
            ToolArgumentGuide(
                name="name",
                type_hint="string",
                required=False,
                description="Contact name (optional, allows anonymous records).",
            ),
            ToolArgumentGuide(
                name="nicknames",
                type_hint="list[string]",
                required=False,
                description="List of nicknames or aliases.",
                default="[]",
            ),
            ToolArgumentGuide(
                name="birth_date",
                type_hint="string",
                required=False,
                description="Birth date (YYYY-MM-DD).",
            ),
            ToolArgumentGuide(
                name="location",
                type_hint="string",
                required=False,
                description="Location or address information.",
            ),
            ToolArgumentGuide(
                name="tag_ids",
                type_hint="list[uuid]",
                required=False,
                description="List of tag IDs to associate with the person.",
                default="[]",
            ),
        ),
        example_arguments={
            "name": "Alex Lee",
            "nicknames": ["Lex"],
            "birth_date": "1988-03-12",
            "location": "Shanghai",
            "tag_ids": ["tag-friend"],
        },
        triggers=(
            IntentTrigger(
                text="User wants to add a new contact or capture relationship details."
            ),
        ),
    )
)


register_tool(
    ToolGuide(
        name="update_person",
        purpose=(
            "Update an existing contact's name, nicknames, tags, or other details (partial update). "
            "Omit fields to keep them; provide null/[] to clear nullable fields like name, nicknames, birth_date, location, tag_ids."
        ),
        arguments=(
            ToolArgumentGuide(
                name="person_id",
                type_hint="uuid",
                required=True,
                description="Identifier of the contact to update.",
            ),
            ToolArgumentGuide(
                name="name",
                type_hint="string",
                required=False,
                description="Updated name.",
            ),
            ToolArgumentGuide(
                name="nicknames",
                type_hint="list[string]",
                required=False,
                description="Updated list of nicknames.",
                default="[]",
            ),
            ToolArgumentGuide(
                name="birth_date",
                type_hint="string",
                required=False,
                description="Updated birth date (YYYY-MM-DD).",
            ),
            ToolArgumentGuide(
                name="location",
                type_hint="string",
                required=False,
                description="Updated location.",
            ),
            ToolArgumentGuide(
                name="tag_ids",
                type_hint="list[uuid]",
                required=False,
                description="Updated list of associated tag IDs.",
                default="[]",
            ),
        ),
        example_arguments={
            "person_id": "44444444-aaaa-bbbb-cccc-555555555555",
            "name": "Alex Lee",
            "location": "Hangzhou",
            "nicknames": [],
            "tag_ids": ["tag-family", "tag-weekly"],
        },
        triggers=(
            IntentTrigger(
                text="User wants to update a contact's name, tags, or important dates."
            ),
        ),
    )
)


register_tool(
    ToolGuide(
        name="delete_person",
        purpose="Delete a contact.",
        arguments=(
            ToolArgumentGuide(
                name="person_id",
                type_hint="uuid",
                required=True,
                description="Identifier of the contact to remove.",
            ),
        ),
        example_arguments={
            "person_id": "66666666-aaaa-bbbb-cccc-777777777777",
        },
        triggers=(
            IntentTrigger(text="User explicitly asks to delete a contact record."),
        ),
    )
)


register_tool(
    ToolGuide(
        name="get_person_detail",
        purpose="Retrieve the full profile of a contact, including tags and anniversaries.",
        arguments=(
            ToolArgumentGuide(
                name="person_id",
                type_hint="uuid",
                required=True,
                description="Identifier of the contact to look up.",
            ),
        ),
        example_arguments={"person_id": "88888888-aaaa-bbbb-cccc-999999999999"},
        triggers=(
            IntentTrigger(
                text="User needs to review a contact's background details or key notes."
            ),
        ),
    )
)


register_tool(
    ToolGuide(
        name="create_anniversary",
        purpose="Create a commemorative date (e.g., first met, wedding) for a contact.",
        arguments=(
            ToolArgumentGuide(
                name="person_id",
                type_hint="uuid",
                required=True,
                description="Identifier of the contact the anniversary belongs to.",
            ),
            ToolArgumentGuide(
                name="name",
                type_hint="string",
                required=True,
                description="Anniversary name such as 'Wedding Anniversary'.",
            ),
            ToolArgumentGuide(
                name="date",
                type_hint="string",
                required=True,
                description="Anniversary date in YYYY-MM-DD format.",
            ),
        ),
        example_arguments={
            "person_id": "11111111-2222-3333-4444-555555555555",
            "name": "First Met",
            "date": "2015-06-01",
        },
        triggers=(
            IntentTrigger(
                text="User wants to record an important date related to a person."
            ),
        ),
    )
)


register_tool(
    ToolGuide(
        name="list_anniversaries",
        purpose="List all anniversaries tied to a contact.",
        arguments=(
            ToolArgumentGuide(
                name="person_id",
                type_hint="uuid",
                required=True,
                description="Identifier of the contact to inspect.",
            ),
        ),
        example_arguments={"person_id": "11111111-2222-3333-4444-555555555555"},
        triggers=(
            IntentTrigger(
                text="User asks what anniversaries or important dates a person has."
            ),
        ),
    )
)


register_tool(
    ToolGuide(
        name="delete_anniversary",
        purpose="Delete a specific anniversary for a contact (irreversible).",
        arguments=(
            ToolArgumentGuide(
                name="person_id",
                type_hint="uuid",
                required=True,
                description="Identifier of the contact the anniversary belongs to.",
            ),
            ToolArgumentGuide(
                name="anniversary_id",
                type_hint="uuid",
                required=True,
                description="Identifier of the anniversary to remove.",
            ),
        ),
        example_arguments={
            "person_id": "11111111-2222-3333-4444-555555555555",
            "anniversary_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        },
        triggers=(
            IntentTrigger(
                text="User wants to remove an incorrect or outdated anniversary."
            ),
        ),
    )
)


register_tool(
    ToolGuide(
        name="update_anniversary",
        purpose=(
            "Update an existing anniversary's name or date for a contact. Omit whichever field "
            "should remain as-is; values cannot be cleared via null—provide a new string when changing them."
        ),
        arguments=(
            ToolArgumentGuide(
                name="person_id",
                type_hint="uuid",
                required=True,
                description="Identifier of the contact the anniversary belongs to.",
            ),
            ToolArgumentGuide(
                name="anniversary_id",
                type_hint="uuid",
                required=True,
                description="Identifier of the anniversary to update.",
            ),
            ToolArgumentGuide(
                name="name",
                type_hint="string",
                required=False,
                description="Updated anniversary name.",
            ),
            ToolArgumentGuide(
                name="date",
                type_hint="string",
                required=False,
                description="Updated anniversary date (YYYY-MM-DD).",
            ),
        ),
        example_arguments={
            "person_id": "11111111-2222-3333-4444-555555555555",
            "anniversary_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "name": "Engagement",
            "date": "2022-10-01",
        },
        triggers=(
            IntentTrigger(
                text="User wants to change an anniversary name or date for a contact."
            ),
        ),
    )
)
