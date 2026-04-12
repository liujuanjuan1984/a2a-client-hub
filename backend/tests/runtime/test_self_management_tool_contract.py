from __future__ import annotations

from app.features.self_management_shared.capability_catalog import (
    ADMIN_HUB_AGENTS_LIST,
    SELF_JOBS_UPDATE_SCHEDULE,
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
    assert "self.sessions.get" in operation_ids
    assert "self.agents.update_config" in operation_ids
    assert "admin.agents.list" not in operation_ids


def test_build_self_management_tool_definition_rejects_missing_tool_name() -> None:
    try:
        build_self_management_tool_definition(ADMIN_HUB_AGENTS_LIST)
    except KeyError as exc:
        assert str(exc) == (
            "'Operation `admin.agents.list` does not declare a tool name.'"
        )
    else:  # pragma: no cover - defensive guard
        raise AssertionError("Expected a KeyError for an operation without a tool name")
