"""Shared actor-context primitives for Hub Assistant entry points."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, cast
from uuid import UUID

from app.db.models.user import User


class HubAssistantAuthorizationError(PermissionError):
    """Raised when a Hub Assistant actor is not allowed to use a scope."""


class HubAssistantActorType(str, Enum):
    """Supported actor types for Hub Assistant entry points."""

    HUMAN_API = "human_api"
    WEB_AGENT = "web_agent"


class HubAssistantScope(str, Enum):
    """Permission scopes for Hub Assistant resources."""

    SELF = "self"
    ADMIN = "admin"


class HubAssistantResource(str, Enum):
    """Managed resource categories exposed by Hub Assistant entry points."""

    AGENTS = "agents"
    JOBS = "jobs"
    SESSIONS = "sessions"
    FOLLOWUPS = "followups"


class HubAssistantAction(str, Enum):
    """Allowed action buckets for Hub Assistant resources."""

    READ = "read"
    WRITE = "write"


@dataclass(frozen=True)
class PermissionGrant:
    """One permission grant over a resource scope."""

    scope: HubAssistantScope
    resource: HubAssistantResource
    actions: frozenset[HubAssistantAction]


@dataclass(frozen=True)
class PermissionEnvelope:
    """Resolved permission envelope for one authenticated actor."""

    grants: tuple[PermissionGrant, ...]

    def allows(
        self,
        *,
        scope: HubAssistantScope,
        resource: HubAssistantResource,
        action: HubAssistantAction,
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
class HubAssistantAuditFields:
    """Canonical audit fields for Hub Assistant operations."""

    event_name: str
    actor_type: HubAssistantActorType
    acting_user_id: UUID
    principal_user_id: UUID
    admin_mode: bool
    scope: HubAssistantScope
    resource: HubAssistantResource | None = None
    action: HubAssistantAction | None = None
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
class HubAssistantActorContext:
    """Resolved actor context for Hub Assistant entry points."""

    actor_type: HubAssistantActorType
    acting_user_id: UUID
    principal_user_id: UUID
    admin_mode: bool
    is_superuser: bool
    permission_envelope: PermissionEnvelope

    def allows(
        self,
        *,
        scope: HubAssistantScope,
        resource: HubAssistantResource,
        action: HubAssistantAction,
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
        scope: HubAssistantScope | None = None,
        resource: HubAssistantResource | None = None,
        action: HubAssistantAction | None = None,
        resource_id: str | None = None,
        target_user_id: UUID | None = None,
        tool_name: str | None = None,
        delegated_by: str | None = None,
        operation_id: str | None = None,
        confirmation_policy: str | None = None,
    ) -> HubAssistantAuditFields:
        """Build canonical audit fields for one actor-mediated operation."""

        resolved_scope = (
            scope
            if scope is not None
            else (
                HubAssistantScope.ADMIN if self.admin_mode else HubAssistantScope.SELF
            )
        )
        return HubAssistantAuditFields(
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


def build_hub_assistant_actor_context(
    *,
    user: User,
    actor_type: HubAssistantActorType,
    admin_mode: bool = False,
    principal_user_id: UUID | None = None,
) -> HubAssistantActorContext:
    """Resolve the current actor context for Hub Assistant operations."""

    actor_user_id = cast(UUID | None, user.id)
    if actor_user_id is None:
        raise ValueError("Authenticated user id is required")

    if admin_mode and not bool(user.is_superuser):
        raise HubAssistantAuthorizationError("Admin mode requires superuser privileges")

    resolved_principal_user_id = principal_user_id or actor_user_id
    if (
        actor_type
        in {
            HubAssistantActorType.HUMAN_API,
        }
        and resolved_principal_user_id != actor_user_id
    ):
        raise HubAssistantAuthorizationError(
            "Direct human actions cannot impersonate another principal user"
        )

    grants: list[PermissionGrant] = []
    all_actions = frozenset({HubAssistantAction.READ, HubAssistantAction.WRITE})
    for resource in HubAssistantResource:
        grants.append(
            PermissionGrant(
                scope=HubAssistantScope.SELF,
                resource=resource,
                actions=all_actions,
            )
        )
        if admin_mode:
            grants.append(
                PermissionGrant(
                    scope=HubAssistantScope.ADMIN,
                    resource=resource,
                    actions=all_actions,
                )
            )

    return HubAssistantActorContext(
        actor_type=actor_type,
        acting_user_id=actor_user_id,
        principal_user_id=resolved_principal_user_id,
        admin_mode=admin_mode,
        is_superuser=bool(user.is_superuser),
        permission_envelope=PermissionEnvelope(grants=tuple(grants)),
    )
