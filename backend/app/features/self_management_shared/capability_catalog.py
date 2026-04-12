"""First-wave self-management capability catalog."""

from __future__ import annotations

from app.features.self_management_shared.actor_context import (
    SelfManagementAction,
    SelfManagementResource,
    SelfManagementScope,
)
from app.features.self_management_shared.tool_gateway import (
    SelfManagementConfirmationPolicy,
    SelfManagementOperation,
    SelfManagementSurface,
)

_SELF_ENTRY_SURFACES = frozenset(
    {
        SelfManagementSurface.REST,
        SelfManagementSurface.CLI,
        SelfManagementSurface.WEB_AGENT,
    }
)

SELF_AGENTS_LIST = SelfManagementOperation(
    operation_id="self.agents.list",
    scope=SelfManagementScope.SELF,
    resource=SelfManagementResource.AGENTS,
    action=SelfManagementAction.READ,
    event_name="self_agent.list.requested",
    command_name="agents.list",
    tool_name="self.agents.list",
    first_wave_exposed=True,
    surfaces=_SELF_ENTRY_SURFACES,
    description="List the current user's agents.",
)

SELF_AGENTS_GET = SelfManagementOperation(
    operation_id="self.agents.get",
    scope=SelfManagementScope.SELF,
    resource=SelfManagementResource.AGENTS,
    action=SelfManagementAction.READ,
    event_name="self_agent.get.requested",
    command_name="agents.get",
    tool_name="self.agents.get",
    first_wave_exposed=True,
    surfaces=_SELF_ENTRY_SURFACES,
    description="Read one current-user agent in detail.",
)

SELF_AGENTS_UPDATE_CONFIG = SelfManagementOperation(
    operation_id="self.agents.update_config",
    scope=SelfManagementScope.SELF,
    resource=SelfManagementResource.AGENTS,
    action=SelfManagementAction.WRITE,
    event_name="self_agent.update_config.requested",
    command_name="agents.update-config",
    tool_name="self.agents.update_config",
    confirmation_policy=SelfManagementConfirmationPolicy.REQUIRED,
    first_wave_exposed=True,
    surfaces=_SELF_ENTRY_SURFACES,
    description="Update a constrained subset of the current user's agent config.",
)

SELF_SESSIONS_LIST = SelfManagementOperation(
    operation_id="self.sessions.list",
    scope=SelfManagementScope.SELF,
    resource=SelfManagementResource.SESSIONS,
    action=SelfManagementAction.READ,
    event_name="self_session.list.requested",
    command_name="sessions.list",
    tool_name="self.sessions.list",
    first_wave_exposed=True,
    surfaces=_SELF_ENTRY_SURFACES,
    description="List the current user's sessions.",
)

SELF_SESSIONS_GET = SelfManagementOperation(
    operation_id="self.sessions.get",
    scope=SelfManagementScope.SELF,
    resource=SelfManagementResource.SESSIONS,
    action=SelfManagementAction.READ,
    event_name="self_session.get.requested",
    command_name="sessions.get",
    tool_name="self.sessions.get",
    first_wave_exposed=True,
    surfaces=_SELF_ENTRY_SURFACES,
    description="Read one current-user session in detail.",
)

SELF_JOBS_LIST = SelfManagementOperation(
    operation_id="self.jobs.list",
    scope=SelfManagementScope.SELF,
    resource=SelfManagementResource.JOBS,
    action=SelfManagementAction.READ,
    event_name="self_job.list.requested",
    command_name="jobs.list",
    tool_name="self.jobs.list",
    first_wave_exposed=True,
    surfaces=_SELF_ENTRY_SURFACES,
    description="List the current user's jobs.",
)

SELF_JOBS_GET = SelfManagementOperation(
    operation_id="self.jobs.get",
    scope=SelfManagementScope.SELF,
    resource=SelfManagementResource.JOBS,
    action=SelfManagementAction.READ,
    event_name="self_job.get.requested",
    command_name="jobs.get",
    tool_name="self.jobs.get",
    first_wave_exposed=True,
    surfaces=_SELF_ENTRY_SURFACES,
    description="Read one current-user job in detail.",
)

SELF_JOBS_PAUSE = SelfManagementOperation(
    operation_id="self.jobs.pause",
    scope=SelfManagementScope.SELF,
    resource=SelfManagementResource.JOBS,
    action=SelfManagementAction.WRITE,
    event_name="self_job.pause.requested",
    command_name="jobs.pause",
    tool_name="self.jobs.pause",
    confirmation_policy=SelfManagementConfirmationPolicy.REQUIRED,
    first_wave_exposed=True,
    surfaces=_SELF_ENTRY_SURFACES,
    description="Pause one current-user job.",
)

