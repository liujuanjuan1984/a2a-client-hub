"""Declarative registry for self-management operations and tool inputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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


class _StrictBaseModel(BaseModel):
    """Base model for strict self-management tool input schemas."""

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


class _FollowUpsGetInput(_StrictBaseModel):
    pass


class _FollowUpsSetSessionsInput(_StrictBaseModel):
    conversation_ids: list[str] = Field(default_factory=list, max_length=10)


class _SessionsGetLatestMessagesInput(_StrictBaseModel):
    conversation_ids: list[str] = Field(min_length=1, max_length=10)
    limit_per_session: int = Field(default=1, ge=1, le=5)
    after_agent_message_id_by_conversation: dict[str, str] | None = Field(
        default=None,
        description=(
            "Optional map from conversation id to the last seen target agent text "
            "message id. When provided together with a positive wait budget, the "
            "tool waits for a newer persisted target agent text message."
        ),
    )
    wait_up_to_seconds: int = Field(
        default=0,
        ge=0,
        le=20,
        description=(
            "Maximum bounded observation time in seconds. Use 0 for an immediate "
            "snapshot read."
        ),
    )
    poll_interval_seconds: int = Field(
        default=1,
        ge=1,
        le=5,
        description=(
            "Polling interval in seconds while observing persisted target-session "
            "results."
        ),
    )


class _SessionUpdateInput(_SessionGetInput):
    title: str = Field(min_length=1, max_length=255)


class _SessionsSendMessageInput(_StrictBaseModel):
    conversation_ids: list[str] = Field(min_length=1, max_length=10)
    message: str = Field(min_length=1, max_length=50_000)


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


class _AgentsStartSessionsInput(_StrictBaseModel):
    agent_ids: list[str] = Field(min_length=1, max_length=10)
    message: str = Field(min_length=1, max_length=50_000)


@dataclass(frozen=True)
class SelfManagementOperationSpec:
    """Declarative metadata for one registered self-management operation."""

    symbol_name: str
    operation_id: str
    scope: SelfManagementScope
    resource: SelfManagementResource
    action: SelfManagementAction
    event_name: str
    surfaces: frozenset[SelfManagementSurface]
    confirmation_policy: SelfManagementConfirmationPolicy = (
        SelfManagementConfirmationPolicy.NONE
    )
    first_wave_exposed: bool = False
    description: str | None = None
    tool_name: str | None = None
    delegated_by: str | None = None
    input_model: type[BaseModel] | None = None

    def build_operation(self) -> SelfManagementOperation:
        """Build a runtime operation from this declarative spec."""

        return SelfManagementOperation(
            operation_id=self.operation_id,
            scope=self.scope,
            resource=self.resource,
            action=self.action,
            event_name=self.event_name,
            confirmation_policy=self.confirmation_policy,
            surfaces=self.surfaces,
            first_wave_exposed=self.first_wave_exposed,
            description=self.description,
            tool_name=self.tool_name,
            delegated_by=self.delegated_by,
        )


_SELF_ENTRY_SURFACES = frozenset(
    {
        SelfManagementSurface.REST,
        SelfManagementSurface.WEB_AGENT,
    }
)
_WEB_AGENT_ONLY_SURFACES = frozenset({SelfManagementSurface.WEB_AGENT})
_REST_ONLY_SURFACES = frozenset({SelfManagementSurface.REST})

_OPERATION_SPECS = (
    SelfManagementOperationSpec(
        symbol_name="SELF_AGENTS_LIST",
        operation_id="self.agents.list",
        scope=SelfManagementScope.SELF,
        resource=SelfManagementResource.AGENTS,
        action=SelfManagementAction.READ,
        event_name="self_agent.list.requested",
        tool_name="self.agents.list",
        first_wave_exposed=True,
        surfaces=_SELF_ENTRY_SURFACES,
        description="List the current user's agents.",
        input_model=_AgentsListInput,
    ),
    SelfManagementOperationSpec(
        symbol_name="SELF_AGENTS_GET",
        operation_id="self.agents.get",
        scope=SelfManagementScope.SELF,
        resource=SelfManagementResource.AGENTS,
        action=SelfManagementAction.READ,
        event_name="self_agent.get.requested",
        tool_name="self.agents.get",
        first_wave_exposed=True,
        surfaces=_SELF_ENTRY_SURFACES,
        description="Read one current-user agent in detail.",
        input_model=_AgentGetInput,
    ),
    SelfManagementOperationSpec(
        symbol_name="SELF_AGENTS_CHECK_HEALTH",
        operation_id="self.agents.check_health",
        scope=SelfManagementScope.SELF,
        resource=SelfManagementResource.AGENTS,
        action=SelfManagementAction.WRITE,
        event_name="self_agent.check_health.requested",
        tool_name="self.agents.check_health",
        first_wave_exposed=True,
        surfaces=_SELF_ENTRY_SURFACES,
        confirmation_policy=SelfManagementConfirmationPolicy.REQUIRED,
        description="Run a health check for one current-user agent.",
        input_model=_AgentCheckHealthInput,
    ),
    SelfManagementOperationSpec(
        symbol_name="SELF_AGENTS_CHECK_HEALTH_ALL",
        operation_id="self.agents.check_health_all",
        scope=SelfManagementScope.SELF,
        resource=SelfManagementResource.AGENTS,
        action=SelfManagementAction.WRITE,
        event_name="self_agent.check_health_all.requested",
        tool_name="self.agents.check_health_all",
        first_wave_exposed=True,
        surfaces=_SELF_ENTRY_SURFACES,
        confirmation_policy=SelfManagementConfirmationPolicy.REQUIRED,
        description="Run a health check sweep for all current-user agents.",
        input_model=_AgentsCheckHealthAllInput,
    ),
    SelfManagementOperationSpec(
        symbol_name="SELF_AGENTS_CREATE",
        operation_id="self.agents.create",
        scope=SelfManagementScope.SELF,
        resource=SelfManagementResource.AGENTS,
        action=SelfManagementAction.WRITE,
        event_name="self_agent.create.requested",
        tool_name="self.agents.create",
        first_wave_exposed=True,
        surfaces=_SELF_ENTRY_SURFACES,
        confirmation_policy=SelfManagementConfirmationPolicy.REQUIRED,
        description="Create one current-user agent.",
        input_model=_AgentCreateInput,
    ),
    SelfManagementOperationSpec(
        symbol_name="SELF_AGENTS_UPDATE_CONFIG",
        operation_id="self.agents.update_config",
        scope=SelfManagementScope.SELF,
        resource=SelfManagementResource.AGENTS,
        action=SelfManagementAction.WRITE,
        event_name="self_agent.update_config.requested",
        tool_name="self.agents.update_config",
        first_wave_exposed=True,
        surfaces=_SELF_ENTRY_SURFACES,
        confirmation_policy=SelfManagementConfirmationPolicy.REQUIRED,
        description="Update one current-user agent.",
        input_model=_AgentUpdateConfigInput,
    ),
    SelfManagementOperationSpec(
        symbol_name="SELF_AGENTS_DELETE",
        operation_id="self.agents.delete",
        scope=SelfManagementScope.SELF,
        resource=SelfManagementResource.AGENTS,
        action=SelfManagementAction.WRITE,
        event_name="self_agent.delete.requested",
        tool_name="self.agents.delete",
        first_wave_exposed=True,
        surfaces=_SELF_ENTRY_SURFACES,
        confirmation_policy=SelfManagementConfirmationPolicy.REQUIRED,
        description="Soft-delete one current-user agent.",
        input_model=_AgentGetInput,
    ),
    SelfManagementOperationSpec(
        symbol_name="SELF_AGENTS_START_SESSIONS",
        operation_id="self.agents.start_sessions",
        scope=SelfManagementScope.SELF,
        resource=SelfManagementResource.AGENTS,
        action=SelfManagementAction.WRITE,
        event_name="self_agent.start_sessions.requested",
        tool_name="self.agents.start_sessions",
        first_wave_exposed=True,
        surfaces=_SELF_ENTRY_SURFACES,
        confirmation_policy=SelfManagementConfirmationPolicy.REQUIRED,
        description=(
            "Start one or more new conversations for the current user's agents, "
            "send a delegated message, and hand each conversation off to the "
            "platform-managed target session without waiting for replies. In the "
            "built-in self-management conversation, accepted target conversations "
            "are automatically added to durable follow-up tracking."
        ),
        input_model=_AgentsStartSessionsInput,
    ),
    SelfManagementOperationSpec(
        symbol_name="SELF_FOLLOWUPS_GET",
        operation_id="self.followups.get",
        scope=SelfManagementScope.SELF,
        resource=SelfManagementResource.FOLLOWUPS,
        action=SelfManagementAction.READ,
        event_name="self_followup.get.requested",
        tool_name="self.followups.get",
        first_wave_exposed=True,
        surfaces=_WEB_AGENT_ONLY_SURFACES,
        description=(
            "Read the current durable follow-up tracking state for the active "
            "built-in self-management conversation, including host-managed "
            "auto-tracked delegated targets."
        ),
        input_model=_FollowUpsGetInput,
    ),
    SelfManagementOperationSpec(
        symbol_name="SELF_FOLLOWUPS_SET_SESSIONS",
        operation_id="self.followups.set_sessions",
        scope=SelfManagementScope.SELF,
        resource=SelfManagementResource.FOLLOWUPS,
        action=SelfManagementAction.WRITE,
        event_name="self_followup.set_sessions.requested",
        tool_name="self.followups.set_sessions",
        first_wave_exposed=True,
        surfaces=_WEB_AGENT_ONLY_SURFACES,
        description=(
            "Override the current tracked target conversation ids for the active "
            "built-in self-management conversation. Use this to narrow, extend, "
            "replace, or stop future follow-up wakeups by passing an empty list."
        ),
        input_model=_FollowUpsSetSessionsInput,
    ),
    SelfManagementOperationSpec(
        symbol_name="SELF_SESSIONS_LIST",
        operation_id="self.sessions.list",
        scope=SelfManagementScope.SELF,
        resource=SelfManagementResource.SESSIONS,
        action=SelfManagementAction.READ,
        event_name="self_session.list.requested",
        tool_name="self.sessions.list",
        first_wave_exposed=True,
        surfaces=_SELF_ENTRY_SURFACES,
        description="List the current user's sessions.",
        input_model=_SessionsListInput,
    ),
    SelfManagementOperationSpec(
        symbol_name="SELF_SESSIONS_GET",
        operation_id="self.sessions.get",
        scope=SelfManagementScope.SELF,
        resource=SelfManagementResource.SESSIONS,
        action=SelfManagementAction.READ,
        event_name="self_session.get.requested",
        tool_name="self.sessions.get",
        first_wave_exposed=True,
        surfaces=_SELF_ENTRY_SURFACES,
        description="Read one current-user session in detail.",
        input_model=_SessionGetInput,
    ),
    SelfManagementOperationSpec(
        symbol_name="SELF_SESSIONS_GET_LATEST_MESSAGES",
        operation_id="self.sessions.get_latest_messages",
        scope=SelfManagementScope.SELF,
        resource=SelfManagementResource.SESSIONS,
        action=SelfManagementAction.READ,
        event_name="self_session.get_latest_messages.requested",
        tool_name="self.sessions.get_latest_messages",
        first_wave_exposed=True,
        surfaces=_SELF_ENTRY_SURFACES,
        description=(
            "Read the latest persisted text messages for one or more current-user "
            "sessions, optionally wait within a bounded budget for new target-agent "
            "text results, and ignore reasoning, tool-call, and interrupt lifecycle "
            "details."
        ),
        input_model=_SessionsGetLatestMessagesInput,
    ),
    SelfManagementOperationSpec(
        symbol_name="SELF_SESSIONS_UPDATE",
        operation_id="self.sessions.update",
        scope=SelfManagementScope.SELF,
        resource=SelfManagementResource.SESSIONS,
        action=SelfManagementAction.WRITE,
        event_name="self_session.update.requested",
        tool_name="self.sessions.update",
        first_wave_exposed=True,
        surfaces=_SELF_ENTRY_SURFACES,
        confirmation_policy=SelfManagementConfirmationPolicy.REQUIRED,
        description="Update one current-user session.",
        input_model=_SessionUpdateInput,
    ),
    SelfManagementOperationSpec(
        symbol_name="SELF_SESSIONS_ARCHIVE",
        operation_id="self.sessions.archive",
        scope=SelfManagementScope.SELF,
        resource=SelfManagementResource.SESSIONS,
        action=SelfManagementAction.WRITE,
        event_name="self_session.archive.requested",
        tool_name="self.sessions.archive",
        first_wave_exposed=True,
        surfaces=_SELF_ENTRY_SURFACES,
        confirmation_policy=SelfManagementConfirmationPolicy.REQUIRED,
        description="Archive one current-user session as a soft delete.",
        input_model=_SessionGetInput,
    ),
    SelfManagementOperationSpec(
        symbol_name="SELF_SESSIONS_UNARCHIVE",
        operation_id="self.sessions.unarchive",
        scope=SelfManagementScope.SELF,
        resource=SelfManagementResource.SESSIONS,
        action=SelfManagementAction.WRITE,
        event_name="self_session.unarchive.requested",
        tool_name="self.sessions.unarchive",
        first_wave_exposed=True,
        surfaces=_SELF_ENTRY_SURFACES,
        confirmation_policy=SelfManagementConfirmationPolicy.REQUIRED,
        description="Restore one archived current-user session.",
        input_model=_SessionGetInput,
    ),
    SelfManagementOperationSpec(
        symbol_name="SELF_SESSIONS_SEND_MESSAGE",
        operation_id="self.sessions.send_message",
        scope=SelfManagementScope.SELF,
        resource=SelfManagementResource.SESSIONS,
        action=SelfManagementAction.WRITE,
        event_name="self_session.send_message.requested",
        tool_name="self.sessions.send_message",
        first_wave_exposed=True,
        surfaces=_SELF_ENTRY_SURFACES,
        confirmation_policy=SelfManagementConfirmationPolicy.REQUIRED,
        description=(
            "Send one delegated message to one or more current-user conversations "
            "and hand each conversation off to the platform-managed target session "
            "without waiting for replies. In the built-in self-management "
            "conversation, accepted target conversations are automatically added "
            "to durable follow-up tracking."
        ),
        input_model=_SessionsSendMessageInput,
    ),
    SelfManagementOperationSpec(
        symbol_name="SELF_JOBS_LIST",
        operation_id="self.jobs.list",
        scope=SelfManagementScope.SELF,
        resource=SelfManagementResource.JOBS,
        action=SelfManagementAction.READ,
        event_name="self_job.list.requested",
        tool_name="self.jobs.list",
        first_wave_exposed=True,
        surfaces=_SELF_ENTRY_SURFACES,
        description="List the current user's jobs.",
        input_model=_JobsListInput,
    ),
    SelfManagementOperationSpec(
        symbol_name="SELF_JOBS_GET",
        operation_id="self.jobs.get",
        scope=SelfManagementScope.SELF,
        resource=SelfManagementResource.JOBS,
        action=SelfManagementAction.READ,
        event_name="self_job.get.requested",
        tool_name="self.jobs.get",
        first_wave_exposed=True,
        surfaces=_SELF_ENTRY_SURFACES,
        description="Read one current-user job in detail.",
        input_model=_JobGetInput,
    ),
    SelfManagementOperationSpec(
        symbol_name="SELF_JOBS_CREATE",
        operation_id="self.jobs.create",
        scope=SelfManagementScope.SELF,
        resource=SelfManagementResource.JOBS,
        action=SelfManagementAction.WRITE,
        event_name="self_job.create.requested",
        tool_name="self.jobs.create",
        first_wave_exposed=True,
        surfaces=_SELF_ENTRY_SURFACES,
        confirmation_policy=SelfManagementConfirmationPolicy.REQUIRED,
        description=(
            "Create one current-user job. For `conversation_policy`, use the exact "
            "enum `new_each_run` or `reuse_single`."
        ),
        input_model=_JobsCreateInput,
    ),
    SelfManagementOperationSpec(
        symbol_name="SELF_JOBS_PAUSE",
        operation_id="self.jobs.pause",
        scope=SelfManagementScope.SELF,
        resource=SelfManagementResource.JOBS,
        action=SelfManagementAction.WRITE,
        event_name="self_job.pause.requested",
        tool_name="self.jobs.pause",
        first_wave_exposed=True,
        surfaces=_SELF_ENTRY_SURFACES,
        confirmation_policy=SelfManagementConfirmationPolicy.REQUIRED,
        description="Pause one current-user job.",
        input_model=_JobGetInput,
    ),
    SelfManagementOperationSpec(
        symbol_name="SELF_JOBS_RESUME",
        operation_id="self.jobs.resume",
        scope=SelfManagementScope.SELF,
        resource=SelfManagementResource.JOBS,
        action=SelfManagementAction.WRITE,
        event_name="self_job.resume.requested",
        tool_name="self.jobs.resume",
        first_wave_exposed=True,
        surfaces=_SELF_ENTRY_SURFACES,
        confirmation_policy=SelfManagementConfirmationPolicy.REQUIRED,
        description="Resume one current-user job.",
        input_model=_JobGetInput,
    ),
    SelfManagementOperationSpec(
        symbol_name="SELF_JOBS_UPDATE_PROMPT",
        operation_id="self.jobs.update_prompt",
        scope=SelfManagementScope.SELF,
        resource=SelfManagementResource.JOBS,
        action=SelfManagementAction.WRITE,
        event_name="self_job.update_prompt.requested",
        tool_name="self.jobs.update_prompt",
        first_wave_exposed=True,
        surfaces=_SELF_ENTRY_SURFACES,
        confirmation_policy=SelfManagementConfirmationPolicy.REQUIRED,
        description="Update the prompt of one current-user job.",
        input_model=_JobUpdatePromptInput,
    ),
    SelfManagementOperationSpec(
        symbol_name="SELF_JOBS_UPDATE",
        operation_id="self.jobs.update",
        scope=SelfManagementScope.SELF,
        resource=SelfManagementResource.JOBS,
        action=SelfManagementAction.WRITE,
        event_name="self_job.update.requested",
        tool_name="self.jobs.update",
        first_wave_exposed=True,
        surfaces=_SELF_ENTRY_SURFACES,
        confirmation_policy=SelfManagementConfirmationPolicy.REQUIRED,
        description=(
            "Update one current-user job. For `conversation_policy`, use the exact "
            "enum `new_each_run` or `reuse_single`."
        ),
        input_model=_JobUpdateInput,
    ),
    SelfManagementOperationSpec(
        symbol_name="SELF_JOBS_UPDATE_SCHEDULE",
        operation_id="self.jobs.update_schedule",
        scope=SelfManagementScope.SELF,
        resource=SelfManagementResource.JOBS,
        action=SelfManagementAction.WRITE,
        event_name="self_job.update_schedule.requested",
        tool_name="self.jobs.update_schedule",
        first_wave_exposed=True,
        surfaces=_SELF_ENTRY_SURFACES,
        confirmation_policy=SelfManagementConfirmationPolicy.REQUIRED,
        description="Update the schedule of one current-user job.",
        input_model=_JobUpdateScheduleInput,
    ),
    SelfManagementOperationSpec(
        symbol_name="SELF_JOBS_DELETE",
        operation_id="self.jobs.delete",
        scope=SelfManagementScope.SELF,
        resource=SelfManagementResource.JOBS,
        action=SelfManagementAction.WRITE,
        event_name="self_job.delete.requested",
        tool_name="self.jobs.delete",
        first_wave_exposed=True,
        surfaces=_SELF_ENTRY_SURFACES,
        confirmation_policy=SelfManagementConfirmationPolicy.REQUIRED,
        description="Soft-delete one current-user job.",
        input_model=_JobGetInput,
    ),
    SelfManagementOperationSpec(
        symbol_name="ADMIN_HUB_AGENTS_LIST",
        operation_id="admin.agents.list",
        scope=SelfManagementScope.ADMIN,
        resource=SelfManagementResource.AGENTS,
        action=SelfManagementAction.READ,
        event_name="hub_agent.list.requested",
        surfaces=_REST_ONLY_SURFACES,
    ),
    SelfManagementOperationSpec(
        symbol_name="ADMIN_HUB_AGENTS_GET",
        operation_id="admin.agents.get",
        scope=SelfManagementScope.ADMIN,
        resource=SelfManagementResource.AGENTS,
        action=SelfManagementAction.READ,
        event_name="hub_agent.get.requested",
        surfaces=_REST_ONLY_SURFACES,
    ),
    SelfManagementOperationSpec(
        symbol_name="ADMIN_HUB_AGENTS_CREATE",
        operation_id="admin.agents.create",
        scope=SelfManagementScope.ADMIN,
        resource=SelfManagementResource.AGENTS,
        action=SelfManagementAction.WRITE,
        event_name="hub_agent.create.requested",
        surfaces=_REST_ONLY_SURFACES,
    ),
    SelfManagementOperationSpec(
        symbol_name="ADMIN_HUB_AGENTS_UPDATE",
        operation_id="admin.agents.update",
        scope=SelfManagementScope.ADMIN,
        resource=SelfManagementResource.AGENTS,
        action=SelfManagementAction.WRITE,
        event_name="hub_agent.update.requested",
        surfaces=_REST_ONLY_SURFACES,
    ),
    SelfManagementOperationSpec(
        symbol_name="ADMIN_HUB_AGENTS_DELETE",
        operation_id="admin.agents.delete",
        scope=SelfManagementScope.ADMIN,
        resource=SelfManagementResource.AGENTS,
        action=SelfManagementAction.WRITE,
        event_name="hub_agent.delete.requested",
        surfaces=_REST_ONLY_SURFACES,
    ),
    SelfManagementOperationSpec(
        symbol_name="ADMIN_HUB_AGENT_ALLOWLIST_LIST",
        operation_id="admin.agents.allowlist.list",
        scope=SelfManagementScope.ADMIN,
        resource=SelfManagementResource.AGENTS,
        action=SelfManagementAction.READ,
        event_name="hub_agent.allowlist.list.requested",
        surfaces=_REST_ONLY_SURFACES,
    ),
    SelfManagementOperationSpec(
        symbol_name="ADMIN_HUB_AGENT_ALLOWLIST_ADD",
        operation_id="admin.agents.allowlist.add",
        scope=SelfManagementScope.ADMIN,
        resource=SelfManagementResource.AGENTS,
        action=SelfManagementAction.WRITE,
        event_name="hub_agent.allowlist.add.requested",
        surfaces=_REST_ONLY_SURFACES,
    ),
    SelfManagementOperationSpec(
        symbol_name="ADMIN_HUB_AGENT_ALLOWLIST_REPLACE",
        operation_id="admin.agents.allowlist.replace",
        scope=SelfManagementScope.ADMIN,
        resource=SelfManagementResource.AGENTS,
        action=SelfManagementAction.WRITE,
        event_name="hub_agent.allowlist.replace.requested",
        surfaces=_REST_ONLY_SURFACES,
    ),
    SelfManagementOperationSpec(
        symbol_name="ADMIN_HUB_AGENT_ALLOWLIST_REMOVE",
        operation_id="admin.agents.allowlist.remove",
        scope=SelfManagementScope.ADMIN,
        resource=SelfManagementResource.AGENTS,
        action=SelfManagementAction.WRITE,
        event_name="hub_agent.allowlist.remove.requested",
        surfaces=_REST_ONLY_SURFACES,
    ),
)

_OPERATION_SPECS_BY_ID = {spec.operation_id: spec for spec in _OPERATION_SPECS}


def get_self_management_operation_spec(
    operation_id: str,
) -> SelfManagementOperationSpec:
    """Resolve one registered operation spec by id."""

    try:
        return _OPERATION_SPECS_BY_ID[operation_id]
    except KeyError as exc:
        raise KeyError(f"Unknown self-management operation: {operation_id}") from exc


def list_self_management_operation_specs(
    *,
    first_wave_only: bool = True,
) -> tuple[SelfManagementOperationSpec, ...]:
    """List registered operation specs in declarative order."""

    if not first_wave_only:
        return _OPERATION_SPECS
    return tuple(spec for spec in _OPERATION_SPECS if spec.first_wave_exposed)


def get_self_management_input_model(operation_id: str) -> type[BaseModel] | None:
    """Resolve the registered input model for one operation id."""

    return get_self_management_operation_spec(operation_id).input_model
