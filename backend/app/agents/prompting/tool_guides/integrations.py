"""Tool guide definitions for the integrations domain."""

from app.agents.prompting.builder import ToolArgumentGuide, ToolGuide
from app.agents.prompting.registry import register_tool

register_tool(
    ToolGuide(
        name="a2a_agent",
        purpose="Invoke registered external A2A agents to retrieve specialised responses or services.",
        arguments=(
            ToolArgumentGuide(
                name="agent",
                type_hint="string",
                required=False,
                description="Name of the pre-configured A2A agent to call.",
            ),
            ToolArgumentGuide(
                name="agent_url",
                type_hint="string",
                required=False,
                description="Direct service URL for an A2A agent; overrides the configured list.",
            ),
            ToolArgumentGuide(
                name="query",
                type_hint="string",
                required=True,
                description="Query or instruction forwarded to the external agent.",
            ),
            ToolArgumentGuide(
                name="context",
                type_hint="object",
                required=False,
                description="Additional context payload merged into the downstream request.",
                default="{}",
            ),
        ),
        example_arguments={
            "agent": "researcher",
            "query": "Summarise the latest findings about sleep and productivity.",
            "context": {"streaming": False},
        },
    )
)
