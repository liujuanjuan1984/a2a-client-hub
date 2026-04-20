"""Tool definitions for Hub Assistant surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.features.hub_access.capability_catalog import (
    list_hub_operations,
)
from app.features.hub_access.operation_gateway import (
    HubConfirmationPolicy,
    HubOperation,
    HubSurface,
)
from app.features.hub_access.operation_registry import (
    get_hub_operation_input_model,
)


@dataclass(frozen=True)
class HubAssistantToolDefinition:
    """Agent-facing tool definition derived from one capability operation."""

    operation_id: str
    tool_name: str
    description: str
    input_json_schema: dict[str, Any]
    confirmation_policy: HubConfirmationPolicy
    surfaces: frozenset[HubSurface]


def build_hub_assistant_tool_definition(
    operation: HubOperation,
) -> HubAssistantToolDefinition:
    """Build one tool definition from a catalog operation."""

    if operation.tool_name is None:
        raise KeyError(
            f"Operation `{operation.operation_id}` does not declare a tool name."
        )
    model = get_hub_operation_input_model(operation.operation_id)
    if model is None:
        raise KeyError(
            f"Operation `{operation.operation_id}` does not have a registered input schema."
        )
    return HubAssistantToolDefinition(
        operation_id=operation.operation_id,
        tool_name=operation.tool_name,
        description=operation.description or operation.operation_id,
        input_json_schema=model.model_json_schema(),
        confirmation_policy=operation.confirmation_policy,
        surfaces=operation.surfaces,
    )


def list_hub_assistant_tool_definitions(
    *,
    surface: HubSurface | None = None,
    first_wave_only: bool = True,
) -> tuple[HubAssistantToolDefinition, ...]:
    """List Hub Assistant tool definitions filtered by surface."""

    return tuple(
        build_hub_assistant_tool_definition(operation)
        for operation in list_hub_operations(
            surface=surface,
            first_wave_only=first_wave_only,
            require_tool_name=True,
        )
    )
