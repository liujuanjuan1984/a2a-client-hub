"""Durable session and message persistence helpers for the Hub Assistant."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    HUB_ASSISTANT_INTERRUPT_TOKEN_TYPE,
    get_hub_assistant_interrupt_conversation_id,
    get_hub_assistant_interrupt_message,
    verify_jwt_token_claims,
)
from app.db.models.agent_message import AgentMessage
from app.db.models.conversation_thread import ConversationThread
from app.features.hub_assistant.models import (
    HubAssistantPermissionInterrupt,
    HubAssistantRecoveredPermissionInterrupt,
    HubAssistantRunResult,
    HubAssistantRunStatus,
)
from app.features.hub_assistant.shared.constants import (
    HUB_ASSISTANT_INTERNAL_ID,
    HUB_ASSISTANT_PUBLIC_ID,
)
from app.features.sessions import block_store, message_store
from app.features.sessions.common import (
    SessionSource,
    normalize_interrupt_lifecycle_event,
    parse_conversation_id,
    project_message_blocks,
    sender_to_role,
)
from app.features.sessions.service import session_hub_service
from app.features.sessions.support import SessionHubSupport
from app.utils.timezone_util import utc_now


class HubAssistantPersistenceService:
    """Persistence operations shared across Hub Assistant orchestration flows."""

    def __init__(self, *, session_support: SessionHubSupport) -> None:
        self._session_support = session_support

    async def recover_pending_permission_interrupts(
        self,
        *,
        db: AsyncSession,
        current_user: Any,
        conversation_id: str,
    ) -> list[HubAssistantRecoveredPermissionInterrupt]:
        resolved_conversation_id = parse_conversation_id(conversation_id)
        recoverable_conversation = cast(
            ConversationThread | None,
            await db.scalar(
                select(ConversationThread).where(
                    ConversationThread.id == resolved_conversation_id,
                    ConversationThread.user_id == cast(Any, current_user.id),
                    ConversationThread.status.in_(
                        [
                            ConversationThread.STATUS_ACTIVE,
                            ConversationThread.STATUS_ARCHIVED,
                        ]
                    ),
                    ConversationThread.source.in_(
                        [
                            ConversationThread.SOURCE_MANUAL,
                            ConversationThread.SOURCE_SCHEDULED,
                        ]
                    ),
                )
            ),
        )
        if recoverable_conversation is None:
            return []

        rows = list(
            (
                await db.scalars(
                    select(AgentMessage)
                    .where(
                        AgentMessage.user_id == cast(Any, current_user.id),
                        AgentMessage.conversation_id == resolved_conversation_id,
                        AgentMessage.sender == "system",
                    )
                    .order_by(AgentMessage.created_at.asc(), AgentMessage.id.asc())
                )
            ).all()
        )

        asked_interrupts: dict[str, dict[str, Any]] = {}
        ordered_request_ids: list[str] = []
        expired_request_ids: list[str] = []
        for message in rows:
            metadata = cast(dict[str, Any], message.message_metadata or {})
            interrupt = normalize_interrupt_lifecycle_event(
                cast(dict[str, Any] | None, metadata.get("interrupt"))
            )
            if interrupt is None:
                continue
            request_id = cast(str | None, interrupt.get("request_id"))
            if not request_id:
                continue
            phase = cast(str | None, interrupt.get("phase"))
            if phase == "asked":
                asked_interrupts[request_id] = interrupt
                if request_id not in ordered_request_ids:
                    ordered_request_ids.append(request_id)
                continue
            if phase == "resolved":
                asked_interrupts.pop(request_id, None)

        recovered: list[HubAssistantRecoveredPermissionInterrupt] = []
        for request_id in ordered_request_ids:
            interrupt = asked_interrupts.get(request_id)
            if interrupt is None:
                continue
            if interrupt.get("type") != "permission":
                continue
            claims = verify_jwt_token_claims(
                request_id,
                expected_type=HUB_ASSISTANT_INTERRUPT_TOKEN_TYPE,
            )
            if claims is None:
                expired_request_ids.append(request_id)
                continue
            if claims.subject != str(current_user.id):
                expired_request_ids.append(request_id)
                continue
            if get_hub_assistant_interrupt_conversation_id(claims) != str(
                resolved_conversation_id
            ):
                expired_request_ids.append(request_id)
                continue
            if get_hub_assistant_interrupt_message(claims) is None:
                expired_request_ids.append(request_id)
                continue
            recovered.append(
                HubAssistantRecoveredPermissionInterrupt(
                    request_id=request_id,
                    session_id=str(resolved_conversation_id),
                    type="permission",
                    details=cast(dict[str, Any], interrupt.get("details") or {}),
                )
            )

        for request_id in expired_request_ids:
            await self.persist_interrupt_resolution(
                db=db,
                current_user=current_user,
                conversation_id=str(resolved_conversation_id),
                request_id=request_id,
                resolution="expired",
            )
        return recovered

    async def ensure_local_hub_assistant_session(
        self,
        *,
        db: AsyncSession,
        current_user: Any,
        conversation_id: str,
    ) -> tuple[Any, SessionSource]:
        session, source = await session_hub_service.ensure_local_session_for_invoke(
            db,
            user_id=cast(Any, current_user.id),
            agent_id=HUB_ASSISTANT_INTERNAL_ID,
            agent_source="hub_assistant",
            conversation_id=conversation_id,
        )
        if session is None or source is None:
            raise RuntimeError(
                "Failed to bind the Hub Assistant conversation to a durable session."
            )
        return session, source

    async def persist_run_turn(
        self,
        *,
        db: AsyncSession,
        current_user: Any,
        local_session: Any,
        local_session_id: str,
        local_source: SessionSource,
        query: str,
        user_message_id: UUID | None,
        agent_message_id: UUID | None,
        result: HubAssistantRunResult,
    ) -> None:
        await session_hub_service.record_local_invoke_messages(
            db,
            session=local_session,
            source=local_source,
            user_id=cast(Any, current_user.id),
            agent_id=HUB_ASSISTANT_INTERNAL_ID,
            agent_source="hub_assistant",
            query=query,
            response_content=result.answer or "",
            success=result.status == HubAssistantRunStatus.COMPLETED,
            context_id=None,
            extra_metadata={
                "hub_assistant": True,
                "hub_assistant_id": HUB_ASSISTANT_PUBLIC_ID,
                "runtime": result.runtime,
                "resources": list(result.resources),
                "write_tools_enabled": result.write_tools_enabled,
            },
            response_metadata={
                "tools": list(result.tool_names),
                "write_tools_enabled": result.write_tools_enabled,
                "hub_assistant": True,
            },
            user_message_id=user_message_id,
            agent_message_id=agent_message_id,
            agent_status=(
                "interrupted"
                if result.status == HubAssistantRunStatus.INTERRUPTED
                else "done"
            ),
            finish_reason=(
                "interrupt"
                if result.status == HubAssistantRunStatus.INTERRUPTED
                else "completed"
            ),
            error_code=None,
        )
        if result.interrupt is None:
            return
        await self.persist_permission_interrupt(
            db=db,
            current_user=current_user,
            local_session_id=local_session_id,
            interrupt=result.interrupt,
        )

    async def persist_permission_interrupt(
        self,
        *,
        db: AsyncSession,
        current_user: Any,
        local_session_id: str,
        interrupt: HubAssistantPermissionInterrupt,
    ) -> None:
        await session_hub_service.record_interrupt_lifecycle_event_by_local_session_id(
            db,
            local_session_id=parse_conversation_id(local_session_id),
            user_id=cast(Any, current_user.id),
            event={
                "request_id": interrupt.request_id,
                "type": "permission",
                "phase": "asked",
                "details": {
                    "permission": interrupt.permission,
                    "patterns": list(interrupt.patterns),
                    "displayMessage": interrupt.display_message,
                },
            },
        )

    async def persist_interrupt_resolution(
        self,
        *,
        db: AsyncSession,
        current_user: Any,
        conversation_id: str,
        request_id: str,
        resolution: str,
    ) -> None:
        await session_hub_service.record_interrupt_lifecycle_event_by_local_session_id(
            db,
            local_session_id=parse_conversation_id(conversation_id),
            user_id=cast(Any, current_user.id),
            event={
                "request_id": request_id,
                "type": "permission",
                "phase": "resolved",
                "resolution": resolution,
            },
        )

    async def persist_follow_up_agent_message(
        self,
        *,
        db: AsyncSession,
        current_user: Any,
        conversation_id: str,
        answer: str | None,
        agent_message_id: UUID | None,
        metadata: dict[str, Any],
        status: str,
        finish_reason: str | None,
    ) -> None:
        local_session, _ = await self.ensure_local_hub_assistant_session(
            db=db,
            current_user=current_user,
            conversation_id=conversation_id,
        )
        setattr(local_session, "last_active_at", utc_now())
        agent_message: AgentMessage | None = None
        if agent_message_id is not None:
            agent_message = await db.scalar(
                select(AgentMessage).where(
                    AgentMessage.id == agent_message_id,
                    AgentMessage.user_id == cast(Any, current_user.id),
                    AgentMessage.conversation_id == cast(Any, local_session.id),
                    AgentMessage.sender == "agent",
                )
            )
        if agent_message is None:
            create_kwargs: dict[str, Any] = {
                "user_id": cast(Any, current_user.id),
                "sender": "agent",
                "conversation_id": cast(Any, local_session.id),
                "status": status,
                "finish_reason": finish_reason,
                "metadata": metadata,
            }
            if agent_message_id is not None:
                create_kwargs["id"] = agent_message_id
            agent_message = await message_store.create_agent_message(
                db, **create_kwargs
            )
        else:
            await message_store.update_agent_message(
                db,
                message=agent_message,
                status=status,
                finish_reason=finish_reason,
                metadata=metadata,
            )
        await self._session_support.upsert_single_text_block(
            db,
            user_id=cast(Any, current_user.id),
            message_id=cast(Any, agent_message.id),
            content=answer or "",
            source="hub_assistant_reply",
        )

    async def list_persisted_runtime_messages(
        self,
        *,
        db: AsyncSession,
        current_user: Any,
        conversation_id: str,
    ) -> list[dict[str, str]]:
        resolved_conversation_id = parse_conversation_id(conversation_id)
        sender_priority = case(
            (AgentMessage.sender.in_(["user", "automation"]), 0),
            else_=1,
        )
        rows = list(
            (
                await db.scalars(
                    select(AgentMessage)
                    .where(
                        AgentMessage.user_id == cast(Any, current_user.id),
                        AgentMessage.conversation_id == resolved_conversation_id,
                        AgentMessage.sender.in_(["user", "automation", "agent"]),
                    )
                    .order_by(
                        AgentMessage.created_at.asc(),
                        sender_priority.asc(),
                        AgentMessage.id.asc(),
                    )
                )
            ).all()
        )
        if not rows:
            return []

        message_ids = [cast(Any, message.id) for message in rows]
        blocks = await block_store.list_blocks_by_message_ids(
            db,
            user_id=cast(Any, current_user.id),
            message_ids=message_ids,
        )
        blocks_by_message_id: dict[Any, list[Any]] = {}
        for block in blocks:
            blocks_by_message_id.setdefault(block.message_id, []).append(block)

        persisted_messages: list[dict[str, str]] = []
        for message in rows:
            role = sender_to_role(cast(str, message.sender))
            if role not in {"user", "agent"}:
                continue
            rendered_blocks, content = project_message_blocks(
                blocks_by_message_id.get(message.id, []),
                message_status=cast(str | None, message.status),
            )
            if not content and not rendered_blocks:
                continue
            if role == "agent" and not content:
                continue
            persisted_messages.append(
                {
                    "role": "assistant" if role == "agent" else role,
                    "content": content,
                }
            )
        return persisted_messages
