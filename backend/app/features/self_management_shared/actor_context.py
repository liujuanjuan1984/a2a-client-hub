"""Shared actor-context primitives for self-management entry points."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, cast
from uuid import UUID

from app.db.models.user import User


class SelfManagementAuthorizationError(PermissionError):
    """Raised when a self-management actor is not allowed to use a scope."""


class SelfManagementActorType(str, Enum):
    """Supported actor types for self-management entry points."""

    HUMAN_API = "human_api"
    WEB_AGENT = "web_agent"


class SelfManagementScope(str, Enum):
    """Permission scopes for self-management resources."""

    SELF = "self"
    ADMIN = "admin"


class SelfManagementResource(str, Enum):
    """Managed resource categories exposed by self-management entry points."""

    AGENTS = "agents"
    JOBS = "jobs"
    SESSIONS = "sessions"


class SelfManagementAction(str, Enum):
    """Allowed action buckets for self-management resources."""

    READ = "read"
    WRITE = "write"


@dataclass(frozen=True)
class PermissionGrant:
    """One permission grant over a resource scope."""

    scope: SelfManagementScope
    resource: SelfManagementResource
    actions: frozenset[SelfManagementAction]


@dataclass(frozen=True)
class PermissionEnvelope:
    """Resolved permission envelope for one authenticated actor."""

    grants: tuple[PermissionGrant, ...]

    def allows(
        self,
        *,
        scope: SelfManagementScope,
        resource: SelfManagementResource,
        action: SelfManagementAction,
    ) -> bool:
        """Return whether the resolved envelope grants the requested action."""

        for grant in self.grants:
            if (
                grant.scope == scope
                and grant.resource == resource
                and action in grant.actions
            ):
                return True
        return False


@dataclass(frozen=True)
class SelfManagementAuditFields:
    """Canonical audit fields for self-management operations."""

    event_name: str
    actor_type: SelfManagementActorType
    acting_user_id: UUID
    principal_user_id: UUID
    admin_mode: bool
    scope: SelfManagementScope
    resource: SelfManagementResource | None = None
    action: SelfManagementAction | None = None
    resource_id: str | None = None
    target_user_id: UUID | None = None
    tool_name: str | None = None
    delegated_by: str | None = None
    operation_id: str | None = None
    confirmation_policy: str | None = None

    def as_log_extra(self) -> dict[str, Any]:
        """Render audit fields into logger-friendly structured metadata."""

        return {
            "audit_event_name": self.event_name,
            "actor_type": self.actor_type.value,
            "acting_user_id": str(self.acting_user_id),
            "principal_user_id": str(self.principal_user_id),
            "admin_mode": self.admin_mode,
            "permission_scope": self.scope.value,
            "resource_type": self.resource.value if self.resource is not None else None,
            "resource_action": self.action.value if self.action is not None else None,
            "resource_id": self.resource_id,
            "target_user_id": (
                str(self.target_user_id) if self.target_user_id is not None else None
            ),
            "tool_name": self.tool_name,
            "delegated_by": self.delegated_by,
            "operation_id": self.operation_id,
            "confirmation_policy": self.confirmation_policy,
        }


@dataclass(frozen=True)
class SelfManagementActorContext:
    """Resolved actor context for self-management entry points."""

    actor_type: SelfManagementActorType
    acting_user_id: UUID
    principal_user_id: UUID
    admin_mode: bool
    is_superuser: bool
    permission_envelope: PermissionEnvelope

    def allows(
        self,
        *,
        scope: SelfManagementScope,
        resource: SelfManagementResource,
        action: SelfManagementAction,
    ) -> bool:
        """Return whether the current actor can execute the requested action."""

        return self.permission_envelope.allows(
            scope=scope,
            resource=resource,
            action=action,
        )

    def build_audit_fields(
        self,
        *,
        event_name: str,
        scope: SelfManagementScope | None = None,
        resource: SelfManagementResource | None = None,
        action: SelfManagementAction | None = None,
        resource_id: str | None = None,
        target_user_id: UUID | None = None,
        tool_name: str | None = None,
        delegated_by: str | None = None,
        operation_id: str | None = None,
        confirmation_policy: str | None = None,
    ) -> SelfManagementAuditFields:
        """Build canonical audit fields for one actor-mediated operation."""

        resolved_scope = (
            scope
            if scope is not None
            else (
                SelfManagementScope.ADMIN
                if self.admin_mode
                else SelfManagementScope.SELF
            )
        )
        return SelfManagementAuditFields(
            event_name=event_name,
            actor_type=self.actor_type,
            acting_user_id=self.acting_user_id,
            principal_user_id=self.principal_user_id,
            admin_mode=self.admin_mode,
            scope=resolved_scope,
            resource=resource,
            action=action,
            resource_id=resource_id,
            target_user_id=target_user_id,
            tool_name=tool_name,
            delegated_by=delegated_by,
            operation_id=operation_id,
            confirmation_policy=confirmation_policy,
        )


def build_self_management_actor_context(
    *,
    user: User,
    actor_type: SelfManagementActorType,
    admin_mode: bool = False,
    principal_user_id: UUID | None = None,
) -> SelfManagementActorContext:
    """Resolve the current actor context for self-management operations."""

    actor_user_id = cast(UUID | None, user.id)
    if actor_user_id is None:
        raise ValueError("Authenticated user id is required")

    if admin_mode and not bool(user.is_superuser):
        raise SelfManagementAuthorizationError(
            "Admin mode requires superuser privileges"
        )

    resolved_principal_user_id = principal_user_id or actor_user_id
    if (
        actor_type
        in {
            SelfManagementActorType.HUMAN_API,
        }
        and resolved_principal_user_id != actor_user_id
    ):
        raise SelfManagementAuthorizationError(
            "Direct human actions cannot impersonate another principal user"
        )

    grants: list[PermissionGrant] = []
    all_actions = frozenset({SelfManagementAction.READ, SelfManagementAction.WRITE})
    for resource in SelfManagementResource:
        grants.append(
            PermissionGrant(
                scope=SelfManagementScope.SELF,
                resource=resource,
                actions=all_actions,
            )
        )
        if admin_mode:
            grants.append(
                PermissionGrant(
                    scope=SelfManagementScope.ADMIN,
                    resource=resource,
                    actions=all_actions,
                )
            )

    return SelfManagementActorContext(
        actor_type=actor_type,
        acting_user_id=actor_user_id,
        principal_user_id=resolved_principal_user_id,
        admin_mode=admin_mode,
        is_superuser=bool(user.is_superuser),
        permission_envelope=PermissionEnvelope(grants=tuple(grants)),
    )


__all__ = [
    "PermissionEnvelope",
    "PermissionGrant",
    "SelfManagementAction",
    "SelfManagementActorContext",
    "SelfManagementActorType",
    "SelfManagementAuditFields",
    "SelfManagementAuthorizationError",
    "SelfManagementResource",
    "SelfManagementScope",
    "build_self_management_actor_context",
]
