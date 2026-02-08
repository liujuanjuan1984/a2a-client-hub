import textwrap

from app.agents.prompting.builder import (
    PROMPT_TEMPLATE_VERSION,
    AgentPromptConfig,
    PromptBuilder,
    ToolArgumentGuide,
    ToolGuide,
)


def _make_builder(tool_usage_guidance=None):
    guide = ToolGuide(
        name="a2a_agent",
        purpose="Call external A2A agents",
        arguments=(
            ToolArgumentGuide(
                name="agent",
                type_hint="string",
                required=False,
                description="Configured agent name",
            ),
        ),
        example_arguments={"agent": "demo"},
    )
    config = AgentPromptConfig(
        role="Test role",
        tool_names=("a2a_agent",),
        response_guidance="Respond with clarity.",
        fallback_guidance="Explain limitations.",
        tool_usage_guidance=tool_usage_guidance,
    )
    return PromptBuilder(
        tool_guides={"a2a_agent": guide}, agent_configs={"test": config}
    )


def test_prompt_builder_emits_version_and_metadata():
    builder = _make_builder(tool_usage_guidance=("- Use tools sparingly.",))
    result = builder.build("test")

    assert result.version == PROMPT_TEMPLATE_VERSION
    assert "Operational Constraints" in result.text
    assert "- Use tools sparingly." in result.text
    assert "Tool: a2a_agent" in result.text


def test_prompt_builder_renders_examples():
    builder = _make_builder()
    result = builder.build("test")

    assert "Example Call:" in result.text
    assert (
        textwrap.dedent(
            """```json\n{\n  \"tool_name\": \"a2a_agent\",\n  \"arguments\": {\n    \"agent\": \"demo\"\n  }\n}\n```"""
        ).strip()
        in result.text
    )
