from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.deps import (
    get_current_hub_assistant_actor,
    get_current_hub_assistant_admin_actor,
    get_current_hub_assistant_admin_tool_gateway,
    get_current_hub_assistant_tool_gateway,
)
from app.db.models.user import User
from app.features.hub_assistant.shared.actor_context import (
    HubAssistantAction,
    HubAssistantActorType,
    HubAssistantAuthorizationError,
    HubAssistantResource,
    HubAssistantScope,
    build_hub_assistant_actor_context,
)
from app.features.hub_assistant.shared.capability_catalog import (
    ADMIN_HUB_AGENTS_CREATE,
    FIRST_WAVE_EXPOSED_OPERATIONS,
    HUB_ASSISTANT_JOBS_UPDATE_SCHEDULE,
    UNSUPPORTED_FIRST_WAVE_OPERATION_IDS,
    get_hub_assistant_operation,
)
from app.features.hub_assistant.shared.tool_gateway import (
    HubAssistantOperation,
    HubAssistantSurface,
    HubAssistantToolGateway,
)


def _build_user(*, is_superuser: bool) -> User:
    return User(
        id=uuid4(),
        email=f"user-{uuid4().hex[:8]}@example.com",
        name="Test User",
        password_hash="test-password-hash",  # pragma: allowlist secret
        is_superuser=is_superuser,
        timezone="UTC",
    )


def test_build_hub_assistant_actor_context_grants_self_scope_permissions() -> None:
    user = _build_user(is_superuser=False)

    actor = build_hub_assistant_actor_context(
        user=user,
        actor_type=HubAssistantActorType.HUMAN_API,
    )

    assert actor.actor_type == HubAssistantActorType.HUMAN_API
    assert actor.admin_mode is False
    assert actor.principal_user_id == user.id
    assert actor.acting_user_id == user.id
    assert actor.allows(
        scope=HubAssistantScope.SELF,
        resource=HubAssistantResource.JOBS,
        action=HubAssistantAction.WRITE,
    )
    assert not actor.allows(
        scope=HubAssistantScope.ADMIN,
        resource=HubAssistantResource.JOBS,
        action=HubAssistantAction.WRITE,
    )


def test_build_hub_assistant_actor_context_rejects_non_admin_escalation() -> None:
    user = _build_user(is_superuser=False)

    with pytest.raises(HubAssistantAuthorizationError) as exc_info:
        build_hub_assistant_actor_context(
            user=user,
            actor_type=HubAssistantActorType.HUMAN_API,
            admin_mode=True,
        )

    assert str(exc_info.value) == "Admin mode requires superuser privileges"


def test_build_hub_assistant_actor_context_adds_admin_scope_for_superuser() -> None:
    user = _build_user(is_superuser=True)

    actor = build_hub_assistant_actor_context(
        user=user,
        actor_type=HubAssistantActorType.WEB_AGENT,
        admin_mode=True,
    )

    assert actor.admin_mode is True
    assert actor.is_superuser is True
    assert actor.allows(
        scope=HubAssistantScope.ADMIN,
        resource=HubAssistantResource.AGENTS,
        action=HubAssistantAction.READ,
    )


def test_direct_human_actor_cannot_impersonate_another_principal() -> None:
    user = _build_user(is_superuser=True)

    with pytest.raises(HubAssistantAuthorizationError) as exc_info:
        build_hub_assistant_actor_context(
            user=user,
            actor_type=HubAssistantActorType.HUMAN_API,
            principal_user_id=uuid4(),
        )

    assert (
        str(exc_info.value)
        == "Direct human actions cannot impersonate another principal user"
    )


def test_actor_context_builds_canonical_audit_fields() -> None:
    user = _build_user(is_superuser=True)
    actor = build_hub_assistant_actor_context(
        user=user,
        actor_type=HubAssistantActorType.WEB_AGENT,
        admin_mode=True,
    )
    target_user_id = uuid4()

    audit_fields = actor.build_audit_fields(
        event_name="hub_agent.update.requested",
        scope=HubAssistantScope.ADMIN,
        resource=HubAssistantResource.AGENTS,
        action=HubAssistantAction.WRITE,
        resource_id="agent-123",
        target_user_id=target_user_id,
        tool_name="hub.agent.update",
        delegated_by="web_hub_assistant",
    ).as_log_extra()

    assert audit_fields["audit_event_name"] == "hub_agent.update.requested"
    assert audit_fields["actor_type"] == "web_agent"
    assert audit_fields["permission_scope"] == "admin"
    assert audit_fields["resource_type"] == "agents"
    assert audit_fields["resource_action"] == "write"
    assert audit_fields["resource_id"] == "agent-123"
    assert audit_fields["target_user_id"] == str(target_user_id)
    assert audit_fields["tool_name"] == "hub.agent.update"
    assert audit_fields["delegated_by"] == "web_hub_assistant"


