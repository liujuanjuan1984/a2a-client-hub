from __future__ import annotations

from app.features.hub_assistant.shared.capability_catalog import (
    ADMIN_HUB_AGENTS_LIST,
    HUB_ASSISTANT_AGENTS_CHECK_HEALTH,
    HUB_ASSISTANT_AGENTS_CREATE,
    HUB_ASSISTANT_AGENTS_START_SESSIONS,
    HUB_ASSISTANT_FOLLOWUPS_GET,
    HUB_ASSISTANT_FOLLOWUPS_SET_SESSIONS,
    HUB_ASSISTANT_JOBS_CREATE,
    HUB_ASSISTANT_JOBS_UPDATE_SCHEDULE,
    HUB_ASSISTANT_SESSIONS_GET_LATEST_MESSAGES,
    HUB_ASSISTANT_SESSIONS_SEND_MESSAGE,
)
from app.features.hub_assistant.shared.hub_assistant_tool_contract import (
    build_hub_assistant_tool_definition,
    list_hub_assistant_tool_definitions,
)
from app.features.hub_assistant.shared.tool_gateway import HubAssistantSurface


def test_build_hub_assistant_tool_definition_exposes_operation_schema() -> None:
    definition = build_hub_assistant_tool_definition(HUB_ASSISTANT_JOBS_UPDATE_SCHEDULE)

    assert definition.operation_id == "hub_assistant.jobs.update_schedule"
    assert definition.tool_name == "hub_assistant.jobs.update_schedule"
    assert definition.confirmation_policy.value == "required"
    assert definition.input_json_schema["type"] == "object"
    assert definition.input_json_schema["additionalProperties"] is False
    assert definition.input_json_schema["properties"]["task_id"]["type"] == "string"
    assert (
        definition.input_json_schema["properties"]["time_point"]["anyOf"][0]["type"]
        == "object"
    )


def test_list_hub_assistant_tool_definitions_filters_by_surface() -> None:
    definitions = list_hub_assistant_tool_definitions(
        surface=HubAssistantSurface.WEB_AGENT,
    )

    operation_ids = {item.operation_id for item in definitions}

    assert "hub_assistant.jobs.list" in operation_ids
    assert "hub_assistant.agents.create" in operation_ids
    assert "hub_assistant.jobs.delete" in operation_ids
    assert "hub_assistant.followups.get" in operation_ids
    assert "hub_assistant.followups.set_sessions" in operation_ids
    assert "hub_assistant.sessions.archive" in operation_ids
    assert "hub_assistant.sessions.get" in operation_ids
    assert "hub_assistant.sessions.get_latest_messages" in operation_ids
    assert "hub_assistant.sessions.send_message" in operation_ids
    assert "hub_assistant.agents.update_config" in operation_ids
    assert "hub_assistant.agents.start_sessions" in operation_ids
    assert "admin.agents.list" not in operation_ids


def test_build_hub_assistant_tool_definition_supports_agent_create() -> None:
    definition = build_hub_assistant_tool_definition(HUB_ASSISTANT_AGENTS_CREATE)

    assert definition.operation_id == "hub_assistant.agents.create"
    assert definition.tool_name == "hub_assistant.agents.create"
    assert definition.confirmation_policy.value == "required"
    assert definition.input_json_schema["properties"]["card_url"]["type"] == "string"


def test_build_hub_assistant_tool_definition_supports_agent_health_check() -> None:
    definition = build_hub_assistant_tool_definition(HUB_ASSISTANT_AGENTS_CHECK_HEALTH)

    assert definition.operation_id == "hub_assistant.agents.check_health"
    assert definition.tool_name == "hub_assistant.agents.check_health"
    assert definition.confirmation_policy.value == "required"
    assert definition.input_json_schema["properties"]["force"]["type"] == "boolean"


def test_build_hub_assistant_tool_definition_supports_session_send_message() -> None:
    definition = build_hub_assistant_tool_definition(
        HUB_ASSISTANT_SESSIONS_SEND_MESSAGE
    )

    assert definition.operation_id == "hub_assistant.sessions.send_message"
    assert definition.tool_name == "hub_assistant.sessions.send_message"
    assert definition.confirmation_policy.value == "required"
    assert definition.input_json_schema["properties"]["conversation_ids"]["type"] == (
        "array"
    )
    assert definition.input_json_schema["properties"]["message"]["type"] == "string"


