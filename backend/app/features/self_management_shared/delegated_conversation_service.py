"""Delegated conversation handoff actions for the self-management built-in agent."""

from __future__ import annotations

import asyncio
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.conversation_thread import ConversationThread
from app.db.models.user import User
from app.db.transaction import load_for_external_call
from app.features.hub_agents.runtime import (
    HubA2ARuntimeNotFoundError,
    HubA2ARuntimeValidationError,
    HubA2AUserCredentialRequiredError,
    hub_a2a_runtime_builder,
)
from app.features.invoke.route_runner import run_background_invoke
from app.features.personal_agents.runtime import (
    A2ARuntimeNotFoundError,
    A2ARuntimeValidationError,
    a2a_runtime_builder,
)
from app.features.self_management_shared.capability_catalog import (
    SELF_AGENTS_START_SESSIONS,
    SELF_SESSIONS_SEND_MESSAGE,
)
from app.features.self_management_shared.tool_gateway import SelfManagementToolGateway
from app.features.sessions.support import SessionHubSupport
from app.integrations.a2a_client.service import get_a2a_service
from app.integrations.a2a_client.validators import validate_message
from app.schemas.a2a_invoke import A2AAgentInvokeRequest

logger = get_logger(__name__)

_DELEGATED_BY = "self_management_built_in_agent"