def test_tool_gateway_authorize_returns_canonical_audit_fields() -> None:
    user = _build_user(is_superuser=True)
    actor = build_hub_assistant_actor_context(
        user=user,
        actor_type=HubAssistantActorType.HUMAN_API,
        admin_mode=True,
    )
    gateway = HubAssistantToolGateway(actor, surface=HubAssistantSurface.REST)

    audit_fields = gateway.authorize(
        operation=HubAssistantOperation(
            operation_id="admin.agents.list",
            scope=HubAssistantScope.ADMIN,
            resource=HubAssistantResource.AGENTS,
            action=HubAssistantAction.READ,
            event_name="hub_agent.list.requested",
        ),
        resource_id="shared-catalog",
    ).as_log_extra()

    assert audit_fields["audit_event_name"] == "hub_agent.list.requested"
    assert audit_fields["resource_type"] == "agents"
    assert audit_fields["resource_action"] == "read"
    assert audit_fields["resource_id"] == "shared-catalog"
    assert audit_fields["operation_id"] == "admin.agents.list"
    assert audit_fields["confirmation_policy"] == "none"


@pytest.mark.asyncio
async def test_tool_gateway_execute_returns_result_and_audit_fields() -> None:
    user = _build_user(is_superuser=False)
    actor = build_hub_assistant_actor_context(
        user=user,
        actor_type=HubAssistantActorType.HUMAN_API,
    )
    gateway = HubAssistantToolGateway(actor, surface=HubAssistantSurface.REST)

    executed = await gateway.execute(
        operation=HubAssistantOperation(
            operation_id="self.jobs.update",
            scope=HubAssistantScope.SELF,
            resource=HubAssistantResource.JOBS,
            action=HubAssistantAction.WRITE,
            event_name="job.update.requested",
        ),
        resource_id="job-123",
        handler=lambda: _return_value("ok"),
    )

    assert executed.result == "ok"
    assert executed.audit_fields.event_name == "job.update.requested"
    assert executed.audit_fields.resource_id == "job-123"
    assert executed.audit_fields.operation_id == "self.jobs.update"


def test_tool_gateway_rejects_unauthorized_admin_operation() -> None:
    user = _build_user(is_superuser=False)
    actor = build_hub_assistant_actor_context(
        user=user,
        actor_type=HubAssistantActorType.HUMAN_API,
    )
    gateway = HubAssistantToolGateway(actor, surface=HubAssistantSurface.REST)

    with pytest.raises(HubAssistantAuthorizationError) as exc_info:
        gateway.authorize(
            operation=HubAssistantOperation(
                operation_id="admin.agents.update",
                scope=HubAssistantScope.ADMIN,
                resource=HubAssistantResource.AGENTS,
                action=HubAssistantAction.WRITE,
                event_name="hub_agent.update.requested",
            )
        )

    assert str(exc_info.value) == "Actor is not allowed to perform admin:agents:write"


def test_tool_gateway_rejects_surface_not_exposed_by_operation() -> None:
    user = _build_user(is_superuser=False)
    actor = build_hub_assistant_actor_context(
        user=user,
        actor_type=HubAssistantActorType.HUMAN_API,
    )
    gateway = HubAssistantToolGateway(actor, surface=HubAssistantSurface.REST)

    with pytest.raises(HubAssistantAuthorizationError) as exc_info:
        gateway.authorize(
            operation=HubAssistantOperation(
                operation_id="self.jobs.rest_only",
                scope=HubAssistantScope.SELF,
                resource=HubAssistantResource.JOBS,
                action=HubAssistantAction.READ,
                event_name="self_job.list.requested",
                surfaces=frozenset({HubAssistantSurface.WEB_AGENT}),
            )
        )

    assert (
        str(exc_info.value)
        == "Operation `self.jobs.rest_only` is not exposed on `rest`."
    )


