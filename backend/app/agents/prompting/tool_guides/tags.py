"""Tool guide definitions for the tags domain."""

from app.agents.prompting.builder import IntentTrigger, ToolArgumentGuide, ToolGuide
from app.agents.prompting.registry import register_tool

register_tool(
    ToolGuide(
        name="create_tag",
        purpose="Create a new tag to categorise people, notes, tasks, visions, etc.",
        arguments=(
            ToolArgumentGuide(
                name="name",
                type_hint="string",
                required=True,
                description="Tag name such as 'family' or 'important'.",
            ),
            ToolArgumentGuide(
                name="entity_type",
                type_hint="string",
                required=False,
                description="Entity type: person, note, task, vision, or general (default).",
                default="general",
            ),
            ToolArgumentGuide(
                name="description",
                type_hint="string",
                required=False,
                description="Optional description explaining the tag's purpose.",
            ),
            ToolArgumentGuide(
                name="color",
                type_hint="string",
                required=False,
                description="Optional hex colour code such as #3B82F6.",
            ),
        ),
        example_arguments={
            "name": "Key Customers",
            "entity_type": "person",
            "description": "Clients that require recurring follow-ups.",
            "color": "#F97316",
        },
        triggers=(
            IntentTrigger(
                text="User wants to add a new category/tag or tidy the tagging system."
            ),
        ),
    )
)


register_tool(
    ToolGuide(
        name="list_tags",
        purpose="List existing tags, optionally filtered by associated entity type.",
        arguments=(
            ToolArgumentGuide(
                name="entity_type",
                type_hint="string",
                required=False,
                description="Optional entity filter: person, note, task, vision, general.",
            ),
        ),
        example_arguments={"entity_type": "task"},
        triggers=(
            IntentTrigger(
                text="User wants to review existing tags before choosing one."
            ),
        ),
    )
)


register_tool(
    ToolGuide(
        name="get_tag_usage",
        purpose="Inspect usage statistics for a tag to understand its coverage.",
        arguments=(
            ToolArgumentGuide(
                name="tag_id",
                type_hint="uuid",
                required=True,
                description="Identifier of the tag to inspect.",
            ),
        ),
        example_arguments={"tag_id": "aaaa1111-bbbb-2222-cccc-333333333333"},
        triggers=(
            IntentTrigger(
                text="User wants to know where a tag is applied or how often it is used."
            ),
        ),
    )
)


register_tool(
    ToolGuide(
        name="update_tag",
        purpose=(
            "Update an existing tag's name, entity type, description, or colour. "
            "Leave fields out to keep them; set description/color to null to clear those optional values."
        ),
        arguments=(
            ToolArgumentGuide(
                name="tag_id",
                type_hint="uuid",
                required=True,
                description="Identifier of the tag to update.",
            ),
            ToolArgumentGuide(
                name="name",
                type_hint="string",
                required=False,
                description="New tag name; leave empty to keep unchanged.",
            ),
            ToolArgumentGuide(
                name="entity_type",
                type_hint="string",
                required=False,
                description="Updated entity type (person, note, task, vision, general).",
            ),
            ToolArgumentGuide(
                name="description",
                type_hint="string",
                required=False,
                description="Updated description for the tag.",
            ),
            ToolArgumentGuide(
                name="color",
                type_hint="string",
                required=False,
                description="Updated hex colour such as #3B82F6.",
            ),
        ),
        example_arguments={
            "tag_id": "aaaa1111-bbbb-2222-cccc-333333333333",
            "name": "vip",
            "description": None,
            "color": "#10B981",
        },
        triggers=(IntentTrigger(text="User wants to rename or adjust a tag."),),
    )
)


register_tool(
    ToolGuide(
        name="delete_tag",
        purpose="Delete a tag.",
        arguments=(
            ToolArgumentGuide(
                name="tag_id",
                type_hint="uuid",
                required=True,
                description="Identifier of the tag to delete.",
            ),
        ),
        example_arguments={
            "tag_id": "cccc1111-bbbb-2222-cccc-333333333333",
        },
        triggers=(
            IntentTrigger(text="User wants to remove a tag from the catalogue."),
        ),
    )
)
