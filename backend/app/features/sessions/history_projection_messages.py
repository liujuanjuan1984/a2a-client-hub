"""Message write-path helpers for session history projection."""

from __future__ import annotations

from typing import Any, Literal, cast
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_message import AgentMessage
from app.db.models.conversation_thread import ConversationThread
from app.db.transaction import rollback_safely
from app.features.sessions import block_store
from app.features.sessions import common as session_common
from app.features.sessions import message_store
from app.features.sessions.history_projection_blocks import (
    apply_message_block_specs,
    normalize_message_block_specs,
)
from app.features.sessions.identity import conversation_identity_service
from app.features.sessions.support import SessionHubSupport
from app.features.working_directory import extract_working_directory
from app.utils.idempotency_key import normalize_idempotency_key
from app.utils.payload_extract import extract_provider_and_external_session_id
from app.utils.session_identity import normalize_non_empty_text, normalize_provider
from app.utils.timezone_util import utc_now


class SessionHistoryMessageService:
    """Writes local invoke/user messages and keeps session bindings consistent."""

    def __init__(self, *, support: SessionHubSupport) -> None:
        self._support = support

    async def ensure_local_session_for_invoke(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        agent_id: UUID,
        agent_source: session_common.SessionAgentSource,
        conversation_id: str | None,
    ) -> tuple[ConversationThread | None, session_common.SessionSource | None]:
        from app.features.sessions.common import parse_conversation_id

        if not conversation_id:
            return None, None
        try:
            normalized_conversation_id = parse_conversation_id(conversation_id)
        except ValueError as exc:
            raise ValueError("invalid_conversation_id") from exc

        target = await self._support.resolve_conversation_target(
            db,
            user_id=user_id,
            conversation_id=normalized_conversation_id,
        )

        local_session_id = (
            cast(UUID, target.thread.id) if target else normalized_conversation_id
        )

        session = (
            target.thread
            if target
            else cast(
                ConversationThread | None,
                await db.scalar(
                    select(ConversationThread).where(
                        and_(
                            ConversationThread.id == local_session_id,
                            ConversationThread.user_id == user_id,
                            ConversationThread.status
                            == ConversationThread.STATUS_ACTIVE,
                        )
                    )
                ),
            )
        )

        if session is None:
            existing_session_id = cast(
                UUID | None,
                await db.scalar(
                    select(ConversationThread.id).where(
                        ConversationThread.id == local_session_id
                    )
                ),
            )
            if existing_session_id is not None:
                raise ValueError("invalid_conversation_id")
            session = ConversationThread(
                id=local_session_id,
                user_id=user_id,
                source=ConversationThread.SOURCE_MANUAL,
                agent_id=agent_id,
                agent_source=agent_source,
                title="Session",
                last_active_at=utc_now(),
                status=ConversationThread.STATUS_ACTIVE,
            )
            db.add(session)
            try:
                await db.flush()
            except IntegrityError as exc:
                await rollback_safely(db)
                raise ValueError("invalid_conversation_id") from exc

        local_source: session_common.SessionSource
        if session.source == ConversationThread.SOURCE_MANUAL:
            local_source = "manual"
        elif session.source == ConversationThread.SOURCE_SCHEDULED:
            local_source = "scheduled"
        else:
            raise ValueError("invalid_conversation_id")

        setattr(session, "agent_id", agent_id)
        setattr(session, "agent_source", agent_source)
        setattr(session, "last_active_at", utc_now())
        session_id = cast(UUID, session.id)
        session_title = cast(str, session.title)
        if local_source == "manual":
            await self._support.ensure_local_conversation_thread(
                db,
                user_id=user_id,
                conversation_id=session_id,
                agent_id=agent_id,
                agent_source=agent_source,
                title=session_title or "Session",
                source="manual",
            )
            return session, "manual"
        return session, local_source

    async def record_local_invoke_messages(
        self,
        db: AsyncSession,
        *,
        session: ConversationThread,
        source: session_common.SessionSource,
        user_id: UUID,
        agent_id: UUID,
        agent_source: session_common.SessionAgentSource,
        query: str,
        response_content: str,
        success: bool,
        context_id: str | None,
        invoke_metadata: dict[str, Any] | None = None,
        extra_metadata: dict[str, Any] | None = None,
        response_metadata: dict[str, Any] | None = None,
        response_blocks: list[dict[str, Any]] | None = None,
        idempotency_key: str | None = None,
        user_message_id: UUID | None = None,
        agent_message_id: UUID | None = None,
        user_sender: Literal["user", "automation"] = "user",
        agent_status: str | None = None,
        finish_reason: str | None = None,
        error_code: str | None = None,
    ) -> dict[str, UUID]:
        metadata: dict[str, Any] = {
            "source": source,
            "agent_id": str(agent_id),
            "conversation_id": str(session.id),
            "success": success,
        }
        query_hash = session_common.build_query_hash(query)
        metadata["query_hash"] = query_hash
        (
            provider_from_invoke,
            external_session_id,
        ) = extract_provider_and_external_session_id(invoke_metadata or {})
        working_directory = extract_working_directory(invoke_metadata or {})
        if context_id and isinstance(context_id, str):
            metadata["context_id"] = context_id
        if provider_from_invoke:
            metadata["provider"] = provider_from_invoke
        if external_session_id:
            metadata["externalSessionId"] = external_session_id
        if working_directory:
            metadata["working_directory"] = working_directory
        if extra_metadata:
            metadata.update(extra_metadata)
        normalized_idempotency_key = normalize_idempotency_key(idempotency_key)
        if normalized_idempotency_key:
            metadata["invoke_idempotency_key"] = normalized_idempotency_key
        normalized_response_blocks = normalize_message_block_specs(response_blocks)
        if (
            source == "manual"
            and (session_title := session_common.derive_session_title_from_query(query))
            and ConversationThread.is_placeholder_title(cast(str, session.title))
        ):
            setattr(session, "title", session_title)

        conversation_id: UUID = cast(UUID, session.id)
        if source == "manual":
            await self._support.ensure_local_conversation_thread(
                db,
                user_id=user_id,
                conversation_id=conversation_id,
                agent_id=agent_id,
                agent_source=agent_source,
                title=cast(str, session.title) or "Session",
                source="manual",
            )
        if provider_from_invoke and external_session_id:
            invoke_title = session_common.derive_session_title_from_invoke_metadata(
                invoke_metadata
            )
            bind_title = invoke_title if invoke_title else cast(str, session.title)
            conversation_id = await conversation_identity_service.bind_external_session(
                db,
                user_id=user_id,
                conversation_id=conversation_id,
                source=source,
                provider=provider_from_invoke,
                external_session_id=external_session_id,
                agent_id=agent_id,
                agent_source=agent_source,
                context_id=context_id if isinstance(context_id, str) else None,
                title=bind_title or "Session",
            )
        else:
            normalized_provider = normalize_provider(provider_from_invoke)
            normalized_context_id = normalize_non_empty_text(context_id)
            if (
                normalized_provider
                and cast(str | None, session.external_provider) != normalized_provider
            ):
                setattr(session, "external_provider", normalized_provider)
            if (
                normalized_context_id
                and cast(str | None, session.context_id) != normalized_context_id
            ):
                setattr(session, "context_id", normalized_context_id)

        metadata["conversation_id"] = str(conversation_id)
        agent_metadata = dict(metadata)
        if response_metadata:
            for key, value in response_metadata.items():
                if key == "message_blocks":
                    continue
                if (
                    key in agent_metadata
                    and isinstance(agent_metadata[key], dict)
                    and isinstance(value, dict)
                ):
                    merged_nested = dict(agent_metadata[key])
                    merged_nested.update(value)
                    agent_metadata[key] = merged_nested
                    continue
                agent_metadata[key] = value
        resolved_agent_status = (
            normalize_non_empty_text(agent_status)
            if isinstance(agent_status, str)
            else None
        )
        if not resolved_agent_status:
            resolved_agent_status = "done" if success else "error"
        resolved_finish_reason = normalize_non_empty_text(finish_reason)
        resolved_error_code = normalize_non_empty_text(error_code)
        resolved_user_sender: Literal["user", "automation"] = (
            "automation" if user_sender == "automation" else "user"
        )
        requested_user_message = (
            await self._support.find_message_by_id_and_sender(
                db,
                user_id=user_id,
                message_id=user_message_id,
                sender=resolved_user_sender,
                conversation_id=conversation_id,
            )
            if isinstance(user_message_id, UUID)
            else None
        )
        requested_agent_message = (
            await self._support.find_message_by_id_and_sender(
                db,
                user_id=user_id,
                message_id=agent_message_id,
                sender="agent",
                conversation_id=conversation_id,
            )
            if isinstance(agent_message_id, UUID)
            else None
        )
        existing_user_message: AgentMessage | None = requested_user_message
        existing_agent_message: AgentMessage | None = requested_agent_message
        if normalized_idempotency_key:
            idempotent_user_message = (
                await self._support.find_message_by_idempotency_key(
                    db,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    sender=resolved_user_sender,
                    idempotency_key=normalized_idempotency_key,
                )
            )
            idempotent_agent_message = (
                await self._support.find_message_by_idempotency_key(
                    db,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    sender="agent",
                    idempotency_key=normalized_idempotency_key,
                )
            )
            if (
                existing_user_message is not None
                and idempotent_user_message is not None
                and existing_user_message.id != idempotent_user_message.id
            ):
                raise ValueError("message_id_conflict")
            if (
                existing_agent_message is not None
                and idempotent_agent_message is not None
                and existing_agent_message.id != idempotent_agent_message.id
            ):
                raise ValueError("message_id_conflict")
            if existing_user_message is None:
                existing_user_message = idempotent_user_message
            if existing_agent_message is None:
                existing_agent_message = idempotent_agent_message

        if existing_user_message is None:
            try:
                if isinstance(user_message_id, UUID):
                    user_message = await message_store.create_agent_message(
                        db,
                        id=user_message_id,
                        user_id=user_id,
                        sender=resolved_user_sender,
                        status="done",
                        conversation_id=conversation_id,
                        metadata=metadata,
                        invoke_idempotency_key=normalized_idempotency_key,
                    )
                else:
                    user_message = await message_store.create_agent_message(
                        db,
                        user_id=user_id,
                        sender=resolved_user_sender,
                        status="done",
                        conversation_id=conversation_id,
                        metadata=metadata,
                        invoke_idempotency_key=normalized_idempotency_key,
                    )
            except message_store.AgentMessageCreationError as exc:
                if isinstance(
                    user_message_id, UUID
                ) and session_common.is_agent_message_pk_violation(exc):
                    raise ValueError("message_id_conflict") from exc
                if not (
                    normalized_idempotency_key
                    and session_common.is_idempotency_unique_violation(
                        exc,
                        index_name="uq_agent_messages_conversation_sender_invoke_idempotency_key",
                    )
                ):
                    raise
                recovered_user_message = (
                    await self._support.find_message_by_idempotency_key(
                        db,
                        user_id=user_id,
                        conversation_id=conversation_id,
                        sender=resolved_user_sender,
                        idempotency_key=normalized_idempotency_key,
                    )
                )
                if recovered_user_message is None:
                    raise
                if (
                    isinstance(user_message_id, UUID)
                    and recovered_user_message.id != user_message_id
                ):
                    raise ValueError("message_id_conflict")
                user_message = recovered_user_message
        else:
            user_message = existing_user_message
            if isinstance(user_message_id, UUID) and user_message.id != user_message_id:
                raise ValueError("message_id_conflict")
            if normalized_idempotency_key:
                setattr(
                    user_message,
                    "invoke_idempotency_key",
                    normalized_idempotency_key,
                )
        await self._support.ensure_idempotent_user_query(
            db,
            user_id=user_id,
            user_message=user_message,
            query=query,
            idempotency_key=normalized_idempotency_key,
        )

        if existing_agent_message is None:
            try:
                if isinstance(agent_message_id, UUID):
                    agent_message = await message_store.create_agent_message(
                        db,
                        id=agent_message_id,
                        user_id=user_id,
                        sender="agent",
                        conversation_id=conversation_id,
                        status=resolved_agent_status,
                        finish_reason=resolved_finish_reason,
                        error_code=resolved_error_code,
                        metadata=agent_metadata,
                        invoke_idempotency_key=normalized_idempotency_key,
                    )
                else:
                    agent_message = await message_store.create_agent_message(
                        db,
                        user_id=user_id,
                        sender="agent",
                        conversation_id=conversation_id,
                        status=resolved_agent_status,
                        finish_reason=resolved_finish_reason,
                        error_code=resolved_error_code,
                        metadata=agent_metadata,
                        invoke_idempotency_key=normalized_idempotency_key,
                    )
            except message_store.AgentMessageCreationError as exc:
                if isinstance(
                    agent_message_id, UUID
                ) and session_common.is_agent_message_pk_violation(exc):
                    raise ValueError("message_id_conflict") from exc
                if not (
                    normalized_idempotency_key
                    and session_common.is_idempotency_unique_violation(
                        exc,
                        index_name="uq_agent_messages_conversation_sender_invoke_idempotency_key",
                    )
                ):
                    raise
                recovered_agent_message = (
                    await self._support.find_message_by_idempotency_key(
                        db,
                        user_id=user_id,
                        conversation_id=conversation_id,
                        sender="agent",
                        idempotency_key=normalized_idempotency_key,
                    )
                )
                if recovered_agent_message is None:
                    raise
                if (
                    isinstance(agent_message_id, UUID)
                    and recovered_agent_message.id != agent_message_id
                ):
                    raise ValueError("message_id_conflict")
                updated_agent_message = await message_store.update_agent_message(
                    db,
                    message=recovered_agent_message,
                    status=resolved_agent_status,
                    finish_reason=resolved_finish_reason,
                    error_code=resolved_error_code,
                    message_metadata=agent_metadata,
                    invoke_idempotency_key=normalized_idempotency_key,
                )
                if updated_agent_message is None:
                    raise ValueError("message_update_failed")
                agent_message = updated_agent_message
        else:
            if (
                isinstance(agent_message_id, UUID)
                and existing_agent_message.id != agent_message_id
            ):
                raise ValueError("message_id_conflict")
            updated_agent_message = await message_store.update_agent_message(
                db,
                message=existing_agent_message,
                status=resolved_agent_status,
                finish_reason=resolved_finish_reason,
                error_code=resolved_error_code,
                message_metadata=agent_metadata,
                invoke_idempotency_key=normalized_idempotency_key,
            )
            if updated_agent_message is None:
                raise ValueError("message_update_failed")
            agent_message = updated_agent_message
        await self._support.upsert_single_text_block(
            db,
            user_id=user_id,
            message_id=cast(UUID, user_message.id),
            content=query,
            source=(
                "user_input" if resolved_user_sender == "user" else "automation_input"
            ),
        )
        if normalized_response_blocks:
            await apply_message_block_specs(
                db,
                user_id=user_id,
                message_id=cast(UUID, agent_message.id),
                block_specs=normalized_response_blocks,
                idempotency_key=normalized_idempotency_key,
            )
        elif isinstance(response_content, str) and response_content:
            existing_agent_blocks = await block_store.list_blocks_by_message_id(
                db,
                user_id=user_id,
                message_id=cast(UUID, agent_message.id),
            )
            can_upsert_snapshot = not existing_agent_blocks or (
                len(existing_agent_blocks) == 1
                and int(existing_agent_blocks[0].block_seq) == 1
                and session_common.normalize_block_type(
                    cast(str | None, existing_agent_blocks[0].block_type)
                )
                == "text"
                and normalize_non_empty_text(
                    cast(str | None, existing_agent_blocks[0].source)
                )
                in {"final_snapshot", "finalize_snapshot"}
            )
            if can_upsert_snapshot:
                await self._support.upsert_single_text_block(
                    db,
                    user_id=user_id,
                    message_id=cast(UUID, agent_message.id),
                    content=response_content,
                    source="finalize_snapshot",
                )
        target_session = session
        if conversation_id != cast(UUID, session.id):
            rebound_session = await self._support.get_local_session_by_id(
                db,
                user_id=user_id,
                local_session_id=conversation_id,
            )
            if rebound_session is not None:
                target_session = rebound_session
        setattr(target_session, "last_active_at", utc_now())
        return {
            "conversation_id": conversation_id,
            "user_message_id": cast(UUID, user_message.id),
            "agent_message_id": cast(UUID, agent_message.id),
        }

    async def record_local_invoke_messages_by_local_session_id(
        self,
        db: AsyncSession,
        *,
        local_session_id: UUID,
        source: session_common.SessionSource,
        user_id: UUID,
        agent_id: UUID,
        agent_source: session_common.SessionAgentSource,
        query: str,
        response_content: str,
        success: bool,
        context_id: str | None,
        invoke_metadata: dict[str, Any] | None = None,
        extra_metadata: dict[str, Any] | None = None,
        response_metadata: dict[str, Any] | None = None,
        response_blocks: list[dict[str, Any]] | None = None,
        idempotency_key: str | None = None,
        user_message_id: UUID | None = None,
        agent_message_id: UUID | None = None,
        user_sender: Literal["user", "automation"] = "user",
        agent_status: str | None = None,
        finish_reason: str | None = None,
        error_code: str | None = None,
    ) -> dict[str, UUID]:
        session = await self._support.get_local_session_by_id(
            db,
            user_id=user_id,
            local_session_id=local_session_id,
        )
        if session is None:
            return {}

        return await self.record_local_invoke_messages(
            db,
            session=session,
            source=source,
            user_id=user_id,
            agent_id=agent_id,
            agent_source=agent_source,
            query=query,
            response_content=response_content,
            success=success,
            context_id=context_id,
            invoke_metadata=invoke_metadata,
            extra_metadata=extra_metadata,
            response_metadata=response_metadata,
            response_blocks=response_blocks,
            idempotency_key=idempotency_key,
            user_message_id=user_message_id,
            agent_message_id=agent_message_id,
            user_sender=user_sender,
            agent_status=agent_status,
            finish_reason=finish_reason,
            error_code=error_code,
        )

    async def record_user_message_by_local_session_id(
        self,
        db: AsyncSession,
        *,
        local_session_id: UUID,
        user_id: UUID,
        content: str,
        metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        user_message_id: UUID | None = None,
    ) -> dict[str, UUID]:
        session = await self._support.get_local_session_by_id(
            db,
            user_id=user_id,
            local_session_id=local_session_id,
        )
        if session is None:
            return {}

        normalized_content = str(content or "")
        if not normalized_content.strip():
            raise ValueError("invalid_query")

        normalized_idempotency_key = normalize_idempotency_key(idempotency_key)
        existing_user_message = (
            await self._support.find_message_by_id_and_sender(
                db,
                user_id=user_id,
                message_id=user_message_id,
                sender="user",
                conversation_id=local_session_id,
            )
            if isinstance(user_message_id, UUID)
            else None
        )
        if existing_user_message is None and normalized_idempotency_key:
            existing_user_message = await self._support.find_message_by_idempotency_key(
                db,
                user_id=user_id,
                conversation_id=local_session_id,
                sender="user",
                idempotency_key=normalized_idempotency_key,
            )
            if (
                existing_user_message is not None
                and isinstance(user_message_id, UUID)
                and existing_user_message.id != user_message_id
            ):
                raise ValueError("message_id_conflict")

        message_metadata = dict(metadata or {})
        if normalized_idempotency_key:
            message_metadata["invoke_idempotency_key"] = normalized_idempotency_key

        if existing_user_message is None:
            try:
                create_kwargs: dict[str, Any] = {
                    "user_id": user_id,
                    "sender": "user",
                    "status": "done",
                    "conversation_id": local_session_id,
                    "metadata": message_metadata,
                    "invoke_idempotency_key": normalized_idempotency_key,
                }
                if isinstance(user_message_id, UUID):
                    create_kwargs["id"] = user_message_id
                user_message = await message_store.create_agent_message(
                    db,
                    **create_kwargs,
                )
            except message_store.AgentMessageCreationError as exc:
                if isinstance(
                    user_message_id, UUID
                ) and session_common.is_agent_message_pk_violation(exc):
                    raise ValueError("message_id_conflict") from exc
                if not (
                    normalized_idempotency_key
                    and session_common.is_idempotency_unique_violation(
                        exc,
                        index_name="uq_agent_messages_conversation_sender_invoke_idempotency_key",
                    )
                ):
                    raise
                recovered_user_message = (
                    await self._support.find_message_by_idempotency_key(
                        db,
                        user_id=user_id,
                        conversation_id=local_session_id,
                        sender="user",
                        idempotency_key=normalized_idempotency_key,
                    )
                )
                if recovered_user_message is None:
                    raise
                if (
                    isinstance(user_message_id, UUID)
                    and recovered_user_message.id != user_message_id
                ):
                    raise ValueError("message_id_conflict")
                user_message = recovered_user_message
        else:
            user_message = existing_user_message
            if isinstance(user_message_id, UUID) and user_message.id != user_message_id:
                raise ValueError("message_id_conflict")
            if normalized_idempotency_key:
                setattr(
                    user_message,
                    "invoke_idempotency_key",
                    normalized_idempotency_key,
                )
            if message_metadata:
                merged_metadata = dict(
                    getattr(user_message, "message_metadata", {}) or {}
                )
                merged_metadata.update(message_metadata)
                setattr(user_message, "message_metadata", merged_metadata)
                await db.flush()

        await self._support.ensure_idempotent_user_query(
            db,
            user_id=user_id,
            user_message=user_message,
            query=normalized_content,
            idempotency_key=normalized_idempotency_key,
        )
        await self._support.upsert_single_text_block(
            db,
            user_id=user_id,
            message_id=cast(UUID, user_message.id),
            content=normalized_content,
            source="user_input",
        )
        setattr(session, "last_active_at", utc_now())
        return {
            "conversation_id": local_session_id,
            "user_message_id": cast(UUID, user_message.id),
        }

    async def ensure_local_invoke_message_headers_by_local_session_id(
        self,
        db: AsyncSession,
        *,
        local_session_id: UUID,
        source: session_common.SessionSource,
        user_id: UUID,
        agent_id: UUID,
        agent_source: session_common.SessionAgentSource,
        query: str,
        context_id: str | None,
        invoke_metadata: dict[str, Any] | None = None,
        extra_metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        user_message_id: UUID | None = None,
        agent_message_id: UUID | None = None,
        user_sender: Literal["user", "automation"] = "user",
    ) -> dict[str, UUID]:
        session = await self._support.get_local_session_by_id(
            db,
            user_id=user_id,
            local_session_id=local_session_id,
        )
        if session is None:
            return {}

        normalized_idempotency_key = normalize_idempotency_key(idempotency_key)
        if normalized_idempotency_key:
            existing_user_message = cast(
                AgentMessage | None,
                await db.scalar(
                    select(AgentMessage).where(
                        and_(
                            AgentMessage.user_id == user_id,
                            AgentMessage.conversation_id == local_session_id,
                            AgentMessage.sender == user_sender,
                            AgentMessage.invoke_idempotency_key
                            == normalized_idempotency_key,
                        )
                    )
                ),
            )
            existing_agent_message = cast(
                AgentMessage | None,
                await db.scalar(
                    select(AgentMessage).where(
                        and_(
                            AgentMessage.user_id == user_id,
                            AgentMessage.conversation_id == local_session_id,
                            AgentMessage.sender == "agent",
                            AgentMessage.invoke_idempotency_key
                            == normalized_idempotency_key,
                        )
                    )
                ),
            )
            if existing_user_message and existing_agent_message:
                if (
                    isinstance(user_message_id, UUID)
                    and existing_user_message.id != user_message_id
                ):
                    raise ValueError("message_id_conflict")
                if (
                    isinstance(agent_message_id, UUID)
                    and existing_agent_message.id != agent_message_id
                ):
                    raise ValueError("message_id_conflict")
                return {
                    "conversation_id": local_session_id,
                    "user_message_id": cast(UUID, existing_user_message.id),
                    "agent_message_id": cast(UUID, existing_agent_message.id),
                }

        return await self.record_local_invoke_messages(
            db,
            session=session,
            source=source,
            user_id=user_id,
            agent_id=agent_id,
            agent_source=agent_source,
            query=query,
            response_content="",
            success=False,
            context_id=context_id,
            invoke_metadata=invoke_metadata,
            extra_metadata=extra_metadata,
            response_metadata=None,
            idempotency_key=idempotency_key,
            user_message_id=user_message_id,
            agent_message_id=agent_message_id,
            user_sender=user_sender,
            agent_status="streaming",
            finish_reason=None,
            error_code=None,
        )
