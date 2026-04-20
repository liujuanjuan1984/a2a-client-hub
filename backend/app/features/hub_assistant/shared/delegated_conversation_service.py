"""Delegated conversation handoff actions for the Hub Assistant."""

from __future__ import annotations

from typing import Any, Literal, cast
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.conversation_thread import ConversationThread
from app.db.models.user import User
from app.db.transaction import commit_safely, load_for_external_call
from app.features.hub_agents.runtime import (
    HubA2ARuntimeNotFoundError,
    HubA2ARuntimeValidationError,
    HubA2AUserCredentialRequiredError,
    hub_a2a_runtime_builder,
)
from app.features.hub_assistant.shared.capability_catalog import (
    HUB_ASSISTANT_AGENTS_START_SESSIONS,
    HUB_ASSISTANT_SESSIONS_SEND_MESSAGE,
)
from app.features.hub_assistant.shared.task_service import (
    DelegatedInvokeTaskRequest,
    hub_assistant_task_service,
)
from app.features.hub_assistant.shared.tool_gateway import HubAssistantToolGateway
from app.features.invoke.route_runner import run_background_invoke
from app.features.personal_agents.runtime import (
    A2ARuntimeNotFoundError,
    A2ARuntimeValidationError,
    a2a_runtime_builder,
)
from app.features.sessions import message_store
from app.features.sessions.common import parse_conversation_id
from app.features.sessions.support import SessionHubSupport
from app.integrations.a2a_client.service import get_a2a_service
from app.integrations.a2a_client.validators import validate_message
from app.schemas.a2a_invoke import A2AAgentInvokeRequest

logger = get_logger(__name__)

_DELEGATED_BY = "hub_assistant"
_HANDOFF_MESSAGE_KIND = "delegation_handoff"


