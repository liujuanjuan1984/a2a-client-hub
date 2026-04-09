from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.deps import (
    get_current_self_management_actor,
    get_current_self_management_admin_actor,
)
from app.db.models.user import User
from app.features.agents_shared.actor_context import (
    SelfManagementAction,
    SelfManagementActorType,
    SelfManagementAuthorizationError,
    SelfManagementResource,
    SelfManagementScope,
    build_self_management_actor_context,
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


def test_build_self_management_actor_context_grants_self_scope_permissions() -> None:
    user = _build_user(is_superuser=False)

    actor = build_self_management_actor_context(
        user=user,
        actor_type=SelfManagementActorType.HUMAN_API,
    )

    assert actor.actor_type == SelfManagementActorType.HUMAN_API
    assert actor.admin_mode is False
    assert actor.principal_user_id == user.id
    assert actor.acting_user_id == user.id
    assert actor.allows(
        scope=SelfManagementScope.SELF,
        resource=SelfManagementResource.JOBS,
        action=SelfManagementAction.WRITE,
    )
    assert not actor.allows(
        scope=SelfManagementScope.ADMIN,
        resource=SelfManagementResource.JOBS,
        action=SelfManagementAction.WRITE,
    )


def test_build_self_management_actor_context_rejects_non_admin_escalation() -> None:
    user = _build_user(is_superuser=False)

    with pytest.raises(SelfManagementAuthorizationError) as exc_info:
        build_self_management_actor_context(
            user=user,
            actor_type=SelfManagementActorType.HUMAN_API,
            admin_mode=True,
        )

    assert str(exc_info.value) == "Admin mode requires superuser privileges"


def test_build_self_management_actor_context_adds_admin_scope_for_superuser() -> None:
    user = _build_user(is_superuser=True)

    actor = build_self_management_actor_context(
        user=user,
        actor_type=SelfManagementActorType.WEB_AGENT,
        admin_mode=True,
    )

    assert actor.admin_mode is True
    assert actor.is_superuser is True
    assert actor.allows(
        scope=SelfManagementScope.ADMIN,
        resource=SelfManagementResource.AGENTS,
        action=SelfManagementAction.READ,
    )


def test_direct_human_actor_cannot_impersonate_another_principal() -> None:
    user = _build_user(is_superuser=True)

    with pytest.raises(SelfManagementAuthorizationError) as exc_info:
        build_self_management_actor_context(
            user=user,
            actor_type=SelfManagementActorType.HUMAN_CLI,
            principal_user_id=uuid4(),
        )

    assert (
        str(exc_info.value)
        == "Direct human actions cannot impersonate another principal user"
    )


def test_actor_context_builds_canonical_audit_fields() -> None:
    user = _build_user(is_superuser=True)
    actor = build_self_management_actor_context(
        user=user,
        actor_type=SelfManagementActorType.WEB_AGENT,
        admin_mode=True,
    )
    target_user_id = uuid4()

    audit_fields = actor.build_audit_fields(
        event_name="hub_agent.update.requested",
        scope=SelfManagementScope.ADMIN,
        resource=SelfManagementResource.AGENTS,
        action=SelfManagementAction.WRITE,
        resource_id="agent-123",
        target_user_id=target_user_id,
        tool_name="hub.agent.update",
        delegated_by="web_built_in_agent",
    ).as_log_extra()

    assert audit_fields["audit_event_name"] == "hub_agent.update.requested"
    assert audit_fields["actor_type"] == "web_agent"
    assert audit_fields["permission_scope"] == "admin"
    assert audit_fields["resource_type"] == "agents"
    assert audit_fields["resource_action"] == "write"
    assert audit_fields["resource_id"] == "agent-123"
    assert audit_fields["target_user_id"] == str(target_user_id)
    assert audit_fields["tool_name"] == "hub.agent.update"
    assert audit_fields["delegated_by"] == "web_built_in_agent"


def test_self_management_actor_dependency_returns_default_human_api_actor() -> None:
    user = _build_user(is_superuser=False)

    actor = get_current_self_management_actor(current_user=user)

    assert actor.actor_type == SelfManagementActorType.HUMAN_API
    assert actor.admin_mode is False
    assert actor.principal_user_id == user.id


def test_self_management_admin_actor_dependency_rejects_non_superuser() -> None:
    user = _build_user(is_superuser=False)

    with pytest.raises(HTTPException) as exc_info:
        get_current_self_management_admin_actor(current_user=user)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Admin mode requires superuser privileges"
