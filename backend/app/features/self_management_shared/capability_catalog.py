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
        SelfManagementSurface.WEB_AGENT,
    }
)

SELF_AGENTS_LIST = SelfManagementOperation(
    operation_id="self.agents.list",
    scope=SelfManagementScope.SELF,
    resource=SelfManagementResource.AGENTS,
    action=SelfManagementAction.READ,
    event_name="self_agent.list.requested",
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
    tool_name="self.agents.get",
    first_wave_exposed=True,
    surfaces=_SELF_ENTRY_SURFACES,
    description="Read one current-user agent in detail.",
)

SELF_AGENTS_CHECK_HEALTH = SelfManagementOperation(
    operation_id="self.agents.check_health",
    scope=SelfManagementScope.SELF,
    resource=SelfManagementResource.AGENTS,
    action=SelfManagementAction.WRITE,
    event_name="self_agent.check_health.requested",
    tool_name="self.agents.check_health",
    confirmation_policy=SelfManagementConfirmationPolicy.REQUIRED,
    first_wave_exposed=True,
    surfaces=_SELF_ENTRY_SURFACES,
    description="Run a health check for one current-user agent.",
)

SELF_AGENTS_CHECK_HEALTH_ALL = SelfManagementOperation(
    operation_id="self.agents.check_health_all",
    scope=SelfManagementScope.SELF,
    resource=SelfManagementResource.AGENTS,
    action=SelfManagementAction.WRITE,
    event_name="self_agent.check_health_all.requested",
    tool_name="self.agents.check_health_all",
    confirmation_policy=SelfManagementConfirmationPolicy.REQUIRED,
    first_wave_exposed=True,
    surfaces=_SELF_ENTRY_SURFACES,
    description="Run a health check sweep for all current-user agents.",
)

SELF_AGENTS_CREATE = SelfManagementOperation(
    operation_id="self.agents.create",
    scope=SelfManagementScope.SELF,
    resource=SelfManagementResource.AGENTS,
    action=SelfManagementAction.WRITE,
    event_name="self_agent.create.requested",
    tool_name="self.agents.create",
    confirmation_policy=SelfManagementConfirmationPolicy.REQUIRED,
    first_wave_exposed=True,
    surfaces=_SELF_ENTRY_SURFACES,
    description="Create one current-user agent.",
)

SELF_AGENTS_UPDATE_CONFIG = SelfManagementOperation(
    operation_id="self.agents.update_config",
    scope=SelfManagementScope.SELF,
    resource=SelfManagementResource.AGENTS,
    action=SelfManagementAction.WRITE,
    event_name="self_agent.update_config.requested",
    tool_name="self.agents.update_config",
    confirmation_policy=SelfManagementConfirmationPolicy.REQUIRED,
    first_wave_exposed=True,
    surfaces=_SELF_ENTRY_SURFACES,
    description="Update one current-user agent.",
)

SELF_AGENTS_DELETE = SelfManagementOperation(
    operation_id="self.agents.delete",
    scope=SelfManagementScope.SELF,
    resource=SelfManagementResource.AGENTS,
    action=SelfManagementAction.WRITE,
    event_name="self_agent.delete.requested",
    tool_name="self.agents.delete",
    confirmation_policy=SelfManagementConfirmationPolicy.REQUIRED,
    first_wave_exposed=True,
    surfaces=_SELF_ENTRY_SURFACES,
    description="Soft-delete one current-user agent.",
)

SELF_SESSIONS_LIST = SelfManagementOperation(
    operation_id="self.sessions.list",
    scope=SelfManagementScope.SELF,
    resource=SelfManagementResource.SESSIONS,
    action=SelfManagementAction.READ,
    event_name="self_session.list.requested",
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
    tool_name="self.sessions.get",
    first_wave_exposed=True,
    surfaces=_SELF_ENTRY_SURFACES,
    description="Read one current-user session in detail.",
)

SELF_SESSIONS_UPDATE = SelfManagementOperation(
    operation_id="self.sessions.update",
    scope=SelfManagementScope.SELF,
    resource=SelfManagementResource.SESSIONS,
    action=SelfManagementAction.WRITE,
    event_name="self_session.update.requested",
    tool_name="self.sessions.update",
    confirmation_policy=SelfManagementConfirmationPolicy.REQUIRED,
    first_wave_exposed=True,
    surfaces=_SELF_ENTRY_SURFACES,
    description="Update one current-user session.",
)

SELF_SESSIONS_ARCHIVE = SelfManagementOperation(
    operation_id="self.sessions.archive",
    scope=SelfManagementScope.SELF,
    resource=SelfManagementResource.SESSIONS,
    action=SelfManagementAction.WRITE,
    event_name="self_session.archive.requested",
    tool_name="self.sessions.archive",
    confirmation_policy=SelfManagementConfirmationPolicy.REQUIRED,
    first_wave_exposed=True,
    surfaces=_SELF_ENTRY_SURFACES,
    description="Archive one current-user session as a soft delete.",
)

SELF_SESSIONS_UNARCHIVE = SelfManagementOperation(
    operation_id="self.sessions.unarchive",
    scope=SelfManagementScope.SELF,
    resource=SelfManagementResource.SESSIONS,
    action=SelfManagementAction.WRITE,
    event_name="self_session.unarchive.requested",
    tool_name="self.sessions.unarchive",
    confirmation_policy=SelfManagementConfirmationPolicy.REQUIRED,
    first_wave_exposed=True,
    surfaces=_SELF_ENTRY_SURFACES,
    description="Restore one archived current-user session.",
)

