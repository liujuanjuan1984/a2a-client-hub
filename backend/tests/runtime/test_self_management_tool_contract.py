from __future__ import annotations

from app.features.self_management_shared.capability_catalog import (
    ADMIN_HUB_AGENTS_LIST,
    SELF_AGENTS_CHECK_HEALTH,
    SELF_AGENTS_CREATE,
    SELF_AGENTS_START_SESSIONS,
    SELF_JOBS_CREATE,
    SELF_JOBS_UPDATE_SCHEDULE,
    SELF_SESSIONS_GET_LATEST_MESSAGES,
    SELF_SESSIONS_SEND_MESSAGE,
)
from app.features.self_management_shared.self_management_tool_contract import (
    build_self_management_tool_definition,
    list_self_management_tool_definitions,
)
from app.features.self_management_shared.tool_gateway import SelfManagementSurface


def test_build_self_management_tool_definition_exposes_operation_schema() -> None:
    definition = build_self_management_tool_definition(SELF_JOBS_UPDATE_SCHEDULE)

    assert definition.operation_id == "self.jobs.update_schedule"
    assert definition.tool_name == "self.jobs.update_schedule"
    assert definition.confirmation_policy.value == "required"
    assert definition.input_json_schema["type"] == "object"
    assert definition.input_json_schema["additionalProperties"] is False
    assert definition.input_json_schema["properties"]["task_id"]["type"] == "string"
    assert (
        definition.input_json_schema["properties"]["time_point"]["anyOf"][0]["type"]
        == "object"
    )


def test_list_self_management_tool_definitions_filters_by_surface() -> None:
    definitions = list_self_management_tool_definitions(
        surface=SelfManagementSurface.WEB_AGENT,
    )

    operation_ids = {item.operation_id for item in definitions}

    assert "self.jobs.list" in operation_ids
    assert "self.agents.create" in operation_ids
    assert "self.jobs.delete" in operation_ids
    assert "self.sessions.archive" in operation_ids
    assert "self.sessions.get" in operation_ids
    assert "self.sessions.get_latest_messages" in operation_ids
    assert "self.sessions.send_message" in operation_ids
    assert "self.agents.update_config" in operation_ids
    assert "self.agents.start_sessions" in operation_ids
    assert "admin.agents.list" not in operation_ids


def test_build_self_management_tool_definition_supports_agent_create() -> None:
    definition = build_self_management_tool_definition(SELF_AGENTS_CREATE)

    assert definition.operation_id == "self.agents.create"
    assert definition.tool_name == "self.agents.create"
    assert definition.confirmation_policy.value == "required"
    assert definition.input_json_schema["properties"]["card_url"]["type"] == "string"


def test_build_self_management_tool_definition_supports_agent_health_check() -> None:
    definition = build_self_management_tool_definition(SELF_AGENTS_CHECK_HEALTH)

    assert definition.operation_id == "self.agents.check_health"
    assert definition.tool_name == "self.agents.check_health"
    assert definition.confirmation_policy.value == "required"
    assert definition.input_json_schema["properties"]["force"]["type"] == "boolean"


def test_build_self_management_tool_definition_supports_session_send_message() -> None:
    definition = build_self_management_tool_definition(SELF_SESSIONS_SEND_MESSAGE)

    assert definition.operation_id == "self.sessions.send_message"
    assert definition.tool_name == "self.sessions.send_message"
    assert definition.confirmation_policy.value == "required"
    assert definition.input_json_schema["properties"]["conversation_ids"]["type"] == (
        "array"
    )
    assert definition.input_json_schema["properties"]["message"]["type"] == "string"


def test_build_self_management_tool_definition_supports_session_get_latest_messages() -> (
    None
):
    definition = build_self_management_tool_definition(
        SELF_SESSIONS_GET_LATEST_MESSAGES
    )

    assert definition.operation_id == "self.sessions.get_latest_messages"
    assert definition.tool_name == "self.sessions.get_latest_messages"
    assert definition.confirmation_policy.value == "none"
    assert definition.input_json_schema["properties"]["conversation_ids"]["type"] == (
        "array"
    )
    assert definition.input_json_schema["properties"]["limit_per_session"]["type"] == (
        "integer"
    )


def test_build_self_management_tool_definition_supports_agent_start_sessions() -> None:
    definition = build_self_management_tool_definition(SELF_AGENTS_START_SESSIONS)

    assert definition.operation_id == "self.agents.start_sessions"
    assert definition.tool_name == "self.agents.start_sessions"
    assert definition.confirmation_policy.value == "required"
    assert definition.input_json_schema["properties"]["agent_ids"]["type"] == "array"
    assert definition.input_json_schema["properties"]["message"]["type"] == "string"


def test_build_self_management_tool_definition_documents_job_conversation_policy() -> (
    None
):
    definition = build_self_management_tool_definition(SELF_JOBS_CREATE)

    conversation_policy = definition.input_json_schema["properties"][
        "conversation_policy"
    ]

    assert definition.operation_id == "self.jobs.create"
    assert "exact enum `new_each_run` or `reuse_single`" in definition.description
    assert conversation_policy["enum"] == ["new_each_run", "reuse_single"]
    assert conversation_policy["description"] == (
        "Use the exact enum `new_each_run` to create a fresh conversation for "
        "every run, or `reuse_single` to keep reusing one conversation across runs."
    )


def test_build_self_management_tool_definition_rejects_missing_tool_name() -> None:
    try:
        build_self_management_tool_definition(ADMIN_HUB_AGENTS_LIST)
    except KeyError as exc:
        assert str(exc) == (
            "'Operation `admin.agents.list` does not declare a tool name.'"
        )
    else:  # pragma: no cover - defensive guard
        raise AssertionError("Expected a KeyError for an operation without a tool name")