class HubAssistantDelegatedConversationService:
    """Dispatch delegated session and agent handoffs for the Hub Assistant."""

    def __init__(self) -> None:
        self._session_support = SessionHubSupport()

    async def send_messages_to_sessions(
        self,
        *,
        db: AsyncSession,
        gateway: HubAssistantToolGateway,
        current_user: User,
        conversation_ids: list[UUID],
        message: str,
    ) -> dict[str, Any]:
        normalized_message = message.strip()
        if not normalized_message:
            raise ValueError("message is required")

        items: list[dict[str, Any]] = []
        accepted_conversation_ids: list[str] = []
        dispatched = False
        operation_id = str(uuid4())
        for conversation_id in self._dedupe_uuids(conversation_ids):
            gateway.authorize(
                operation=HUB_ASSISTANT_SESSIONS_SEND_MESSAGE,
                resource_id=str(conversation_id),
            )
            item = await self._send_one_session_message(
                db=db,
                current_user=current_user,
                hub_assistant_conversation_id=gateway.web_agent_conversation_id,
                operation_id=operation_id,
                conversation_id=conversation_id,
                message=normalized_message,
            )
            items.append(item)
            if item.get("status") == "accepted":
                accepted_conversation_ids.append(str(conversation_id))
                dispatched = True
        if accepted_conversation_ids:
            await self._auto_track_handoff_conversations(
                db=db,
                current_user=current_user,
                hub_assistant_conversation_id=gateway.web_agent_conversation_id,
                conversation_ids=accepted_conversation_ids,
            )
        if dispatched:
            from app.features.hub_assistant.shared.task_job import (
                request_hub_assistant_task_run,
            )

            request_hub_assistant_task_run()
        return self._serialize_batch_payload(items=items)

    async def start_sessions_for_agents(
        self,
        *,
        db: AsyncSession,
        gateway: HubAssistantToolGateway,
        current_user: User,
        agent_ids: list[UUID],
        message: str,
    ) -> dict[str, Any]:
        normalized_message = message.strip()
        if not normalized_message:
            raise ValueError("message is required")

        items: list[dict[str, Any]] = []
        accepted_conversation_ids: list[str] = []
        dispatched = False
        operation_id = str(uuid4())
        for agent_id in self._dedupe_uuids(agent_ids):
            gateway.authorize(
                operation=HUB_ASSISTANT_AGENTS_START_SESSIONS,
                resource_id=str(agent_id),
            )
            item = await self._start_one_agent_session(
                db=db,
                current_user=current_user,
                hub_assistant_conversation_id=gateway.web_agent_conversation_id,
                operation_id=operation_id,
                agent_id=agent_id,
                message=normalized_message,
            )
            items.append(item)
            if item.get("status") == "accepted":
                conversation_id = item.get("conversation_id")
                if isinstance(conversation_id, str) and conversation_id.strip():
                    accepted_conversation_ids.append(conversation_id.strip())
                    dispatched = True
        if accepted_conversation_ids:
            await self._auto_track_handoff_conversations(
                db=db,
                current_user=current_user,
                hub_assistant_conversation_id=gateway.web_agent_conversation_id,
                conversation_ids=accepted_conversation_ids,
            )
        if dispatched:
            from app.features.hub_assistant.shared.task_job import (
                request_hub_assistant_task_run,
            )

            request_hub_assistant_task_run()
        return self._serialize_batch_payload(items=items)

    async def _send_one_session_message(
        self,
        *,
        db: AsyncSession,
        current_user: User,
        hub_assistant_conversation_id: str | None,
        operation_id: str,
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

        await self._record_hub_assistant_handoff_message(
            db=db,
            current_user=current_user,
            hub_assistant_conversation_id=hub_assistant_conversation_id,
            operation_id=operation_id,
            target_type="session",
            target_conversation_id=str(conversation_id),
            target_agent_id=cast(str | None, runtime_info["agent_id"]),
            target_agent_source=cast(str | None, runtime_info["agent_source"]),
            target_agent_name=cast(str | None, runtime_info["agent_name"]),
            target_session_title=cast(str, thread.title),
            delegated_message=message,
        )
        await hub_assistant_task_service.enqueue_delegated_invoke(
            db=db,
            request=DelegatedInvokeTaskRequest(
                current_user_id=user_id,
                hub_assistant_conversation_id=self._require_hub_assistant_conversation_id(
                    hub_assistant_conversation_id
                ),
                agent_id=cast(UUID, runtime_info["agent_uuid"]),
                agent_source=cast(
                    Literal["personal", "shared"], runtime_info["agent_source"]
                ),
                message=message,
                conversation_id=str(conversation_id),
                target_kind="session",
                target_id=str(conversation_id),
            ),
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
        hub_assistant_conversation_id: str | None,
        operation_id: str,
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
        await self._session_support.ensure_local_conversation_thread(
            db,
            user_id=cast(UUID, current_user.id),
            conversation_id=UUID(local_conversation_id),
            agent_id=agent_id,
            agent_source="personal",
            title=message,
            source="manual",
        )

        await self._record_hub_assistant_handoff_message(
            db=db,
            current_user=current_user,
            hub_assistant_conversation_id=hub_assistant_conversation_id,
            operation_id=operation_id,
            target_type="agent",
            target_conversation_id=local_conversation_id,
            target_agent_id=str(agent_id),
            target_agent_source="personal",
            target_agent_name=cast(str | None, runtime_info["agent_name"]),
            target_session_title=None,
            delegated_message=message,
        )
        await hub_assistant_task_service.enqueue_delegated_invoke(
            db=db,
            request=DelegatedInvokeTaskRequest(
                current_user_id=cast(UUID, current_user.id),
                hub_assistant_conversation_id=self._require_hub_assistant_conversation_id(
                    hub_assistant_conversation_id
                ),
                agent_id=agent_id,
                agent_source="personal",
                message=message,
                conversation_id=local_conversation_id,
                target_kind="agent",
                target_id=str(agent_id),
            ),
        )
        return {
            "target_type": "agent",
            "agent_id": str(agent_id),
            "agent_source": "personal",
            "agent_name": runtime_info["agent_name"],
            "conversation_id": local_conversation_id,
            "status": "accepted",
        }

    async def _auto_track_handoff_conversations(
        self,
        *,
        db: AsyncSession,
        current_user: User,
        hub_assistant_conversation_id: str | None,
        conversation_ids: list[str],
    ) -> None:
        if not hub_assistant_conversation_id:
            return
        await hub_assistant_task_service.add_tracked_sessions(
            db=db,
            current_user=current_user,
            hub_assistant_conversation_id=hub_assistant_conversation_id,
            conversation_ids=conversation_ids,
        )

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

    async def _resolve_runtime_for_dispatch(
        self,
        *,
        db: AsyncSession,
        current_user: User,
        agent_id: UUID,
        agent_source: Literal["personal", "shared"],
    ) -> Any:
        if agent_source == "shared":
            return await load_for_external_call(
                db,
                lambda session: hub_a2a_runtime_builder.build(
                    session,
                    user_id=cast(UUID, current_user.id),
                    agent_id=agent_id,
                ),
            )
        return await load_for_external_call(
            db,
            lambda session: a2a_runtime_builder.build(
                session,
                user_id=cast(UUID, current_user.id),
                agent_id=agent_id,
            ),
        )

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

    async def run_delegated_dispatch_request(
        self,
        *,
        db: AsyncSession,
        current_user: User,
        request: DelegatedInvokeTaskRequest,
    ) -> None:
        extra = {
            "user_id": str(request.current_user_id),
            "agent_id": str(request.agent_id),
            "agent_source": request.agent_source,
            "conversation_id": request.conversation_id,
            "delegated_by": _DELEGATED_BY,
            "delegated_target_kind": request.target_kind,
            "delegated_target_id": request.target_id,
        }
        try:
            runtime = await self._resolve_runtime_for_dispatch(
                db=db,
                current_user=current_user,
                agent_id=request.agent_id,
                agent_source=request.agent_source,
            )
        except (
            A2ARuntimeNotFoundError,
            A2ARuntimeValidationError,
            HubA2ARuntimeNotFoundError,
            HubA2ARuntimeValidationError,
            HubA2AUserCredentialRequiredError,
        ) as exc:
            logger.exception(
                "Delegated hub-assistant handoff runtime resolution failed",
                extra=extra,
            )
            raise RuntimeError(str(exc)) from exc

        result = await self._run_delegated_invoke(
            runtime=runtime,
            user_id=request.current_user_id,
            agent_id=request.agent_id,
            agent_source=request.agent_source,
            message=request.message,
            conversation_id=request.conversation_id,
            target_kind=request.target_kind,
            target_id=request.target_id,
        )
        if not bool(result.get("success")):
            error_code = cast(str | None, result.get("error_code"))
            logger.warning(
                "Delegated hub-assistant handoff finished with a failed target outcome",
                extra={
                    **extra,
                    "error_code": error_code,
                },
            )
            raise RuntimeError(
                error_code
                or cast(str | None, result.get("error"))
                or "delegated_invoke_failed"
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

    async def _record_hub_assistant_handoff_message(
        self,
        *,
        db: AsyncSession,
        current_user: User,
        hub_assistant_conversation_id: str | None,
        operation_id: str,
        target_type: Literal["session", "agent"],
        target_conversation_id: str,
        target_agent_id: str | None,
        target_agent_source: str | None,
        target_agent_name: str | None,
        target_session_title: str | None,
        delegated_message: str,
    ) -> None:
        if not hub_assistant_conversation_id:
            return
        local_session = await self._session_support.get_local_session_by_id(
            db,
            user_id=cast(UUID, current_user.id),
            local_session_id=parse_conversation_id(hub_assistant_conversation_id),
        )
        if local_session is None:
            raise ValueError("hub_assistant_session_not_found")
        agent_message = await message_store.create_agent_message(
            db,
            user_id=cast(UUID, current_user.id),
            sender="agent",
            conversation_id=cast(UUID, local_session.id),
            status="done",
            finish_reason="completed",
            metadata={
                "message_kind": _HANDOFF_MESSAGE_KIND,
                "operation_id": operation_id,
                "delegation": {
                    "status": "accepted",
                    "target_type": target_type,
                    "target_conversation_id": target_conversation_id,
                    "target_agent_id": target_agent_id,
                    "target_agent_source": target_agent_source,
                    "target_agent_name": target_agent_name,
                    "target_session_title": target_session_title,
                    "delegated_message": delegated_message,
                },
            },
        )
        await self._session_support.upsert_single_text_block(
            db,
            user_id=cast(UUID, current_user.id),
            message_id=cast(UUID, agent_message.id),
            content=self._build_handoff_record_content(
                target_type=target_type,
                target_conversation_id=target_conversation_id,
                target_agent_id=target_agent_id,
                target_agent_name=target_agent_name,
                target_session_title=target_session_title,
                delegated_message=delegated_message,
            ),
            source=_HANDOFF_MESSAGE_KIND,
        )
        await commit_safely(db)

    @staticmethod
    def _build_handoff_record_content(
        *,
        target_type: Literal["session", "agent"],
        target_conversation_id: str,
        target_agent_id: str | None,
        target_agent_name: str | None,
        target_session_title: str | None,
        delegated_message: str,
    ) -> str:
        agent_label = target_agent_name or target_agent_id or "target agent"
        if target_type == "session":
            title = (target_session_title or "").strip()
            title_suffix = f' "{title}"' if title else ""
            return (
                f"Delegated to {agent_label} in target session "
                f"{target_conversation_id}{title_suffix}.\n"
                f"Sent message: {delegated_message}"
            )
        return (
            f"Started delegated session {target_conversation_id} with "
            f"{agent_label}.\n"
            f"Sent message: {delegated_message}"
        )

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

    @staticmethod
    def _require_hub_assistant_conversation_id(value: str | None) -> str:
        if value is None or not value.strip():
            raise ValueError("hub_assistant_conversation_context_required")
        return value.strip()


def normalize_name(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


hub_assistant_delegated_conversation_service = (
    HubAssistantDelegatedConversationService()
)
