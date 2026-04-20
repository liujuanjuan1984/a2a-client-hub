"""Shared authorization gateway for hub feature entry points."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable, Generic, TypeVar
from uuid import UUID

from app.features.hub_access.actor_context import (
    HubAction,
    HubActorContext,
    HubAuditFields,
    HubAuthorizationError,
    HubResource,
    HubScope,
)

_ResultT = TypeVar("_ResultT")


class HubConfirmationPolicy(str, Enum):
    """Confirmation policy for one hub operation."""

    NONE = "none"
    REQUIRED = "required"


class HubSurface(str, Enum):
    """Entry surfaces that may expose one hub operation."""

    REST = "rest"
    WEB_AGENT = "web_agent"


@dataclass(frozen=True)
class HubOperation:
    """One authorized hub operation."""

    operation_id: str
    scope: HubScope
    resource: HubResource
    action: HubAction
    event_name: str
    confirmation_policy: HubConfirmationPolicy = HubConfirmationPolicy.NONE
    surfaces: frozenset[HubSurface] = field(default_factory=frozenset)
    first_wave_exposed: bool = False
    description: str | None = None
    tool_name: str | None = None
    delegated_by: str | None = None


@dataclass(frozen=True)
class AuthorizedExecution(Generic[_ResultT]):
    """Authorized execution result and canonical audit fields."""

    result: _ResultT
    audit_fields: HubAuditFields


class HubOperationGateway:
    """Authorization gateway shared by API and assistant layers."""

    def __init__(
        self,
        actor: HubActorContext,
        *,
        surface: HubSurface | None = None,
        web_agent_conversation_id: str | None = None,
    ) -> None:
        self.actor = actor
        self.surface = surface
        normalized_conversation_id = (
            str(web_agent_conversation_id).strip()
            if web_agent_conversation_id is not None
            else ""
        )
        self.web_agent_conversation_id = normalized_conversation_id or None

    def authorize(
        self,
        *,
        operation: HubOperation,
        resource_id: str | None = None,
        target_user_id: UUID | None = None,
    ) -> HubAuditFields:
        """Authorize one operation and return canonical audit fields."""

        if not self.actor.allows(
            scope=operation.scope,
            resource=operation.resource,
            action=operation.action,
        ):
            raise HubAuthorizationError(
                "Actor is not allowed to perform "
                f"{operation.scope.value}:{operation.resource.value}:{operation.action.value}"
            )
        if (
            self.surface is not None
            and operation.surfaces
            and self.surface not in operation.surfaces
        ):
            raise HubAuthorizationError(
                f"Operation `{operation.operation_id}` is not exposed on "
                f"`{self.surface.value}`."
            )

        return self.actor.build_audit_fields(
            event_name=operation.event_name,
            scope=operation.scope,
            resource=operation.resource,
            action=operation.action,
            resource_id=resource_id,
            target_user_id=target_user_id,
            tool_name=operation.tool_name,
            delegated_by=operation.delegated_by,
            operation_id=operation.operation_id,
            confirmation_policy=operation.confirmation_policy.value,
        )

    async def execute(
        self,
        *,
        operation: HubOperation,
        handler: Callable[[], Awaitable[_ResultT]],
        resource_id: str | None = None,
        target_user_id: UUID | None = None,
    ) -> AuthorizedExecution[_ResultT]:
        """Authorize and execute one handler through the shared gateway."""

        audit_fields = self.authorize(
            operation=operation,
            resource_id=resource_id,
            target_user_id=target_user_id,
        )
        result = await handler()
        return AuthorizedExecution(result=result, audit_fields=audit_fields)
