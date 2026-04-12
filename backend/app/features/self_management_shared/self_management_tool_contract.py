"""Tool definitions for self-management built-in agent surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.features.self_management_shared.capability_catalog import (
    ALL_SELF_MANAGEMENT_OPERATIONS,
)
from app.features.self_management_shared.tool_gateway import (
    SelfManagementConfirmationPolicy,
    SelfManagementOperation,
    SelfManagementSurface,
)


class _StrictBaseModel(BaseModel):
    """Base model for self-management tool input schemas."""

    model_config = ConfigDict(extra="forbid")


class _JobsListInput(_StrictBaseModel):
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1)


class _JobGetInput(_StrictBaseModel):
    task_id: str = Field(min_length=1)


class _JobsCreateInput(_StrictBaseModel):
    name: str = Field(min_length=1, max_length=120)
    agent_id: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    cycle_type: str = Field(pattern="^(daily|weekly|monthly|interval|sequential)$")
    time_point: dict[str, object] = Field(default_factory=dict)
    enabled: bool = True
    conversation_policy: Literal["new_each_run", "reuse_single"] = Field(
        default="new_each_run",
        description=(
            "Use the exact enum `new_each_run` to create a fresh conversation for "
            "every run, or `reuse_single` to keep reusing one conversation across "
            "runs."
        ),
    )
    schedule_timezone: str | None = None


class _JobUpdatePromptInput(_JobGetInput):
    prompt: str = Field(min_length=1)


class _JobUpdateScheduleInput(_JobGetInput):
    cycle_type: str | None = None
    time_point: dict[str, object] | None = None
    schedule_timezone: str | None = None


class _JobUpdateInput(_JobGetInput):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    agent_id: str | None = None
    prompt: str | None = Field(default=None, min_length=1)
    cycle_type: str | None = Field(
        default=None,
        pattern="^(daily|weekly|monthly|interval|sequential)$",
    )
    time_point: dict[str, object] | None = None
    enabled: bool | None = None
    conversation_policy: Literal["new_each_run", "reuse_single"] | None = Field(
        default=None,
        description=(
            "When provided, use the exact enum `new_each_run` for a fresh "
            "conversation on every run, or `reuse_single` to keep reusing one "
            "conversation across runs."
        ),
    )
    schedule_timezone: str | None = None


class _SessionsListInput(_StrictBaseModel):
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1)
    source: str | None = Field(default=None, pattern="^(manual|scheduled)$")
    status: str = Field(default="active", pattern="^(active|archived|all)$")
    agent_id: str | None = None


class _SessionGetInput(_StrictBaseModel):
    conversation_id: str = Field(min_length=1)


class _SessionUpdateInput(_SessionGetInput):
    title: str = Field(min_length=1, max_length=255)


class _AgentsListInput(_StrictBaseModel):
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1)
    health_bucket: str = Field(
        default="all",
        pattern="^(all|healthy|degraded|unavailable|unknown|attention)$",
    )


class _AgentGetInput(_StrictBaseModel):
    agent_id: str = Field(min_length=1)


class _AgentCheckHealthInput(_AgentGetInput):
    force: bool = True


class _AgentsCheckHealthAllInput(_StrictBaseModel):
    force: bool = False


class _AgentCreateInput(_StrictBaseModel):
    name: str = Field(min_length=1)
    card_url: str = Field(min_length=1)
    auth_type: str = Field(pattern="^(none|bearer|basic)$")
    auth_header: str | None = None
    auth_scheme: str | None = None
    enabled: bool = True
    tags: list[str] | None = None
    extra_headers: dict[str, str] | None = None
    invoke_metadata_defaults: dict[str, str] | None = None
    token: str | None = None
    basic_username: str | None = None
    basic_password: str | None = None


class _AgentUpdateConfigInput(_AgentGetInput):
    name: str | None = None
    card_url: str | None = None
    auth_type: str | None = Field(default=None, pattern="^(none|bearer|basic)$")
    auth_header: str | None = None
    auth_scheme: str | None = None
    enabled: bool | None = None
    tags: list[str] | None = None
    extra_headers: dict[str, str] | None = None
    invoke_metadata_defaults: dict[str, str] | None = None
    token: str | None = None
    basic_username: str | None = None
    basic_password: str | None = None


_INPUT_MODELS_BY_OPERATION_ID: dict[str, type[BaseModel]] = {
    "self.jobs.list": _JobsListInput,
    "self.jobs.get": _JobGetInput,
    "self.jobs.create": _JobsCreateInput,
    "self.jobs.pause": _JobGetInput,
    "self.jobs.resume": _JobGetInput,
    "self.jobs.update": _JobUpdateInput,
    "self.jobs.update_prompt": _JobUpdatePromptInput,
    "self.jobs.update_schedule": _JobUpdateScheduleInput,
    "self.jobs.delete": _JobGetInput,
    "self.sessions.list": _SessionsListInput,
    "self.sessions.get": _SessionGetInput,
    "self.sessions.update": _SessionUpdateInput,
    "self.sessions.archive": _SessionGetInput,
    "self.sessions.unarchive": _SessionGetInput,
    "self.agents.list": _AgentsListInput,
    "self.agents.get": _AgentGetInput,
    "self.agents.check_health": _AgentCheckHealthInput,
    "self.agents.check_health_all": _AgentsCheckHealthAllInput,
    "self.agents.create": _AgentCreateInput,
    "self.agents.update_config": _AgentUpdateConfigInput,
    "self.agents.delete": _AgentGetInput,
}


@dataclass(frozen=True)
class SelfManagementToolDefinition:
    """Agent-facing tool definition derived from one capability operation."""

    operation_id: str
    tool_name: str
    description: str
    input_json_schema: dict[str, Any]
    confirmation_policy: SelfManagementConfirmationPolicy
    surfaces: frozenset[SelfManagementSurface]


def build_self_management_tool_definition(
    operation: SelfManagementOperation,
) -> SelfManagementToolDefinition:
    """Build one tool definition from a catalog operation."""

    if operation.tool_name is None:
        raise KeyError(
            f"Operation `{operation.operation_id}` does not declare a tool name."
        )
    model = _INPUT_MODELS_BY_OPERATION_ID.get(operation.operation_id)
    if model is None:
        raise KeyError(
            f"Operation `{operation.operation_id}` does not have a registered input schema."
        )
    return SelfManagementToolDefinition(
        operation_id=operation.operation_id,
        tool_name=operation.tool_name,
        description=operation.description or operation.operation_id,
        input_json_schema=model.model_json_schema(),
        confirmation_policy=operation.confirmation_policy,
        surfaces=operation.surfaces,
    )


def list_self_management_tool_definitions(
    *,
    surface: SelfManagementSurface | None = None,
    first_wave_only: bool = True,
) -> tuple[SelfManagementToolDefinition, ...]:
    """List self-management tool definitions filtered by surface."""

    definitions: list[SelfManagementToolDefinition] = []
    for operation in ALL_SELF_MANAGEMENT_OPERATIONS.values():
        if operation.tool_name is None:
            continue
        if first_wave_only and not operation.first_wave_exposed:
            continue
        if (
            surface is not None
            and operation.surfaces
            and surface not in operation.surfaces
        ):
            continue
        definitions.append(build_self_management_tool_definition(operation))
    return tuple(sorted(definitions, key=lambda item: item.operation_id))


__all__ = [
    "SelfManagementToolDefinition",
    "build_self_management_tool_definition",
    "list_self_management_tool_definitions",
]
