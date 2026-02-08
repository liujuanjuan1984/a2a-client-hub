"""Tool guide definitions for the visions domain."""

from app.agents.prompting.builder import IntentTrigger, ToolArgumentGuide, ToolGuide
from app.agents.prompting.registry import register_tool

register_tool(
    ToolGuide(
        name="list_visions",
        purpose="List visions, optionally filtered by status, to support planning reviews.",
        arguments=(
            ToolArgumentGuide(
                name="status",
                type_hint="string",
                required=False,
                description="Optional vision status filter: active, archived, or fruit.",
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
                description="Maximum visions to return (1-200).",
                default="20",
            ),
        ),
        example_arguments={"status": "active", "limit": 20},
        triggers=(
            IntentTrigger(
                text="User wants to review current visions or filter by a specific status."
            ),
        ),
    )
)


register_tool(
    ToolGuide(
        name="get_vision_detail",
        purpose="Retrieve vision details, optionally including the full task hierarchy.",
        arguments=(
            ToolArgumentGuide(
                name="vision_id",
                type_hint="uuid",
                required=True,
                description="Identifier of the vision to inspect.",
            ),
            ToolArgumentGuide(
                name="include_tasks",
                type_hint="bool",
                required=False,
                description="Whether to include the vision's task hierarchy (default false).",
                default="false",
            ),
        ),
        example_arguments={
            "vision_id": "10101010-aaaa-bbbb-cccc-121212121212",
            "include_tasks": True,
        },
        triggers=(
            IntentTrigger(
                text="User needs detailed insight into a vision or its task breakdown."
            ),
        ),
    )
)


register_tool(
    ToolGuide(
        name="create_vision",
        purpose="Create a new vision with optional dimension and people associations.",
        arguments=(
            ToolArgumentGuide(
                name="name",
                type_hint="string",
                required=True,
                description="Vision name summarising the long-term goal.",
            ),
            ToolArgumentGuide(
                name="description",
                type_hint="string",
                required=False,
                description="Detailed description or significance of the vision.",
            ),
            ToolArgumentGuide(
                name="dimension_id",
                type_hint="uuid",
                required=False,
                description="Default dimension ID for the vision.",
            ),
            ToolArgumentGuide(
                name="person_ids",
                type_hint="list[uuid]",
                required=False,
                description="List of person IDs closely tied to the vision.",
                default="[]",
            ),
        ),
        example_arguments={
            "name": "Build a sustainable product growth engine",
            "description": "Set data-driven growth targets for the next three quarters.",
            "dimension_id": "20202020-aaaa-bbbb-cccc-303030303030",
            "person_ids": ["person-product", "person-growth"],
        },
        triggers=(
            IntentTrigger(text="User is defining a new long-term goal or vision."),
        ),
    )
)


register_tool(
    ToolGuide(
        name="update_vision",
        purpose=(
            "Update a vision's name, description, status, dimension, or associated people. "
            "Omit fields to keep them; for nullable fields (description, dimension_id, person_ids) "
            "send null/[] to clear the stored values."
        ),
        arguments=(
            ToolArgumentGuide(
                name="vision_id",
                type_hint="uuid",
                required=True,
                description="Identifier of the vision to update.",
            ),
            ToolArgumentGuide(
                name="name",
                type_hint="string",
                required=False,
                description="Updated vision name.",
            ),
            ToolArgumentGuide(
                name="description",
                type_hint="string",
                required=False,
                description="Updated vision description.",
            ),
            ToolArgumentGuide(
                name="status",
                type_hint="string",
                required=False,
                description="Updated status such as active, archived, or fruit.",
            ),
            ToolArgumentGuide(
                name="dimension_id",
                type_hint="uuid",
                required=False,
                description="Updated default dimension ID.",
            ),
            ToolArgumentGuide(
                name="person_ids",
                type_hint="list[uuid]",
                required=False,
                description="Updated list of associated person IDs.",
                default="[]",
            ),
        ),
        example_arguments={
            "vision_id": "40404040-aaaa-bbbb-cccc-505050505050",
            "status": "archived",
            "description": None,
            "dimension_id": None,
            "person_ids": [],
        },
        triggers=(
            IntentTrigger(
                text="User wants to adjust a vision's status or update its details."
            ),
        ),
    )
)


register_tool(
    ToolGuide(
        name="delete_vision",
        purpose="Delete a vision.",
        arguments=(
            ToolArgumentGuide(
                name="vision_id",
                type_hint="uuid",
                required=True,
                description="Identifier of the vision to delete.",
            ),
        ),
        example_arguments={
            "vision_id": "60606060-aaaa-bbbb-cccc-707070707070",
        },
        triggers=(
            IntentTrigger(
                text="User wants to remove a vision or archive it permanently."
            ),
        ),
    )
)
