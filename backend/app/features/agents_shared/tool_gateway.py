"""Shared authorization gateway for self-management entry points."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Generic, TypeVar
from uuid import UUID

from app.features.agents_shared.actor_context import (
    SelfManagementAction,
    SelfManagementActorContext,
    SelfManagementAuditFields,
    SelfManagementAuthorizationError,
    SelfManagementResource,
    SelfManagementScope,
)

_ResultT = TypeVar("_ResultT")


@dataclass(frozen=True)
class SelfManagementOperation:
    """One authorized self-management operation."""

    scope: SelfManagementScope
    resource: SelfManagementResource
    action: SelfManagementAction
    event_name: str
    command_name: str | None = None
    tool_name: str | None = None
    delegated_by: str | None = None


@dataclass(frozen=True)
class AuthorizedExecution(Generic[_ResultT]):
    """Authorized execution result and canonical audit fields."""

    result: _ResultT
    audit_fields: SelfManagementAuditFields


class SelfManagementToolGateway:
    """Authorization gateway shared by API, built-in agent, and CLI layers."""

    def __init__(self, actor: SelfManagementActorContext) -> None:
        self.actor = actor

    def authorize(
        self,
        *,
        operation: SelfManagementOperation,
        resource_id: str | None = None,
        target_user_id: UUID | None = None,
    ) -> SelfManagementAuditFields:
        """Authorize one operation and return canonical audit fields."""

        if not self.actor.allows(
            scope=operation.scope,
            resource=operation.resource,
            action=operation.action,
        ):
            raise SelfManagementAuthorizationError(
                "Actor is not allowed to perform "
                f"{operation.scope.value}:{operation.resource.value}:{operation.action.value}"
            )

        return self.actor.build_audit_fields(
            event_name=operation.event_name,
            scope=operation.scope,
            resource=operation.resource,
            action=operation.action,
            resource_id=resource_id,
            target_user_id=target_user_id,
            command_name=operation.command_name,
            tool_name=operation.tool_name,
            delegated_by=operation.delegated_by,
        )

    async def execute(
        self,
        *,
        operation: SelfManagementOperation,
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


__all__ = [
    "AuthorizedExecution",
    "SelfManagementOperation",
    "SelfManagementToolGateway",
]