SELF_JOBS_RESUME = SelfManagementOperation(
    operation_id="self.jobs.resume",
    scope=SelfManagementScope.SELF,
    resource=SelfManagementResource.JOBS,
    action=SelfManagementAction.WRITE,
    event_name="self_job.resume.requested",
    command_name="jobs.resume",
    tool_name="self.jobs.resume",
    confirmation_policy=SelfManagementConfirmationPolicy.REQUIRED,
    first_wave_exposed=True,
    surfaces=_SELF_ENTRY_SURFACES,
    description="Resume one current-user job.",
)

SELF_JOBS_UPDATE_PROMPT = SelfManagementOperation(
    operation_id="self.jobs.update_prompt",
    scope=SelfManagementScope.SELF,
    resource=SelfManagementResource.JOBS,
    action=SelfManagementAction.WRITE,
    event_name="self_job.update_prompt.requested",
    command_name="jobs.update-prompt",
    tool_name="self.jobs.update_prompt",
    confirmation_policy=SelfManagementConfirmationPolicy.REQUIRED,
    first_wave_exposed=True,
    surfaces=_SELF_ENTRY_SURFACES,
    description="Update the prompt of one current-user job.",
)

SELF_JOBS_UPDATE_SCHEDULE = SelfManagementOperation(
    operation_id="self.jobs.update_schedule",
    scope=SelfManagementScope.SELF,
    resource=SelfManagementResource.JOBS,
    action=SelfManagementAction.WRITE,
    event_name="self_job.update_schedule.requested",
    command_name="jobs.update-schedule",
    tool_name="self.jobs.update_schedule",
    confirmation_policy=SelfManagementConfirmationPolicy.REQUIRED,
    first_wave_exposed=True,
    surfaces=_SELF_ENTRY_SURFACES,
    description="Update the schedule of one current-user job.",
)

ADMIN_HUB_AGENTS_LIST = SelfManagementOperation(
    operation_id="admin.agents.list",
    scope=SelfManagementScope.ADMIN,
    resource=SelfManagementResource.AGENTS,
    action=SelfManagementAction.READ,
    event_name="hub_agent.list.requested",
    surfaces=frozenset({SelfManagementSurface.REST}),
)

ADMIN_HUB_AGENTS_GET = SelfManagementOperation(
    operation_id="admin.agents.get",
    scope=SelfManagementScope.ADMIN,
    resource=SelfManagementResource.AGENTS,
    action=SelfManagementAction.READ,
    event_name="hub_agent.get.requested",
    surfaces=frozenset({SelfManagementSurface.REST}),
)

ADMIN_HUB_AGENTS_CREATE = SelfManagementOperation(
    operation_id="admin.agents.create",
    scope=SelfManagementScope.ADMIN,
    resource=SelfManagementResource.AGENTS,
    action=SelfManagementAction.WRITE,
    event_name="hub_agent.create.requested",
    surfaces=frozenset({SelfManagementSurface.REST}),
)

ADMIN_HUB_AGENTS_UPDATE = SelfManagementOperation(
    operation_id="admin.agents.update",
    scope=SelfManagementScope.ADMIN,
    resource=SelfManagementResource.AGENTS,
    action=SelfManagementAction.WRITE,
    event_name="hub_agent.update.requested",
    surfaces=frozenset({SelfManagementSurface.REST}),
)

ADMIN_HUB_AGENTS_DELETE = SelfManagementOperation(
    operation_id="admin.agents.delete",
    scope=SelfManagementScope.ADMIN,
    resource=SelfManagementResource.AGENTS,
    action=SelfManagementAction.WRITE,
    event_name="hub_agent.delete.requested",
    surfaces=frozenset({SelfManagementSurface.REST}),
)

ADMIN_HUB_AGENT_ALLOWLIST_LIST = SelfManagementOperation(
    operation_id="admin.agents.allowlist.list",
    scope=SelfManagementScope.ADMIN,
    resource=SelfManagementResource.AGENTS,
    action=SelfManagementAction.READ,
    event_name="hub_agent.allowlist.list.requested",
    surfaces=frozenset({SelfManagementSurface.REST}),
)

ADMIN_HUB_AGENT_ALLOWLIST_ADD = SelfManagementOperation(
    operation_id="admin.agents.allowlist.add",
    scope=SelfManagementScope.ADMIN,
    resource=SelfManagementResource.AGENTS,
    action=SelfManagementAction.WRITE,
    event_name="hub_agent.allowlist.add.requested",
    surfaces=frozenset({SelfManagementSurface.REST}),
)

