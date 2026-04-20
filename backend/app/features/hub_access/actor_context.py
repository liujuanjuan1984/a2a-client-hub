"""Shared actor-context primitives for hub feature entry points."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, cast
from uuid import UUID

from app.db.models.user import User


class HubAuthorizationError(PermissionError):
    """Raised when a hub actor is not allowed to use a scope."""


class HubActorType(str, Enum):
    """Supported actor types for hub feature entry points."""

    HUMAN_API = "human_api"
    WEB_AGENT = "web_agent"


class HubScope(str, Enum):
    """Permission scopes for Hub Assistant resources."""

    SELF = "self"
    ADMIN = "admin"


class HubResource(str, Enum):
    """Managed resource categories exposed by hub feature entry points."""

    AGENTS = "agents"
    JOBS = "jobs"
    SESSIONS = "sessions"
    FOLLOWUPS = "followups"


class HubAction(str, Enum):
    """Allowed action buckets for Hub Assistant resources."""

    READ = "read"
    WRITE = "write"


@dataclass(frozen=True)
class PermissionGrant:
    """One permission grant over a resource scope."""

    scope: HubScope
    resource: HubResource
    actions: frozenset[HubAction]


@dataclass(frozen=True)
class PermissionEnvelope:
    """Resolved permission envelope for one authenticated actor."""

    grants: tuple[PermissionGrant, ...]

    def allows(
        self,
        *,
        scope: HubScope,
        resource: HubResource,
        action: HubAction,
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
class HubAuditFields:
    """Canonical audit fields for hub operations."""

    event_name: str
    actor_type: HubActorType
    acting_user_id: UUID
    principal_user_id: UUID
    admin_mode: bool
    scope: HubScope
    resource: HubResource | None = None
    action: HubAction | None = None
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
class HubActorContext:
    """Resolved actor context for hub feature entry points."""

    actor_type: HubActorType
    acting_user_id: UUID
    principal_user_id: UUID
    admin_mode: bool
    is_superuser: bool
    permission_envelope: PermissionEnvelope

    def allows(
        self,
        *,
        scope: HubScope,
        resource: HubResource,
        action: HubAction,
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
        scope: HubScope | None = None,
        resource: HubResource | None = None,
        action: HubAction | None = None,
        resource_id: str | None = None,
        target_user_id: UUID | None = None,
        tool_name: str | None = None,
        delegated_by: str | None = None,
        operation_id: str | None = None,
        confirmation_policy: str | None = None,
    ) -> HubAuditFields:
        """Build canonical audit fields for one actor-mediated operation."""

        resolved_scope = (
            scope
            if scope is not None
            else (HubScope.ADMIN if self.admin_mode else HubScope.SELF)
        )
        return HubAuditFields(
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


def build_hub_actor_context(
    *,
    user: User,
    actor_type: HubActorType,
    admin_mode: bool = False,
    principal_user_id: UUID | None = None,
) -> HubActorContext:
    """Resolve the current actor context for hub operations."""

    actor_user_id = cast(UUID | None, user.id)
    if actor_user_id is None:
        raise ValueError("Authenticated user id is required")

    if admin_mode and not bool(user.is_superuser):
        raise HubAuthorizationError("Admin mode requires superuser privileges")

    resolved_principal_user_id = principal_user_id or actor_user_id
    if (
        actor_type
        in {
            HubActorType.HUMAN_API,
        }
        and resolved_principal_user_id != actor_user_id
    ):
        raise HubAuthorizationError(
            "Direct human actions cannot impersonate another principal user"
        )

    grants: list[PermissionGrant] = []
    all_actions = frozenset({HubAction.READ, HubAction.WRITE})
    for resource in HubResource:
        grants.append(
            PermissionGrant(
                scope=HubScope.SELF,
                resource=resource,
                actions=all_actions,
            )
        )
        if admin_mode:
            grants.append(
                PermissionGrant(
                    scope=HubScope.ADMIN,
                    resource=resource,
                    actions=all_actions,
                )
            )

    return HubActorContext(
        actor_type=actor_type,
        acting_user_id=actor_user_id,
        principal_user_id=resolved_principal_user_id,
        admin_mode=admin_mode,
        is_superuser=bool(user.is_superuser),
        permission_envelope=PermissionEnvelope(grants=tuple(grants)),
    )
