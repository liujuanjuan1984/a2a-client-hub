"""Shared authorization gateway for Hub Assistant entry points."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable, Generic, TypeVar
from uuid import UUID

from app.features.hub_assistant_shared.actor_context import (
    HubAssistantAction,
    HubAssistantActorContext,
    HubAssistantAuditFields,
    HubAssistantAuthorizationError,
    HubAssistantResource,
    HubAssistantScope,
)

_ResultT = TypeVar("_ResultT")


class HubAssistantConfirmationPolicy(str, Enum):
    """Confirmation policy for one Hub Assistant operation."""

    NONE = "none"
    REQUIRED = "required"


class HubAssistantSurface(str, Enum):
    """Entry surfaces that may expose one Hub Assistant operation."""

    REST = "rest"
    WEB_AGENT = "web_agent"


@dataclass(frozen=True)
class HubAssistantOperation:
    """One authorized Hub Assistant operation."""

    operation_id: str
    scope: HubAssistantScope
    resource: HubAssistantResource
    action: HubAssistantAction
    event_name: str
    confirmation_policy: HubAssistantConfirmationPolicy = (
        HubAssistantConfirmationPolicy.NONE
    )
    surfaces: frozenset[HubAssistantSurface] = field(default_factory=frozenset)
    first_wave_exposed: bool = False
    description: str | None = None
    tool_name: str | None = None
    delegated_by: str | None = None


@dataclass(frozen=True)
class AuthorizedExecution(Generic[_ResultT]):
    """Authorized execution result and canonical audit fields."""

    result: _ResultT
    audit_fields: HubAssistantAuditFields


class HubAssistantToolGateway:
    """Authorization gateway shared by API and Hub Assistant layers."""

    def __init__(
        self,
        actor: HubAssistantActorContext,
        *,
        surface: HubAssistantSurface | None = None,
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
        operation: HubAssistantOperation,
        resource_id: str | None = None,
        target_user_id: UUID | None = None,
    ) -> HubAssistantAuditFields:
        """Authorize one operation and return canonical audit fields."""

        if not self.actor.allows(
            scope=operation.scope,
            resource=operation.resource,
            action=operation.action,
        ):
            raise HubAssistantAuthorizationError(
                "Actor is not allowed to perform "
                f"{operation.scope.value}:{operation.resource.value}:{operation.action.value}"
            )
        if (
            self.surface is not None
            and operation.surfaces
            and self.surface not in operation.surfaces
        ):
            raise HubAssistantAuthorizationError(
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
        operation: HubAssistantOperation,
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