SELF_JOBS_LIST = SelfManagementOperation(
    operation_id="self.jobs.list",
    scope=SelfManagementScope.SELF,
    resource=SelfManagementResource.JOBS,
    action=SelfManagementAction.READ,
    event_name="self_job.list.requested",
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
    tool_name="self.jobs.get",
    first_wave_exposed=True,
    surfaces=_SELF_ENTRY_SURFACES,
    description="Read one current-user job in detail.",
)

SELF_JOBS_CREATE = SelfManagementOperation(
    operation_id="self.jobs.create",
    scope=SelfManagementScope.SELF,
    resource=SelfManagementResource.JOBS,
    action=SelfManagementAction.WRITE,
    event_name="self_job.create.requested",
    tool_name="self.jobs.create",
    confirmation_policy=SelfManagementConfirmationPolicy.REQUIRED,
    first_wave_exposed=True,
    surfaces=_SELF_ENTRY_SURFACES,
    description=(
        "Create one current-user job. For `conversation_policy`, use the exact "
        "enum `new_each_run` or `reuse_single`."
    ),
)

SELF_JOBS_PAUSE = SelfManagementOperation(
    operation_id="self.jobs.pause",
    scope=SelfManagementScope.SELF,
    resource=SelfManagementResource.JOBS,
    action=SelfManagementAction.WRITE,
    event_name="self_job.pause.requested",
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
    tool_name="self.jobs.update_prompt",
    confirmation_policy=SelfManagementConfirmationPolicy.REQUIRED,
    first_wave_exposed=True,
    surfaces=_SELF_ENTRY_SURFACES,
    description="Update the prompt of one current-user job.",
)

SELF_JOBS_UPDATE = SelfManagementOperation(
    operation_id="self.jobs.update",
    scope=SelfManagementScope.SELF,
    resource=SelfManagementResource.JOBS,
    action=SelfManagementAction.WRITE,
    event_name="self_job.update.requested",
    tool_name="self.jobs.update",
    confirmation_policy=SelfManagementConfirmationPolicy.REQUIRED,
    first_wave_exposed=True,
    surfaces=_SELF_ENTRY_SURFACES,
    description=(
        "Update one current-user job. For `conversation_policy`, use the exact "
        "enum `new_each_run` or `reuse_single`."
    ),
)

SELF_JOBS_UPDATE_SCHEDULE = SelfManagementOperation(
    operation_id="self.jobs.update_schedule",
    scope=SelfManagementScope.SELF,
    resource=SelfManagementResource.JOBS,
    action=SelfManagementAction.WRITE,
    event_name="self_job.update_schedule.requested",
    tool_name="self.jobs.update_schedule",
    confirmation_policy=SelfManagementConfirmationPolicy.REQUIRED,
    first_wave_exposed=True,
    surfaces=_SELF_ENTRY_SURFACES,
    description="Update the schedule of one current-user job.",
)

SELF_JOBS_DELETE = SelfManagementOperation(
    operation_id="self.jobs.delete",
    scope=SelfManagementScope.SELF,
    resource=SelfManagementResource.JOBS,
    action=SelfManagementAction.WRITE,
    event_name="self_job.delete.requested",
    tool_name="self.jobs.delete",
    confirmation_policy=SelfManagementConfirmationPolicy.REQUIRED,
    first_wave_exposed=True,
    surfaces=_SELF_ENTRY_SURFACES,
    description="Soft-delete one current-user job.",
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
    SELF_AGENTS_CHECK_HEALTH,
    SELF_AGENTS_CHECK_HEALTH_ALL,
    SELF_AGENTS_CREATE,
    SELF_AGENTS_UPDATE_CONFIG,
    SELF_AGENTS_DELETE,
    SELF_SESSIONS_LIST,
    SELF_SESSIONS_GET,
    SELF_SESSIONS_UPDATE,
    SELF_SESSIONS_ARCHIVE,
    SELF_SESSIONS_UNARCHIVE,
    SELF_JOBS_LIST,
    SELF_JOBS_GET,
    SELF_JOBS_CREATE,
    SELF_JOBS_PAUSE,
    SELF_JOBS_RESUME,
    SELF_JOBS_UPDATE,
    SELF_JOBS_UPDATE_PROMPT,
    SELF_JOBS_UPDATE_SCHEDULE,
    SELF_JOBS_DELETE,
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
        "self.sessions.delete",
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
    "SELF_AGENTS_CREATE",
    "SELF_AGENTS_CHECK_HEALTH",
    "SELF_AGENTS_CHECK_HEALTH_ALL",
    "SELF_AGENTS_DELETE",
    "SELF_AGENTS_UPDATE_CONFIG",
    "SELF_JOBS_CREATE",
    "SELF_JOBS_DELETE",
    "SELF_JOBS_GET",
    "SELF_JOBS_LIST",
    "SELF_JOBS_PAUSE",
    "SELF_JOBS_RESUME",
    "SELF_JOBS_UPDATE",
    "SELF_JOBS_UPDATE_PROMPT",
    "SELF_JOBS_UPDATE_SCHEDULE",
    "SELF_SESSIONS_ARCHIVE",
    "SELF_SESSIONS_GET",
    "SELF_SESSIONS_LIST",
    "SELF_SESSIONS_UNARCHIVE",
    "SELF_SESSIONS_UPDATE",
    "UNSUPPORTED_FIRST_WAVE_OPERATION_IDS",
    "get_self_management_operation",
]
