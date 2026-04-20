"""Registered Hub Assistant capability operations."""

from __future__ import annotations

from app.features.hub_assistant_shared.actor_context import HubAssistantAction
from app.features.hub_assistant_shared.operation_registry import (
    list_hub_assistant_operation_specs,
)
from app.features.hub_assistant_shared.tool_gateway import (
    HubAssistantConfirmationPolicy,
    HubAssistantOperation,
    HubAssistantSurface,
)

ALL_HUB_ASSISTANT_OPERATIONS = {
    spec.operation_id: spec.build_operation()
    for spec in list_hub_assistant_operation_specs(first_wave_only=False)
}


def _bind_operations(*operation_ids: str) -> tuple[HubAssistantOperation, ...]:
    return tuple(
        ALL_HUB_ASSISTANT_OPERATIONS[operation_id] for operation_id in operation_ids
    )


(
    HUB_ASSISTANT_AGENTS_LIST,
    HUB_ASSISTANT_AGENTS_GET,
    HUB_ASSISTANT_AGENTS_CHECK_HEALTH,
    HUB_ASSISTANT_AGENTS_CHECK_HEALTH_ALL,
    HUB_ASSISTANT_AGENTS_CREATE,
    HUB_ASSISTANT_AGENTS_UPDATE_CONFIG,
    HUB_ASSISTANT_AGENTS_DELETE,
    HUB_ASSISTANT_AGENTS_START_SESSIONS,
    HUB_ASSISTANT_FOLLOWUPS_GET,
    HUB_ASSISTANT_FOLLOWUPS_SET_SESSIONS,
    HUB_ASSISTANT_SESSIONS_LIST,
    HUB_ASSISTANT_SESSIONS_GET,
    HUB_ASSISTANT_SESSIONS_GET_LATEST_MESSAGES,
    HUB_ASSISTANT_SESSIONS_UPDATE,
    HUB_ASSISTANT_SESSIONS_ARCHIVE,
    HUB_ASSISTANT_SESSIONS_UNARCHIVE,
    HUB_ASSISTANT_SESSIONS_SEND_MESSAGE,
    HUB_ASSISTANT_JOBS_LIST,
    HUB_ASSISTANT_JOBS_GET,
    HUB_ASSISTANT_JOBS_CREATE,
    HUB_ASSISTANT_JOBS_PAUSE,
    HUB_ASSISTANT_JOBS_RESUME,
    HUB_ASSISTANT_JOBS_UPDATE,
    HUB_ASSISTANT_JOBS_UPDATE_PROMPT,
    HUB_ASSISTANT_JOBS_UPDATE_SCHEDULE,
    HUB_ASSISTANT_JOBS_DELETE,
) = _bind_operations(
    "hub_assistant.agents.list",
    "hub_assistant.agents.get",
    "hub_assistant.agents.check_health",
    "hub_assistant.agents.check_health_all",
    "hub_assistant.agents.create",
    "hub_assistant.agents.update_config",
    "hub_assistant.agents.delete",
    "hub_assistant.agents.start_sessions",
    "hub_assistant.followups.get",
    "hub_assistant.followups.set_sessions",
    "hub_assistant.sessions.list",
    "hub_assistant.sessions.get",
    "hub_assistant.sessions.get_latest_messages",
    "hub_assistant.sessions.update",
    "hub_assistant.sessions.archive",
    "hub_assistant.sessions.unarchive",
    "hub_assistant.sessions.send_message",
    "hub_assistant.jobs.list",
    "hub_assistant.jobs.get",
    "hub_assistant.jobs.create",
    "hub_assistant.jobs.pause",
    "hub_assistant.jobs.resume",
    "hub_assistant.jobs.update",
    "hub_assistant.jobs.update_prompt",
    "hub_assistant.jobs.update_schedule",
    "hub_assistant.jobs.delete",
)

(
    ADMIN_HUB_AGENTS_LIST,
    ADMIN_HUB_AGENTS_GET,
    ADMIN_HUB_AGENTS_CREATE,
    ADMIN_HUB_AGENTS_UPDATE,
    ADMIN_HUB_AGENTS_DELETE,
    ADMIN_HUB_AGENT_ALLOWLIST_LIST,
    ADMIN_HUB_AGENT_ALLOWLIST_ADD,
    ADMIN_HUB_AGENT_ALLOWLIST_REPLACE,
    ADMIN_HUB_AGENT_ALLOWLIST_REMOVE,
) = _bind_operations(
    "admin.agents.list",
    "admin.agents.get",
    "admin.agents.create",
    "admin.agents.update",
    "admin.agents.delete",
    "admin.agents.allowlist.list",
    "admin.agents.allowlist.add",
    "admin.agents.allowlist.replace",
    "admin.agents.allowlist.remove",
)

FIRST_WAVE_EXPOSED_OPERATIONS = tuple(
    ALL_HUB_ASSISTANT_OPERATIONS[spec.operation_id]
    for spec in list_hub_assistant_operation_specs()
)

INTERNAL_ADMIN_OPERATIONS = tuple(
    ALL_HUB_ASSISTANT_OPERATIONS[spec.operation_id]
    for spec in list_hub_assistant_operation_specs(first_wave_only=False)
    if not spec.first_wave_exposed
)

UNSUPPORTED_FIRST_WAVE_OPERATION_IDS = frozenset(
    {
        "hub_assistant.sessions.delete",
        "admin.agents.delete",
    }
)


def get_hub_assistant_operation(operation_id: str) -> HubAssistantOperation:
    """Resolve one registered Hub Assistant operation by id."""

    try:
        return ALL_HUB_ASSISTANT_OPERATIONS[operation_id]
    except KeyError as exc:
        raise KeyError(f"Unknown Hub Assistant operation: {operation_id}") from exc


def list_hub_assistant_operations(
    *,
    surface: HubAssistantSurface | None = None,
    first_wave_only: bool = True,
    confirmation_policy: HubAssistantConfirmationPolicy | None = None,
    action: HubAssistantAction | None = None,
    require_tool_name: bool = False,
) -> tuple[HubAssistantOperation, ...]:
    """List registered operations through one shared filter path."""

    source_operations = (
        FIRST_WAVE_EXPOSED_OPERATIONS
        if first_wave_only
        else tuple(ALL_HUB_ASSISTANT_OPERATIONS.values())
    )
    filtered: list[HubAssistantOperation] = []
    for operation in source_operations:
        if require_tool_name and operation.tool_name is None:
            continue
        if (
            surface is not None
            and operation.surfaces
            and surface not in operation.surfaces
        ):
            continue
        if (
            confirmation_policy is not None
            and operation.confirmation_policy != confirmation_policy
        ):
            continue
        if action is not None and operation.action != action:
            continue
        filtered.append(operation)
    return tuple(sorted(filtered, key=lambda item: item.operation_id))


def list_hub_assistant_operation_ids(
    *,
    surface: HubAssistantSurface | None = None,
    first_wave_only: bool = True,
    confirmation_policy: HubAssistantConfirmationPolicy | None = None,
    action: HubAssistantAction | None = None,
    require_tool_name: bool = False,
) -> tuple[str, ...]:
    """List filtered operation ids in stable order."""

    return tuple(
        operation.operation_id
        for operation in list_hub_assistant_operations(
            surface=surface,
            first_wave_only=first_wave_only,
            confirmation_policy=confirmation_policy,
            action=action,
            require_tool_name=require_tool_name,
        )
    )