def test_hub_assistant_actor_dependency_returns_default_human_api_actor() -> None:
    user = _build_user(is_superuser=False)

    actor = get_current_hub_assistant_actor(current_user=user)

    assert actor.actor_type == HubAssistantActorType.HUMAN_API
    assert actor.admin_mode is False
    assert actor.principal_user_id == user.id


def test_hub_assistant_tool_gateway_dependency_wraps_default_actor() -> None:
    user = _build_user(is_superuser=False)

    gateway = get_current_hub_assistant_tool_gateway(
        actor=get_current_hub_assistant_actor(current_user=user)
    )

    assert gateway.actor.actor_type == HubAssistantActorType.HUMAN_API
    assert gateway.actor.admin_mode is False
    assert gateway.surface == HubAssistantSurface.REST


def test_hub_assistant_admin_actor_dependency_rejects_non_superuser() -> None:
    user = _build_user(is_superuser=False)

    with pytest.raises(HTTPException) as exc_info:
        get_current_hub_assistant_admin_actor(current_user=user)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Admin mode requires superuser privileges"


def test_hub_assistant_admin_tool_gateway_dependency_wraps_admin_actor() -> None:
    user = _build_user(is_superuser=True)

    gateway = get_current_hub_assistant_admin_tool_gateway(
        actor=get_current_hub_assistant_admin_actor(current_user=user)
    )

    assert gateway.actor.actor_type == HubAssistantActorType.HUMAN_API
    assert gateway.actor.admin_mode is True
    assert gateway.surface == HubAssistantSurface.REST


def test_first_wave_capability_catalog_marks_expected_write_confirmation() -> None:
    operation = get_hub_assistant_operation("hub_assistant.jobs.update_schedule")

    assert operation is HUB_ASSISTANT_JOBS_UPDATE_SCHEDULE
    assert operation.first_wave_exposed is True
    assert operation.confirmation_policy.value == "required"


def test_first_wave_capability_catalog_contains_expected_surfaces() -> None:
    exposed_ids = {item.operation_id for item in FIRST_WAVE_EXPOSED_OPERATIONS}
    rest_exposed_ids = {
        item.operation_id
        for item in FIRST_WAVE_EXPOSED_OPERATIONS
        if HubAssistantSurface.REST in item.surfaces
    }
    web_agent_only_ids = {
        item.operation_id
        for item in FIRST_WAVE_EXPOSED_OPERATIONS
        if item.surfaces == {HubAssistantSurface.WEB_AGENT}
    }

    assert "hub_assistant.jobs.list" in exposed_ids
    assert "hub_assistant.agents.check_health" in exposed_ids
    assert "hub_assistant.jobs.create" in exposed_ids
    assert "hub_assistant.followups.get" in exposed_ids
    assert "hub_assistant.followups.set_sessions" in exposed_ids
    assert "hub_assistant.sessions.get" in exposed_ids
    assert "hub_assistant.sessions.get_latest_messages" in exposed_ids
    assert "hub_assistant.sessions.archive" in exposed_ids
    assert "hub_assistant.sessions.send_message" in exposed_ids
    assert "hub_assistant.agents.create" in exposed_ids
    assert "hub_assistant.agents.start_sessions" in exposed_ids
    assert "hub_assistant.agents.update_config" in exposed_ids
    assert all(item.first_wave_exposed for item in FIRST_WAVE_EXPOSED_OPERATIONS)
    assert all(item.surfaces for item in FIRST_WAVE_EXPOSED_OPERATIONS)
    assert "hub_assistant.followups.get" not in rest_exposed_ids
    assert "hub_assistant.followups.set_sessions" not in rest_exposed_ids
    assert web_agent_only_ids == {
        "hub_assistant.followups.get",
        "hub_assistant.followups.set_sessions",
    }


def test_internal_admin_capability_is_not_first_wave_exposed() -> None:
    assert ADMIN_HUB_AGENTS_CREATE.first_wave_exposed is False
    assert {surface.value for surface in ADMIN_HUB_AGENTS_CREATE.surfaces} == {"rest"}


def test_unsupported_first_wave_operation_ids_are_explicit() -> None:
    assert "hub_assistant.sessions.delete" in UNSUPPORTED_FIRST_WAVE_OPERATION_IDS
    assert "admin.agents.delete" in UNSUPPORTED_FIRST_WAVE_OPERATION_IDS


async def _return_value(value: str) -> str:
    return value
