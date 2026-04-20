"""Registered self-management capability operations."""

from __future__ import annotations

from app.features.self_management_shared.actor_context import SelfManagementAction
from app.features.self_management_shared.operation_registry import (
    list_self_management_operation_specs,
)
from app.features.self_management_shared.tool_gateway import (
    SelfManagementConfirmationPolicy,
    SelfManagementOperation,
    SelfManagementSurface,
)

ALL_SELF_MANAGEMENT_OPERATIONS = {
    spec.operation_id: spec.build_operation()
    for spec in list_self_management_operation_specs(first_wave_only=False)
}


def _bind_operations(*operation_ids: str) -> tuple[SelfManagementOperation, ...]:
    return tuple(
        ALL_SELF_MANAGEMENT_OPERATIONS[operation_id] for operation_id in operation_ids
    )


(
    SELF_AGENTS_LIST,
    SELF_AGENTS_GET,
    SELF_AGENTS_CHECK_HEALTH,
    SELF_AGENTS_CHECK_HEALTH_ALL,
    SELF_AGENTS_CREATE,
    SELF_AGENTS_UPDATE_CONFIG,
    SELF_AGENTS_DELETE,
    SELF_AGENTS_START_SESSIONS,
    SELF_FOLLOWUPS_GET,
    SELF_FOLLOWUPS_SET_SESSIONS,
    SELF_SESSIONS_LIST,
    SELF_SESSIONS_GET,
    SELF_SESSIONS_GET_LATEST_MESSAGES,
    SELF_SESSIONS_UPDATE,
    SELF_SESSIONS_ARCHIVE,
    SELF_SESSIONS_UNARCHIVE,
    SELF_SESSIONS_SEND_MESSAGE,
    SELF_JOBS_LIST,
    SELF_JOBS_GET,
    SELF_JOBS_CREATE,
    SELF_JOBS_PAUSE,
    SELF_JOBS_RESUME,
    SELF_JOBS_UPDATE,
    SELF_JOBS_UPDATE_PROMPT,
    SELF_JOBS_UPDATE_SCHEDULE,
    SELF_JOBS_DELETE,
) = _bind_operations(
    "self.agents.list",
    "self.agents.get",
    "self.agents.check_health",
    "self.agents.check_health_all",
    "self.agents.create",
    "self.agents.update_config",
    "self.agents.delete",
    "self.agents.start_sessions",
    "self.followups.get",
    "self.followups.set_sessions",
    "self.sessions.list",
    "self.sessions.get",
    "self.sessions.get_latest_messages",
    "self.sessions.update",
    "self.sessions.archive",
    "self.sessions.unarchive",
    "self.sessions.send_message",
    "self.jobs.list",
    "self.jobs.get",
    "self.jobs.create",
    "self.jobs.pause",
    "self.jobs.resume",
    "self.jobs.update",
    "self.jobs.update_prompt",
    "self.jobs.update_schedule",
    "self.jobs.delete",
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
    ALL_SELF_MANAGEMENT_OPERATIONS[spec.operation_id]
    for spec in list_self_management_operation_specs()
)

INTERNAL_ADMIN_OPERATIONS = tuple(
    ALL_SELF_MANAGEMENT_OPERATIONS[spec.operation_id]
    for spec in list_self_management_operation_specs(first_wave_only=False)
    if not spec.first_wave_exposed
)

UNSUPPORTED_FIRST_WAVE_OPERATION_IDS = frozenset(
    {
        "self.sessions.delete",
        "admin.agents.delete",
    }
)


def get_self_management_operation(operation_id: str) -> SelfManagementOperation:
    """Resolve one registered self-management operation by id."""

    try:
        return ALL_SELF_MANAGEMENT_OPERATIONS[operation_id]
    except KeyError as exc:
        raise KeyError(f"Unknown self-management operation: {operation_id}") from exc


def list_self_management_operations(
    *,
    surface: SelfManagementSurface | None = None,
    first_wave_only: bool = True,
    confirmation_policy: SelfManagementConfirmationPolicy | None = None,
    action: SelfManagementAction | None = None,
    require_tool_name: bool = False,
) -> tuple[SelfManagementOperation, ...]:
    """List registered operations through one shared filter path."""

    source_operations = (
        FIRST_WAVE_EXPOSED_OPERATIONS
        if first_wave_only
        else tuple(ALL_SELF_MANAGEMENT_OPERATIONS.values())
    )
    filtered: list[SelfManagementOperation] = []
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


def list_self_management_operation_ids(
    *,
    surface: SelfManagementSurface | None = None,
    first_wave_only: bool = True,
    confirmation_policy: SelfManagementConfirmationPolicy | None = None,
    action: SelfManagementAction | None = None,
    require_tool_name: bool = False,
) -> tuple[str, ...]:
    """List filtered operation ids in stable order."""

    return tuple(
        operation.operation_id
        for operation in list_self_management_operations(
            surface=surface,
            first_wave_only=first_wave_only,
            confirmation_policy=confirmation_policy,
            action=action,
            require_tool_name=require_tool_name,
        )
    )