class SelfManagementDelegatedConversationService:
    """Dispatch delegated session and agent handoffs for the built-in agent."""

    def __init__(self) -> None:
        self._session_support = SessionHubSupport()
        self._dispatch_tasks: set[asyncio.Task[None]] = set()

    async def send_messages_to_sessions(
        self,
        *,
        db: AsyncSession,
        gateway: SelfManagementToolGateway,
        current_user: User,
        conversation_ids: list[UUID],
        message: str,
    ) -> dict[str, Any]:
        normalized_message = message.strip()
        if not normalized_message:
            raise ValueError("message is required")

        items: list[dict[str, Any]] = []
        for conversation_id in self._dedupe_uuids(conversation_ids):
            gateway.authorize(
                operation=SELF_SESSIONS_SEND_MESSAGE,
                resource_id=str(conversation_id),
            )
            items.append(
                await self._send_one_session_message(
                    db=db,
                    current_user=current_user,
                    conversation_id=conversation_id,
                    message=normalized_message,
                )
            )
        return self._serialize_batch_payload(items=items)

    async def start_sessions_for_agents(
        self,
        *,
        db: AsyncSession,
        gateway: SelfManagementToolGateway,
        current_user: User,
        agent_ids: list[UUID],
        message: str,
    ) -> dict[str, Any]:
        normalized_message = message.strip()
        if not normalized_message:
            raise ValueError("message is required")

        items: list[dict[str, Any]] = []
        for agent_id in self._dedupe_uuids(agent_ids):
            gateway.authorize(
                operation=SELF_AGENTS_START_SESSIONS,
                resource_id=str(agent_id),
            )
            items.append(
                await self._start_one_agent_session(
                    db=db,
                    current_user=current_user,
                    agent_id=agent_id,
                    message=normalized_message,
                )
            )
        return self._serialize_batch_payload(items=items)

    async def drain_pending_tasks(self) -> None:
        tasks = list(self._dispatch_tasks)
        self._dispatch_tasks.clear()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _send_one_session_message(
        self,
        *,
        db: AsyncSession,
        current_user: User,
        conversation_id: UUID,
        message: str,
    ) -> dict[str, Any]:
        user_id = cast(UUID, current_user.id)
        thread = await self._session_support.get_local_session_by_id(
            db,
            user_id=user_id,
            local_session_id=conversation_id,
        )
        if thread is None:
            return {
                "target_type": "session",
                "conversation_id": str(conversation_id),
                "status": "failed",
                "error": "session_not_found",
                "error_code": "session_not_found",
            }

        runtime_info = await self._resolve_runtime_for_thread(
            db=db,
            current_user=current_user,
            thread=thread,
        )
        if runtime_info["error_code"] is not None:
            return {
                "target_type": "session",
                "conversation_id": str(conversation_id),
                "agent_id": runtime_info["agent_id"],
                "agent_source": runtime_info["agent_source"],
                "status": "failed",
                "title": cast(str, thread.title),
                "error": runtime_info["error"],
                "error_code": runtime_info["error_code"],
            }

        self._schedule_delegated_invoke(
            runtime=runtime_info["runtime"],
            user_id=user_id,
            agent_id=cast(UUID, runtime_info["agent_uuid"]),
            agent_source=cast(
                Literal["personal", "shared"], runtime_info["agent_source"]
            ),
            message=message,
            conversation_id=str(conversation_id),
            target_kind="session",
            target_id=str(conversation_id),
        )
        return {
            "target_type": "session",
            "conversation_id": str(conversation_id),
            "agent_id": runtime_info["agent_id"],
            "agent_source": runtime_info["agent_source"],
            "agent_name": runtime_info["agent_name"],
            "title": cast(str, thread.title),
            "status": "accepted",
        }

    async def _start_one_agent_session(
        self,
        *,
        db: AsyncSession,
        current_user: User,
        agent_id: UUID,
        message: str,
    ) -> dict[str, Any]:
        local_conversation_id = str(uuid4())
        runtime_info = await self._resolve_runtime_for_agent(
            db=db,
            current_user=current_user,
            agent_id=agent_id,
        )
        if runtime_info["error_code"] is not None:
            return {
                "target_type": "agent",
                "agent_id": str(agent_id),
                "agent_source": "personal",
                "status": "failed",
                "error": runtime_info["error"],
                "error_code": runtime_info["error_code"],
            }

        self._schedule_delegated_invoke(
            runtime=runtime_info["runtime"],
            user_id=cast(UUID, current_user.id),
            agent_id=agent_id,
            agent_source="personal",
            message=message,
            conversation_id=local_conversation_id,
            target_kind="agent",
            target_id=str(agent_id),
        )
        return {
            "target_type": "agent",
            "agent_id": str(agent_id),
            "agent_source": "personal",
            "agent_name": runtime_info["agent_name"],
            "conversation_id": local_conversation_id,
            "status": "accepted",
        }

    async def _resolve_runtime_for_thread(
        self,
        *,
        db: AsyncSession,
        current_user: User,
        thread: ConversationThread,
    ) -> dict[str, Any]:
        agent_uuid = cast(UUID | None, thread.agent_id)
        agent_source = cast(str | None, thread.agent_source)
        if agent_uuid is None or agent_source not in {"personal", "shared"}:
            return {
                "runtime": None,
                "agent_uuid": None,
                "agent_id": None,
                "agent_source": agent_source,
                "agent_name": None,
                "error": "runtime_invalid",
                "error_code": "runtime_invalid",
            }
        try:
            runtime: Any
            if agent_source == "shared":
                runtime = cast(
                    Any,
                    await load_for_external_call(
                        db,
                        lambda session: hub_a2a_runtime_builder.build(
                            session,
                            user_id=cast(UUID, current_user.id),
                            agent_id=agent_uuid,
                        ),
                    ),
                )
            else:
                runtime = cast(
                    Any,
                    await load_for_external_call(
                        db,
                        lambda session: a2a_runtime_builder.build(
                            session,
                            user_id=cast(UUID, current_user.id),
                            agent_id=agent_uuid,
                        ),
                    ),
                )
        except (A2ARuntimeNotFoundError, HubA2ARuntimeNotFoundError) as exc:
            return {
                "runtime": None,
                "agent_uuid": agent_uuid,
                "agent_id": str(agent_uuid),
                "agent_source": agent_source,
                "agent_name": None,
                "error": str(exc),
                "error_code": "agent_not_found",
            }
        except HubA2AUserCredentialRequiredError as exc:
            return {
                "runtime": None,
                "agent_uuid": agent_uuid,
                "agent_id": str(agent_uuid),
                "agent_source": agent_source,
                "agent_name": None,
                "error": getattr(exc, "error_code", "credential_required"),
                "error_code": getattr(exc, "error_code", "credential_required"),
            }
        except (A2ARuntimeValidationError, HubA2ARuntimeValidationError):
            return {
                "runtime": None,
                "agent_uuid": agent_uuid,
                "agent_id": str(agent_uuid),
                "agent_source": agent_source,
                "agent_name": None,
                "error": "runtime_invalid",
                "error_code": "runtime_invalid",
            }
        return {
            "runtime": runtime,
            "agent_uuid": agent_uuid,
            "agent_id": str(agent_uuid),
            "agent_source": agent_source,
            "agent_name": normalize_name(getattr(runtime.resolved, "name", None)),
            "error": None,
            "error_code": None,
        }

    async def _resolve_runtime_for_agent(
        self,
        *,
        db: AsyncSession,
        current_user: User,
        agent_id: UUID,
    ) -> dict[str, Any]:
        try:
            runtime = await load_for_external_call(
                db,
                lambda session: a2a_runtime_builder.build(
                    session,
                    user_id=cast(UUID, current_user.id),
                    agent_id=agent_id,
                ),
            )
        except A2ARuntimeNotFoundError as exc:
            return {
                "runtime": None,
                "agent_name": None,
                "error": str(exc),
                "error_code": "agent_not_found",
            }
        except A2ARuntimeValidationError:
            return {
                "runtime": None,
                "agent_name": None,
                "error": "runtime_invalid",
                "error_code": "runtime_invalid",
            }
        return {
            "runtime": runtime,
            "agent_name": normalize_name(getattr(runtime.resolved, "name", None)),
            "error": None,
            "error_code": None,
        }

    async def _run_delegated_invoke(
        self,
        *,
        runtime: Any,
        user_id: UUID,
        agent_id: UUID,
        agent_source: Literal["personal", "shared"],
        message: str,
        conversation_id: str | None,
        target_kind: Literal["session", "agent"],
        target_id: str,
    ) -> dict[str, Any]:
        payload = A2AAgentInvokeRequest(
            query=message,
            conversationId=conversation_id,
        )
        return await run_background_invoke(
            gateway=cast(Any, get_a2a_service()).gateway,
            runtime=runtime,
            user_id=user_id,
            agent_id=agent_id,
            agent_source=agent_source,
            payload=payload,
            validate_message=validate_message,
            logger=logger,
            log_extra={
                "user_id": str(user_id),
                "agent_id": str(agent_id),
                "agent_source": agent_source,
                "conversation_id": conversation_id,
                "delegated_by": _DELEGATED_BY,
                "delegated_target_kind": target_kind,
                "delegated_target_id": target_id,
            },
            user_sender="automation",
            extra_persisted_metadata={
                "delegated_by": _DELEGATED_BY,
                "delegated_target_kind": target_kind,
                "delegated_target_id": target_id,
                "message_kind": (
                    "delegated_session_message"
                    if target_kind == "session"
                    else "delegated_agent_message"
                ),
            },
        )

    def _schedule_delegated_invoke(
        self,
        *,
        runtime: Any,
        user_id: UUID,
        agent_id: UUID,
        agent_source: Literal["personal", "shared"],
        message: str,
        conversation_id: str | None,
        target_kind: Literal["session", "agent"],
        target_id: str,
    ) -> None:
        task = asyncio.create_task(
            self._run_delegated_invoke_task(
                runtime=runtime,
                user_id=user_id,
                agent_id=agent_id,
                agent_source=agent_source,
                message=message,
                conversation_id=conversation_id,
                target_kind=target_kind,
                target_id=target_id,
            ),
            name=f"self-management-delegated-handoff:{target_kind}:{target_id}",
        )
        self._dispatch_tasks.add(task)
        task.add_done_callback(self._dispatch_tasks.discard)

    async def _run_delegated_invoke_task(
        self,
        *,
        runtime: Any,
        user_id: UUID,
        agent_id: UUID,
        agent_source: Literal["personal", "shared"],
        message: str,
        conversation_id: str | None,
        target_kind: Literal["session", "agent"],
        target_id: str,
    ) -> None:
        extra = {
            "user_id": str(user_id),
            "agent_id": str(agent_id),
            "agent_source": agent_source,
            "conversation_id": conversation_id,
            "delegated_by": _DELEGATED_BY,
            "delegated_target_kind": target_kind,
            "delegated_target_id": target_id,
        }
        try:
            result = await self._run_delegated_invoke(
                runtime=runtime,
                user_id=user_id,
                agent_id=agent_id,
                agent_source=agent_source,
                message=message,
                conversation_id=conversation_id,
                target_kind=target_kind,
                target_id=target_id,
            )
        except Exception:
            logger.exception(
                "Delegated self-management handoff execution failed",
                extra=extra,
            )
            return
        if not bool(result.get("success")):
            logger.warning(
                "Delegated self-management handoff finished with a failed target outcome",
                extra={
                    **extra,
                    "error_code": cast(str | None, result.get("error_code")),
                },
            )

    @staticmethod
    def _serialize_batch_payload(items: list[dict[str, Any]]) -> dict[str, Any]:
        accepted = sum(1 for item in items if item.get("status") == "accepted")
        failed = sum(1 for item in items if item.get("status") == "failed")
        return {
            "summary": {
                "requested": len(items),
                "accepted": accepted,
                "failed": failed,
            },
            "items": items,
        }

    @staticmethod
    def _dedupe_uuids(values: list[UUID]) -> list[UUID]:
        seen: set[UUID] = set()
        deduped: list[UUID] = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            deduped.append(value)
        return deduped


def normalize_name(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


self_management_delegated_conversation_service = (
    SelfManagementDelegatedConversationService()
)

__all__ = [
    "SelfManagementDelegatedConversationService",
    "self_management_delegated_conversation_service",
]
