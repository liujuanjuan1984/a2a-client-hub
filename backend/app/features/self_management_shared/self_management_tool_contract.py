"""Tool definitions for self-management built-in agent surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.features.self_management_shared.capability_catalog import (
    list_self_management_operations,
)
from app.features.self_management_shared.operation_registry import (
    get_self_management_input_model,
)
from app.features.self_management_shared.tool_gateway import (
    SelfManagementConfirmationPolicy,
    SelfManagementOperation,
    SelfManagementSurface,
)


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
    model = get_self_management_input_model(operation.operation_id)
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

    return tuple(
        build_self_management_tool_definition(operation)
        for operation in list_self_management_operations(
            surface=surface,
            first_wave_only=first_wave_only,
            require_tool_name=True,
        )
    )