def test_build_hub_assistant_tool_definition_supports_follow_up_tools() -> None:
    get_definition = build_hub_assistant_tool_definition(HUB_ASSISTANT_FOLLOWUPS_GET)
    set_definition = build_hub_assistant_tool_definition(
        HUB_ASSISTANT_FOLLOWUPS_SET_SESSIONS
    )

    assert get_definition.operation_id == "hub_assistant.followups.get"
    assert get_definition.tool_name == "hub_assistant.followups.get"
    assert get_definition.confirmation_policy.value == "none"
    assert get_definition.input_json_schema["properties"] == {}
    assert "auto-tracked delegated targets" in get_definition.description

    assert set_definition.operation_id == "hub_assistant.followups.set_sessions"
    assert set_definition.tool_name == "hub_assistant.followups.set_sessions"
    assert set_definition.confirmation_policy.value == "none"
    assert (
        "Override the current tracked target conversation ids"
        in set_definition.description
    )
    assert (
        set_definition.input_json_schema["properties"]["conversation_ids"]["type"]
        == "array"
    )


def test_build_hub_assistant_tool_definition_supports_session_get_latest_messages() -> (
    None
):
    definition = build_hub_assistant_tool_definition(
        HUB_ASSISTANT_SESSIONS_GET_LATEST_MESSAGES
    )

    assert definition.operation_id == "hub_assistant.sessions.get_latest_messages"
    assert definition.tool_name == "hub_assistant.sessions.get_latest_messages"
    assert definition.confirmation_policy.value == "none"
    assert definition.input_json_schema["properties"]["conversation_ids"]["type"] == (
        "array"
    )
    assert definition.input_json_schema["properties"]["limit_per_session"]["type"] == (
        "integer"
    )
    assert (
        definition.input_json_schema["properties"][
            "after_agent_message_id_by_conversation"
        ]["anyOf"][0]["type"]
        == "object"
    )
    assert definition.input_json_schema["properties"]["wait_up_to_seconds"]["type"] == (
        "integer"
    )
    assert (
        definition.input_json_schema["properties"]["poll_interval_seconds"]["type"]
        == "integer"
    )


def test_build_hub_assistant_tool_definition_supports_agent_start_sessions() -> None:
    definition = build_hub_assistant_tool_definition(
        HUB_ASSISTANT_AGENTS_START_SESSIONS
    )

    assert definition.operation_id == "hub_assistant.agents.start_sessions"
    assert definition.tool_name == "hub_assistant.agents.start_sessions"
    assert definition.confirmation_policy.value == "required"
    assert "automatically added to durable follow-up tracking" in definition.description
    assert definition.input_json_schema["properties"]["agent_ids"]["type"] == "array"
    assert definition.input_json_schema["properties"]["message"]["type"] == "string"


def test_build_hub_assistant_tool_definition_documents_job_conversation_policy() -> (
    None
):
    definition = build_hub_assistant_tool_definition(HUB_ASSISTANT_JOBS_CREATE)

    conversation_policy = definition.input_json_schema["properties"][
        "conversation_policy"
    ]

    assert definition.operation_id == "hub_assistant.jobs.create"
    assert "exact enum `new_each_run` or `reuse_single`" in definition.description
    assert conversation_policy["enum"] == ["new_each_run", "reuse_single"]
    assert conversation_policy["description"] == (
        "Use the exact enum `new_each_run` to create a fresh conversation for "
        "every run, or `reuse_single` to keep reusing one conversation across runs."
    )


def test_build_hub_assistant_tool_definition_rejects_missing_tool_name() -> None:
    try:
        build_hub_assistant_tool_definition(ADMIN_HUB_AGENTS_LIST)
    except KeyError as exc:
        assert str(exc) == (
            "'Operation `admin.agents.list` does not declare a tool name.'"
        )
    else:  # pragma: no cover - defensive guard
        raise AssertionError("Expected a KeyError for an operation without a tool name")