ADMIN_HUB_AGENT_ALLOWLIST_REPLACE = SelfManagementOperation(
    operation_id="admin.agents.allowlist.replace",
    scope=SelfManagementScope.ADMIN,
    resource=SelfManagementResource.AGENTS,
    action=SelfManagementAction.WRITE,
    event_name="hub_agent.allowlist.replace.requested",
    surfaces=frozenset({SelfManagementSurface.REST}),
)

ADMIN_HUB_AGENT_ALLOWLIST_REMOVE = SelfManagementOperation(
    operation_id="admin.agents.allowlist.remove",
    scope=SelfManagementScope.ADMIN,
    resource=SelfManagementResource.AGENTS,
    action=SelfManagementAction.WRITE,
    event_name="hub_agent.allowlist.remove.requested",
    surfaces=frozenset({SelfManagementSurface.REST}),
)

FIRST_WAVE_EXPOSED_OPERATIONS = (
    SELF_AGENTS_LIST,
    SELF_AGENTS_GET,
    SELF_AGENTS_UPDATE_CONFIG,
    SELF_SESSIONS_LIST,
    SELF_SESSIONS_GET,
    SELF_JOBS_LIST,
    SELF_JOBS_GET,
    SELF_JOBS_PAUSE,
    SELF_JOBS_RESUME,
    SELF_JOBS_UPDATE_PROMPT,
    SELF_JOBS_UPDATE_SCHEDULE,
)

INTERNAL_ADMIN_OPERATIONS = (
    ADMIN_HUB_AGENTS_LIST,
    ADMIN_HUB_AGENTS_GET,
    ADMIN_HUB_AGENTS_CREATE,
    ADMIN_HUB_AGENTS_UPDATE,
    ADMIN_HUB_AGENTS_DELETE,
    ADMIN_HUB_AGENT_ALLOWLIST_LIST,
    ADMIN_HUB_AGENT_ALLOWLIST_ADD,
    ADMIN_HUB_AGENT_ALLOWLIST_REPLACE,
    ADMIN_HUB_AGENT_ALLOWLIST_REMOVE,
)

UNSUPPORTED_FIRST_WAVE_OPERATION_IDS = frozenset(
    {
        "self.jobs.delete",
        "self.sessions.delete",
        "self.agents.delete",
        "admin.agents.delete",
    }
)

ALL_SELF_MANAGEMENT_OPERATIONS = {
    operation.operation_id: operation
    for operation in (*FIRST_WAVE_EXPOSED_OPERATIONS, *INTERNAL_ADMIN_OPERATIONS)
}


def get_self_management_operation(operation_id: str) -> SelfManagementOperation:
    """Resolve one registered self-management operation by id."""

    try:
        return ALL_SELF_MANAGEMENT_OPERATIONS[operation_id]
    except KeyError as exc:
        raise KeyError(f"Unknown self-management operation: {operation_id}") from exc


__all__ = [
    "ADMIN_HUB_AGENTS_CREATE",
    "ADMIN_HUB_AGENTS_DELETE",
    "ADMIN_HUB_AGENTS_GET",
    "ADMIN_HUB_AGENTS_LIST",
    "ADMIN_HUB_AGENTS_UPDATE",
    "ADMIN_HUB_AGENT_ALLOWLIST_ADD",
    "ADMIN_HUB_AGENT_ALLOWLIST_LIST",
    "ADMIN_HUB_AGENT_ALLOWLIST_REMOVE",
    "ADMIN_HUB_AGENT_ALLOWLIST_REPLACE",
    "ALL_SELF_MANAGEMENT_OPERATIONS",
    "FIRST_WAVE_EXPOSED_OPERATIONS",
    "INTERNAL_ADMIN_OPERATIONS",
    "SELF_AGENTS_GET",
    "SELF_AGENTS_LIST",
    "SELF_AGENTS_UPDATE_CONFIG",
    "SELF_JOBS_GET",
    "SELF_JOBS_LIST",
    "SELF_JOBS_PAUSE",
    "SELF_JOBS_RESUME",
    "SELF_JOBS_UPDATE_PROMPT",
    "SELF_JOBS_UPDATE_SCHEDULE",
    "SELF_SESSIONS_GET",
    "SELF_SESSIONS_LIST",
    "UNSUPPORTED_FIRST_WAVE_OPERATION_IDS",
    "get_self_management_operation",
]
