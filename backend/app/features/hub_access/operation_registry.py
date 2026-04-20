"""Declarative registry for hub operations and tool inputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.features.hub_access.actor_context import (
    HubAction,
    HubResource,
    HubScope,
)
from app.features.hub_access.operation_gateway import (
    HubConfirmationPolicy,
    HubOperation,
    HubSurface,
)


class _StrictBaseModel(BaseModel):
    """Base model for strict Hub Assistant tool input schemas."""

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
class HubOperationSpec:
    """Declarative metadata for one registered Hub Assistant operation."""

    symbol_name: str
    operation_id: str
    scope: HubScope
    resource: HubResource
    action: HubAction
    event_name: str
    surfaces: frozenset[HubSurface]
    confirmation_policy: HubConfirmationPolicy = HubConfirmationPolicy.NONE
    first_wave_exposed: bool = False
    description: str | None = None
    tool_name: str | None = None
    delegated_by: str | None = None
    input_model: type[BaseModel] | None = None

    def build_operation(self) -> HubOperation:
        """Build a runtime operation from this declarative spec."""

        return HubOperation(
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


_HUB_ASSISTANT_ENTRY_SURFACES = frozenset(
    {
        HubSurface.REST,
        HubSurface.WEB_AGENT,
    }
)
_WEB_AGENT_ONLY_SURFACES = frozenset({HubSurface.WEB_AGENT})
_REST_ONLY_SURFACES = frozenset({HubSurface.REST})

_OPERATION_SPECS = (
    HubOperationSpec(
        symbol_name="HUB_ASSISTANT_AGENTS_LIST",
        operation_id="hub_assistant.agents.list",
        scope=HubScope.SELF,
        resource=HubResource.AGENTS,
        action=HubAction.READ,
        event_name="hub_assistant_agent.list.requested",
        tool_name="hub_assistant.agents.list",
        first_wave_exposed=True,
        surfaces=_HUB_ASSISTANT_ENTRY_SURFACES,
        description="List the current user's agents.",
        input_model=_AgentsListInput,
    ),
    HubOperationSpec(
        symbol_name="HUB_ASSISTANT_AGENTS_GET",
        operation_id="hub_assistant.agents.get",
        scope=HubScope.SELF,
        resource=HubResource.AGENTS,
        action=HubAction.READ,
        event_name="hub_assistant_agent.get.requested",
        tool_name="hub_assistant.agents.get",
        first_wave_exposed=True,
        surfaces=_HUB_ASSISTANT_ENTRY_SURFACES,
        description="Read one current-user agent in detail.",
        input_model=_AgentGetInput,
    ),
    HubOperationSpec(
        symbol_name="HUB_ASSISTANT_AGENTS_CHECK_HEALTH",
        operation_id="hub_assistant.agents.check_health",
        scope=HubScope.SELF,
        resource=HubResource.AGENTS,
        action=HubAction.WRITE,
        event_name="hub_assistant_agent.check_health.requested",
        tool_name="hub_assistant.agents.check_health",
        first_wave_exposed=True,
        surfaces=_HUB_ASSISTANT_ENTRY_SURFACES,
        confirmation_policy=HubConfirmationPolicy.REQUIRED,
        description="Run a health check for one current-user agent.",
        input_model=_AgentCheckHealthInput,
    ),
    HubOperationSpec(
        symbol_name="HUB_ASSISTANT_AGENTS_CHECK_HEALTH_ALL",
        operation_id="hub_assistant.agents.check_health_all",
        scope=HubScope.SELF,
        resource=HubResource.AGENTS,
        action=HubAction.WRITE,
        event_name="hub_assistant_agent.check_health_all.requested",
        tool_name="hub_assistant.agents.check_health_all",
        first_wave_exposed=True,
        surfaces=_HUB_ASSISTANT_ENTRY_SURFACES,
        confirmation_policy=HubConfirmationPolicy.REQUIRED,
        description="Run a health check sweep for all current-user agents.",
        input_model=_AgentsCheckHealthAllInput,
    ),
    HubOperationSpec(
        symbol_name="HUB_ASSISTANT_AGENTS_CREATE",
        operation_id="hub_assistant.agents.create",
        scope=HubScope.SELF,
        resource=HubResource.AGENTS,
        action=HubAction.WRITE,
        event_name="hub_assistant_agent.create.requested",
        tool_name="hub_assistant.agents.create",
        first_wave_exposed=True,
        surfaces=_HUB_ASSISTANT_ENTRY_SURFACES,
        confirmation_policy=HubConfirmationPolicy.REQUIRED,
        description="Create one current-user agent.",
        input_model=_AgentCreateInput,
    ),
    HubOperationSpec(
        symbol_name="HUB_ASSISTANT_AGENTS_UPDATE_CONFIG",
        operation_id="hub_assistant.agents.update_config",
        scope=HubScope.SELF,
        resource=HubResource.AGENTS,
        action=HubAction.WRITE,
        event_name="hub_assistant_agent.update_config.requested",
        tool_name="hub_assistant.agents.update_config",
        first_wave_exposed=True,
        surfaces=_HUB_ASSISTANT_ENTRY_SURFACES,
        confirmation_policy=HubConfirmationPolicy.REQUIRED,
        description="Update one current-user agent.",
        input_model=_AgentUpdateConfigInput,
    ),
    HubOperationSpec(
        symbol_name="HUB_ASSISTANT_AGENTS_DELETE",
        operation_id="hub_assistant.agents.delete",
        scope=HubScope.SELF,
        resource=HubResource.AGENTS,
        action=HubAction.WRITE,
        event_name="hub_assistant_agent.delete.requested",
        tool_name="hub_assistant.agents.delete",
        first_wave_exposed=True,
        surfaces=_HUB_ASSISTANT_ENTRY_SURFACES,
        confirmation_policy=HubConfirmationPolicy.REQUIRED,
        description="Soft-delete one current-user agent.",
        input_model=_AgentGetInput,
    ),
    HubOperationSpec(
        symbol_name="HUB_ASSISTANT_AGENTS_START_SESSIONS",
        operation_id="hub_assistant.agents.start_sessions",
        scope=HubScope.SELF,
        resource=HubResource.AGENTS,
        action=HubAction.WRITE,
        event_name="hub_assistant_agent.start_sessions.requested",
        tool_name="hub_assistant.agents.start_sessions",
        first_wave_exposed=True,
        surfaces=_HUB_ASSISTANT_ENTRY_SURFACES,
        confirmation_policy=HubConfirmationPolicy.REQUIRED,
        description=(
            "Start one or more new conversations for the current user's agents, "
            "send a delegated message, and hand each conversation off to the "
            "platform-managed target session without waiting for replies. In the "
            "Hub Assistant Hub Assistant conversation, accepted target conversations "
            "are automatically added to durable follow-up tracking."
        ),
        input_model=_AgentsStartSessionsInput,
    ),
    HubOperationSpec(
        symbol_name="HUB_ASSISTANT_FOLLOWUPS_GET",
        operation_id="hub_assistant.followups.get",
        scope=HubScope.SELF,
        resource=HubResource.FOLLOWUPS,
        action=HubAction.READ,
        event_name="hub_assistant_followup.get.requested",
        tool_name="hub_assistant.followups.get",
        first_wave_exposed=True,
        surfaces=_WEB_AGENT_ONLY_SURFACES,
        description=(
            "Read the current durable follow-up tracking state for the active "
            "Hub Assistant Hub Assistant conversation, including host-managed "
            "auto-tracked delegated targets."
        ),
        input_model=_FollowUpsGetInput,
    ),
    HubOperationSpec(
        symbol_name="HUB_ASSISTANT_FOLLOWUPS_SET_SESSIONS",
        operation_id="hub_assistant.followups.set_sessions",
        scope=HubScope.SELF,
        resource=HubResource.FOLLOWUPS,
        action=HubAction.WRITE,
        event_name="hub_assistant_followup.set_sessions.requested",
        tool_name="hub_assistant.followups.set_sessions",
        first_wave_exposed=True,
        surfaces=_WEB_AGENT_ONLY_SURFACES,
        description=(
            "Override the current tracked target conversation ids for the active "
            "Hub Assistant Hub Assistant conversation. Use this to narrow, extend, "
            "replace, or stop future follow-up wakeups by passing an empty list."
        ),
        input_model=_FollowUpsSetSessionsInput,
    ),
    HubOperationSpec(
        symbol_name="HUB_ASSISTANT_SESSIONS_LIST",
        operation_id="hub_assistant.sessions.list",
        scope=HubScope.SELF,
        resource=HubResource.SESSIONS,
        action=HubAction.READ,
        event_name="hub_assistant_session.list.requested",
        tool_name="hub_assistant.sessions.list",
        first_wave_exposed=True,
        surfaces=_HUB_ASSISTANT_ENTRY_SURFACES,
        description="List the current user's sessions.",
        input_model=_SessionsListInput,
    ),
    HubOperationSpec(
        symbol_name="HUB_ASSISTANT_SESSIONS_GET",
        operation_id="hub_assistant.sessions.get",
        scope=HubScope.SELF,
        resource=HubResource.SESSIONS,
        action=HubAction.READ,
        event_name="hub_assistant_session.get.requested",
        tool_name="hub_assistant.sessions.get",
        first_wave_exposed=True,
        surfaces=_HUB_ASSISTANT_ENTRY_SURFACES,
        description="Read one current-user session in detail.",
        input_model=_SessionGetInput,
    ),
    HubOperationSpec(
        symbol_name="HUB_ASSISTANT_SESSIONS_GET_LATEST_MESSAGES",
        operation_id="hub_assistant.sessions.get_latest_messages",
        scope=HubScope.SELF,
        resource=HubResource.SESSIONS,
        action=HubAction.READ,
        event_name="hub_assistant_session.get_latest_messages.requested",
        tool_name="hub_assistant.sessions.get_latest_messages",
        first_wave_exposed=True,
        surfaces=_HUB_ASSISTANT_ENTRY_SURFACES,
        description=(
            "Read the latest persisted text messages for one or more current-user "
            "sessions, optionally wait within a bounded budget for new target-agent "
            "text results, and ignore reasoning, tool-call, and interrupt lifecycle "
            "details."
        ),
        input_model=_SessionsGetLatestMessagesInput,
    ),
    HubOperationSpec(
        symbol_name="HUB_ASSISTANT_SESSIONS_UPDATE",
        operation_id="hub_assistant.sessions.update",
        scope=HubScope.SELF,
        resource=HubResource.SESSIONS,
        action=HubAction.WRITE,
        event_name="hub_assistant_session.update.requested",
        tool_name="hub_assistant.sessions.update",
        first_wave_exposed=True,
        surfaces=_HUB_ASSISTANT_ENTRY_SURFACES,
        confirmation_policy=HubConfirmationPolicy.REQUIRED,
        description="Update one current-user session.",
        input_model=_SessionUpdateInput,
    ),
    HubOperationSpec(
        symbol_name="HUB_ASSISTANT_SESSIONS_ARCHIVE",
        operation_id="hub_assistant.sessions.archive",
        scope=HubScope.SELF,
        resource=HubResource.SESSIONS,
        action=HubAction.WRITE,
        event_name="hub_assistant_session.archive.requested",
        tool_name="hub_assistant.sessions.archive",
        first_wave_exposed=True,
        surfaces=_HUB_ASSISTANT_ENTRY_SURFACES,
        confirmation_policy=HubConfirmationPolicy.REQUIRED,
        description="Archive one current-user session as a soft delete.",
        input_model=_SessionGetInput,
    ),
    HubOperationSpec(
        symbol_name="HUB_ASSISTANT_SESSIONS_UNARCHIVE",
        operation_id="hub_assistant.sessions.unarchive",
        scope=HubScope.SELF,
        resource=HubResource.SESSIONS,
        action=HubAction.WRITE,
        event_name="hub_assistant_session.unarchive.requested",
        tool_name="hub_assistant.sessions.unarchive",
        first_wave_exposed=True,
        surfaces=_HUB_ASSISTANT_ENTRY_SURFACES,
        confirmation_policy=HubConfirmationPolicy.REQUIRED,
        description="Restore one archived current-user session.",
        input_model=_SessionGetInput,
    ),
    HubOperationSpec(
        symbol_name="HUB_ASSISTANT_SESSIONS_SEND_MESSAGE",
        operation_id="hub_assistant.sessions.send_message",
        scope=HubScope.SELF,
        resource=HubResource.SESSIONS,
        action=HubAction.WRITE,
        event_name="hub_assistant_session.send_message.requested",
        tool_name="hub_assistant.sessions.send_message",
        first_wave_exposed=True,
        surfaces=_HUB_ASSISTANT_ENTRY_SURFACES,
        confirmation_policy=HubConfirmationPolicy.REQUIRED,
        description=(
            "Send one delegated message to one or more current-user conversations "
            "and hand each conversation off to the platform-managed target session "
            "without waiting for replies. In the Hub Assistant hub-assistant "
            "conversation, accepted target conversations are automatically added "
            "to durable follow-up tracking."
        ),
        input_model=_SessionsSendMessageInput,
    ),
    HubOperationSpec(
        symbol_name="HUB_ASSISTANT_JOBS_LIST",
        operation_id="hub_assistant.jobs.list",
        scope=HubScope.SELF,
        resource=HubResource.JOBS,
        action=HubAction.READ,
        event_name="hub_assistant_job.list.requested",
        tool_name="hub_assistant.jobs.list",
        first_wave_exposed=True,
        surfaces=_HUB_ASSISTANT_ENTRY_SURFACES,
        description="List the current user's jobs.",
        input_model=_JobsListInput,
    ),
    HubOperationSpec(
        symbol_name="HUB_ASSISTANT_JOBS_GET",
        operation_id="hub_assistant.jobs.get",
        scope=HubScope.SELF,
        resource=HubResource.JOBS,
        action=HubAction.READ,
        event_name="hub_assistant_job.get.requested",
        tool_name="hub_assistant.jobs.get",
        first_wave_exposed=True,
        surfaces=_HUB_ASSISTANT_ENTRY_SURFACES,
        description="Read one current-user job in detail.",
        input_model=_JobGetInput,
    ),
    HubOperationSpec(
        symbol_name="HUB_ASSISTANT_JOBS_CREATE",
        operation_id="hub_assistant.jobs.create",
        scope=HubScope.SELF,
        resource=HubResource.JOBS,
        action=HubAction.WRITE,
        event_name="hub_assistant_job.create.requested",
        tool_name="hub_assistant.jobs.create",
        first_wave_exposed=True,
        surfaces=_HUB_ASSISTANT_ENTRY_SURFACES,
        confirmation_policy=HubConfirmationPolicy.REQUIRED,
        description=(
            "Create one current-user job. For `conversation_policy`, use the exact "
            "enum `new_each_run` or `reuse_single`."
        ),
        input_model=_JobsCreateInput,
    ),
    HubOperationSpec(
        symbol_name="HUB_ASSISTANT_JOBS_PAUSE",
        operation_id="hub_assistant.jobs.pause",
        scope=HubScope.SELF,
        resource=HubResource.JOBS,
        action=HubAction.WRITE,
        event_name="hub_assistant_job.pause.requested",
        tool_name="hub_assistant.jobs.pause",
        first_wave_exposed=True,
        surfaces=_HUB_ASSISTANT_ENTRY_SURFACES,
        confirmation_policy=HubConfirmationPolicy.REQUIRED,
        description="Pause one current-user job.",
        input_model=_JobGetInput,
    ),
    HubOperationSpec(
        symbol_name="HUB_ASSISTANT_JOBS_RESUME",
        operation_id="hub_assistant.jobs.resume",
        scope=HubScope.SELF,
        resource=HubResource.JOBS,
        action=HubAction.WRITE,
        event_name="hub_assistant_job.resume.requested",
        tool_name="hub_assistant.jobs.resume",
        first_wave_exposed=True,
        surfaces=_HUB_ASSISTANT_ENTRY_SURFACES,
        confirmation_policy=HubConfirmationPolicy.REQUIRED,
        description="Resume one current-user job.",
        input_model=_JobGetInput,
    ),
    HubOperationSpec(
        symbol_name="HUB_ASSISTANT_JOBS_UPDATE_PROMPT",
        operation_id="hub_assistant.jobs.update_prompt",
        scope=HubScope.SELF,
        resource=HubResource.JOBS,
        action=HubAction.WRITE,
        event_name="hub_assistant_job.update_prompt.requested",
        tool_name="hub_assistant.jobs.update_prompt",
        first_wave_exposed=True,
        surfaces=_HUB_ASSISTANT_ENTRY_SURFACES,
        confirmation_policy=HubConfirmationPolicy.REQUIRED,
        description="Update the prompt of one current-user job.",
        input_model=_JobUpdatePromptInput,
    ),
    HubOperationSpec(
        symbol_name="HUB_ASSISTANT_JOBS_UPDATE",
        operation_id="hub_assistant.jobs.update",
        scope=HubScope.SELF,
        resource=HubResource.JOBS,
        action=HubAction.WRITE,
        event_name="hub_assistant_job.update.requested",
        tool_name="hub_assistant.jobs.update",
        first_wave_exposed=True,
        surfaces=_HUB_ASSISTANT_ENTRY_SURFACES,
        confirmation_policy=HubConfirmationPolicy.REQUIRED,
        description=(
            "Update one current-user job. For `conversation_policy`, use the exact "
            "enum `new_each_run` or `reuse_single`."
        ),
        input_model=_JobUpdateInput,
    ),
    HubOperationSpec(
        symbol_name="HUB_ASSISTANT_JOBS_UPDATE_SCHEDULE",
        operation_id="hub_assistant.jobs.update_schedule",
        scope=HubScope.SELF,
        resource=HubResource.JOBS,
        action=HubAction.WRITE,
        event_name="hub_assistant_job.update_schedule.requested",
        tool_name="hub_assistant.jobs.update_schedule",
        first_wave_exposed=True,
        surfaces=_HUB_ASSISTANT_ENTRY_SURFACES,
        confirmation_policy=HubConfirmationPolicy.REQUIRED,
        description="Update the schedule of one current-user job.",
        input_model=_JobUpdateScheduleInput,
    ),
    HubOperationSpec(
        symbol_name="HUB_ASSISTANT_JOBS_DELETE",
        operation_id="hub_assistant.jobs.delete",
        scope=HubScope.SELF,
        resource=HubResource.JOBS,
        action=HubAction.WRITE,
        event_name="hub_assistant_job.delete.requested",
        tool_name="hub_assistant.jobs.delete",
        first_wave_exposed=True,
        surfaces=_HUB_ASSISTANT_ENTRY_SURFACES,
        confirmation_policy=HubConfirmationPolicy.REQUIRED,
        description="Soft-delete one current-user job.",
        input_model=_JobGetInput,
    ),
    HubOperationSpec(
        symbol_name="ADMIN_SHARED_A2A_AGENTS_LIST",
        operation_id="admin.agents.list",
        scope=HubScope.ADMIN,
        resource=HubResource.AGENTS,
        action=HubAction.READ,
        event_name="hub_agent.list.requested",
        surfaces=_REST_ONLY_SURFACES,
    ),
    HubOperationSpec(
        symbol_name="ADMIN_SHARED_A2A_AGENTS_GET",
        operation_id="admin.agents.get",
        scope=HubScope.ADMIN,
        resource=HubResource.AGENTS,
        action=HubAction.READ,
        event_name="hub_agent.get.requested",
        surfaces=_REST_ONLY_SURFACES,
    ),
    HubOperationSpec(
        symbol_name="ADMIN_SHARED_A2A_AGENTS_CREATE",
        operation_id="admin.agents.create",
        scope=HubScope.ADMIN,
        resource=HubResource.AGENTS,
        action=HubAction.WRITE,
        event_name="hub_agent.create.requested",
        surfaces=_REST_ONLY_SURFACES,
    ),
    HubOperationSpec(
        symbol_name="ADMIN_SHARED_A2A_AGENTS_UPDATE",
        operation_id="admin.agents.update",
        scope=HubScope.ADMIN,
        resource=HubResource.AGENTS,
        action=HubAction.WRITE,
        event_name="hub_agent.update.requested",
        surfaces=_REST_ONLY_SURFACES,
    ),
    HubOperationSpec(
        symbol_name="ADMIN_SHARED_A2A_AGENTS_DELETE",
        operation_id="admin.agents.delete",
        scope=HubScope.ADMIN,
        resource=HubResource.AGENTS,
        action=HubAction.WRITE,
        event_name="hub_agent.delete.requested",
        surfaces=_REST_ONLY_SURFACES,
    ),
    HubOperationSpec(
        symbol_name="ADMIN_SHARED_A2A_AGENT_ALLOWLIST_LIST",
        operation_id="admin.agents.allowlist.list",
        scope=HubScope.ADMIN,
        resource=HubResource.AGENTS,
        action=HubAction.READ,
        event_name="hub_agent.allowlist.list.requested",
        surfaces=_REST_ONLY_SURFACES,
    ),
    HubOperationSpec(
        symbol_name="ADMIN_SHARED_A2A_AGENT_ALLOWLIST_ADD",
        operation_id="admin.agents.allowlist.add",
        scope=HubScope.ADMIN,
        resource=HubResource.AGENTS,
        action=HubAction.WRITE,
        event_name="hub_agent.allowlist.add.requested",
        surfaces=_REST_ONLY_SURFACES,
    ),
    HubOperationSpec(
        symbol_name="ADMIN_SHARED_A2A_AGENT_ALLOWLIST_REPLACE",
        operation_id="admin.agents.allowlist.replace",
        scope=HubScope.ADMIN,
        resource=HubResource.AGENTS,
        action=HubAction.WRITE,
        event_name="hub_agent.allowlist.replace.requested",
        surfaces=_REST_ONLY_SURFACES,
    ),
    HubOperationSpec(
        symbol_name="ADMIN_SHARED_A2A_AGENT_ALLOWLIST_REMOVE",
        operation_id="admin.agents.allowlist.remove",
        scope=HubScope.ADMIN,
        resource=HubResource.AGENTS,
        action=HubAction.WRITE,
        event_name="hub_agent.allowlist.remove.requested",
        surfaces=_REST_ONLY_SURFACES,
    ),
)

_OPERATION_SPECS_BY_ID = {spec.operation_id: spec for spec in _OPERATION_SPECS}


def get_hub_operation_spec(
    operation_id: str,
) -> HubOperationSpec:
    """Resolve one registered operation spec by id."""

    try:
        return _OPERATION_SPECS_BY_ID[operation_id]
    except KeyError as exc:
        raise KeyError(f"Unknown Hub Assistant operation: {operation_id}") from exc


def list_hub_operation_specs(
    *,
    first_wave_only: bool = True,
) -> tuple[HubOperationSpec, ...]:
    """List registered operation specs in declarative order."""

    if not first_wave_only:
        return _OPERATION_SPECS
    return tuple(spec for spec in _OPERATION_SPECS if spec.first_wave_exposed)


def get_hub_operation_input_model(operation_id: str) -> type[BaseModel] | None:
    """Resolve the registered input model for one operation id."""

    return get_hub_operation_spec(operation_id).input_model
