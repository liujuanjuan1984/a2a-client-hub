"""History write paths and block projection for the unified session domain."""

from __future__ import annotations

import re
from typing import Any, cast
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_message import AgentMessage
from app.db.models.agent_message_block import AgentMessageBlock
from app.db.models.conversation_thread import ConversationThread
from app.db.transaction import rollback_safely
from app.features.sessions import block_store, message_store
from app.features.sessions.common import (
    SessionAgentSource,
    SessionSource,
    build_interrupt_lifecycle_message_content,
    build_interrupt_lifecycle_message_id,
    build_preempt_message_content,
    build_preempt_message_id,
    build_query_hash,
    create_block_with_conflict_recovery,
    derive_session_title_from_invoke_metadata,
    derive_session_title_from_query,
    deserialize_interrupt_event_block_content,
    is_agent_message_pk_violation,
    is_idempotency_unique_violation,
    is_primary_text_snapshot_source,
    normalize_block_type,
    normalize_interrupt_lifecycle_event,
    normalize_preempt_event,
    read_block_cursor_state,
    write_block_cursor_state,
)
from app.features.sessions.identity import conversation_identity_service
from app.features.sessions.support import SessionHubSupport
from app.features.working_directory import extract_working_directory
from app.utils.idempotency_key import normalize_idempotency_key
from app.utils.payload_extract import extract_provider_and_external_session_id
from app.utils.session_identity import normalize_non_empty_text, normalize_provider
from app.utils.timezone_util import utc_now

BLOCK_OPERATION_TYPES = frozenset({"append", "replace", "finalize"})
REASONING_OVERLAP_WORD_PATTERN = re.compile(r"[\w]+", re.UNICODE)
MIN_REASONING_OVERLAP_WORD_LENGTH = 5


def _default_lane_id(block_type: str) -> str:
    return "primary_text" if block_type == "text" else block_type


def _should_preserve_existing_interrupt_content(
    *,
    block_type: str,
    operation: str,
    incoming_content: str,
) -> bool:
    if block_type != "interrupt_event" or operation != "replace":
        return False
    _, interrupt = deserialize_interrupt_event_block_content(incoming_content)
    return bool(interrupt and interrupt.get("phase") == "resolved")


def _normalize_block_operation(
    operation: str | None,
    *,
    append: bool,
    source: str | None,
) -> str:
    normalized = normalize_non_empty_text(operation)
    if normalized in BLOCK_OPERATION_TYPES:
        return normalized
    if is_primary_text_snapshot_source(source):
        return "replace"
    return "append" if append else "replace"


def _is_word_char(value: str | None) -> bool:
    return bool(value and REASONING_OVERLAP_WORD_PATTERN.fullmatch(value))


def _is_boundary_aligned_reasoning_overlap(
    reasoning_content: str,
    text: str,
    overlap: int,
) -> bool:
    overlap_start = len(reasoning_content) - overlap
    before_overlap = reasoning_content[overlap_start - 1] if overlap_start > 0 else None
    after_overlap = text[overlap] if overlap < len(text) else None
    return not _is_word_char(before_overlap) and not _is_word_char(after_overlap)


def _is_substantial_reasoning_overlap(candidate: str) -> bool:
    tokens = REASONING_OVERLAP_WORD_PATTERN.findall(candidate)
    return len(tokens) >= 2 or any(
        len(token) >= MIN_REASONING_OVERLAP_WORD_LENGTH for token in tokens
    )


def _trim_overlapping_reasoning_prefix(
    reasoning_content: str,
    text: str,
) -> str:
    if not reasoning_content or not text:
        return text
    for overlap in range(min(len(reasoning_content), len(text)), 0, -1):
        candidate = reasoning_content[-overlap:]
        if (
            text.startswith(candidate)
            and _is_boundary_aligned_reasoning_overlap(reasoning_content, text, overlap)
            and _is_substantial_reasoning_overlap(candidate)
        ):
            return re.sub(r"^\s+", "", text[overlap:])
    return text


def _merge_preempt_event(
    *,
    existing_event: dict[str, Any] | None,
    incoming_event: dict[str, Any],
) -> dict[str, Any]:
    normalized_existing = normalize_preempt_event(existing_event)
    if normalized_existing is None:
        return incoming_event
    if (
        normalized_existing.get("status") in {"completed", "failed"}
        and incoming_event.get("status") == "accepted"
    ):
        merged_event = dict(normalized_existing)
        for field_name in (
            "target_message_id",
            "replacement_user_message_id",
            "replacement_agent_message_id",
        ):
            if (
                field_name not in merged_event
                and incoming_event.get(field_name) is not None
            ):
                merged_event[field_name] = incoming_event[field_name]
        for field_name in ("target_task_ids", "failed_error_codes"):
            merged_values: list[str] = []
            for raw_values in (
                normalized_existing.get(field_name),
                incoming_event.get(field_name),
            ):
                if not isinstance(raw_values, list):
                    continue
                for item in raw_values:
                    normalized_item = normalize_non_empty_text(item)
                    if normalized_item and normalized_item not in merged_values:
                        merged_values.append(normalized_item)
            merged_event[field_name] = merged_values
        return merged_event
    return incoming_event


def _update_block_event_metadata(
    block: AgentMessageBlock,
    *,
    seq: int,
    event_id: str | None,
    source: str | None,
    base_seq: int | None,
) -> None:
    if source:
        setattr(block, "source", source)
    start_event_seq = cast(int | None, block.start_event_seq)
    if start_event_seq is None:
        setattr(block, "start_event_seq", seq)
    end_event_seq = cast(int | None, block.end_event_seq)
    if end_event_seq is None or seq >= end_event_seq:
        setattr(block, "end_event_seq", seq)
    if base_seq is not None:
        setattr(block, "base_seq", base_seq)
    normalized_event_id = normalize_non_empty_text(event_id)
    start_event_id = cast(str | None, block.start_event_id)
    if normalized_event_id and not start_event_id:
        setattr(block, "start_event_id", normalized_event_id)
    if normalized_event_id:
        setattr(block, "end_event_id", normalized_event_id)


class SessionHistoryProjectionService:
    """Session write paths, history persistence, and block cursor projection."""

    def __init__(self, *, support: SessionHubSupport) -> None:
        self._support = support

    async def ensure_local_session_for_invoke(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        agent_id: UUID,
        agent_source: SessionAgentSource,
        conversation_id: str | None,
    ) -> tuple[ConversationThread | None, SessionSource | None]:
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

        local_source: SessionSource
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
        source: SessionSource,
        user_id: UUID,
        agent_id: UUID,
        agent_source: SessionAgentSource,
        query: str,
        response_content: str,
        success: bool,
        context_id: str | None,
        invoke_metadata: dict[str, Any] | None = None,
        extra_metadata: dict[str, Any] | None = None,
        response_metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        user_message_id: UUID | None = None,
        agent_message_id: UUID | None = None,
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
        query_hash = build_query_hash(query)
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
        if (
            source == "manual"
            and (session_title := derive_session_title_from_query(query))
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
            invoke_title = derive_session_title_from_invoke_metadata(invoke_metadata)
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
        requested_user_message = (
            await self._support.find_message_by_id_and_sender(
                db,
                user_id=user_id,
                message_id=user_message_id,
                sender="user",
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
                    sender="user",
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
                        sender="user",
                        status="done",
                        conversation_id=conversation_id,
                        metadata=metadata,
                        invoke_idempotency_key=normalized_idempotency_key,
                    )
                else:
                    user_message = await message_store.create_agent_message(
                        db,
                        user_id=user_id,
                        sender="user",
                        status="done",
                        conversation_id=conversation_id,
                        metadata=metadata,
                        invoke_idempotency_key=normalized_idempotency_key,
                    )
            except message_store.AgentMessageCreationError as exc:
                if isinstance(user_message_id, UUID) and is_agent_message_pk_violation(
                    exc
                ):
                    raise ValueError("message_id_conflict") from exc
                if not (
                    normalized_idempotency_key
                    and is_idempotency_unique_violation(
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
                if isinstance(agent_message_id, UUID) and is_agent_message_pk_violation(
                    exc
                ):
                    raise ValueError("message_id_conflict") from exc
                if not (
                    normalized_idempotency_key
                    and is_idempotency_unique_violation(
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
            source="user_input",
        )
        if isinstance(response_content, str) and response_content:
            existing_agent_blocks = await block_store.list_blocks_by_message_id(
                db,
                user_id=user_id,
                message_id=cast(UUID, agent_message.id),
            )
            can_upsert_snapshot = not existing_agent_blocks or (
                len(existing_agent_blocks) == 1
                and int(existing_agent_blocks[0].block_seq) == 1
                and normalize_block_type(
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
        source: SessionSource,
        user_id: UUID,
        agent_id: UUID,
        agent_source: SessionAgentSource,
        query: str,
        response_content: str,
        success: bool,
        context_id: str | None,
        invoke_metadata: dict[str, Any] | None = None,
        extra_metadata: dict[str, Any] | None = None,
        response_metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        user_message_id: UUID | None = None,
        agent_message_id: UUID | None = None,
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
            idempotency_key=idempotency_key,
            user_message_id=user_message_id,
            agent_message_id=agent_message_id,
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
                if isinstance(user_message_id, UUID) and is_agent_message_pk_violation(
                    exc
                ):
                    raise ValueError("message_id_conflict") from exc
                if not (
                    normalized_idempotency_key
                    and is_idempotency_unique_violation(
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
        source: SessionSource,
        user_id: UUID,
        agent_id: UUID,
        agent_source: SessionAgentSource,
        query: str,
        context_id: str | None,
        invoke_metadata: dict[str, Any] | None = None,
        extra_metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        user_message_id: UUID | None = None,
        agent_message_id: UUID | None = None,
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
                            AgentMessage.sender.in_(["user", "automation"]),
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
            agent_status="streaming",
            finish_reason=None,
            error_code=None,
        )

    async def record_interrupt_lifecycle_event_by_local_session_id(
        self,
        db: AsyncSession,
        *,
        local_session_id: UUID,
        user_id: UUID,
        event: dict[str, Any],
    ) -> UUID | None:
        session = await self._support.get_local_session_by_id(
            db,
            user_id=user_id,
            local_session_id=local_session_id,
        )
        if session is None:
            return None
        return await self.record_interrupt_lifecycle_event(
            db,
            conversation_id=cast(UUID, session.id),
            user_id=user_id,
            event=event,
        )

    async def record_interrupt_lifecycle_event(
        self,
        db: AsyncSession,
        *,
        conversation_id: UUID,
        user_id: UUID,
        event: dict[str, Any],
    ) -> UUID | None:
        normalized_event = normalize_interrupt_lifecycle_event(event)
        if normalized_event is None:
            return None

        message_id = build_interrupt_lifecycle_message_id(
            conversation_id=conversation_id,
            request_id=normalized_event["request_id"],
            phase=normalized_event["phase"],
        )
        message_metadata = {"interrupt": normalized_event}
        existing_message = await self._support.find_message_by_id_and_sender(
            db,
            user_id=user_id,
            message_id=message_id,
            sender="system",
            conversation_id=conversation_id,
        )
        if existing_message is None:
            system_message = await message_store.create_agent_message(
                db,
                id=message_id,
                created_at=utc_now(),
                user_id=user_id,
                sender="system",
                status="done",
                conversation_id=conversation_id,
                metadata=message_metadata,
            )
        else:
            updated_system_message = await message_store.update_agent_message(
                db,
                message=existing_message,
                status="done",
                message_metadata=message_metadata,
            )
            if updated_system_message is None:
                raise ValueError("message_update_failed")
            system_message = updated_system_message
        await self._support.upsert_single_text_block(
            db,
            user_id=user_id,
            message_id=cast(UUID, system_message.id),
            content=build_interrupt_lifecycle_message_content(normalized_event),
            source="interrupt_lifecycle",
        )
        return cast(UUID, system_message.id)

    async def record_preempt_event_by_local_session_id(
        self,
        db: AsyncSession,
        *,
        local_session_id: UUID,
        user_id: UUID,
        event: dict[str, Any],
    ) -> UUID | None:
        session = await self._support.get_local_session_by_id(
            db,
            user_id=user_id,
            local_session_id=local_session_id,
        )
        if session is None:
            return None
        return await self.record_preempt_event(
            db,
            conversation_id=cast(UUID, session.id),
            user_id=user_id,
            event=event,
        )

    async def record_preempt_event(
        self,
        db: AsyncSession,
        *,
        conversation_id: UUID,
        user_id: UUID,
        event: dict[str, Any],
    ) -> UUID | None:
        normalized_event = normalize_preempt_event(event)
        if normalized_event is None:
            return None

        message_id = build_preempt_message_id(
            conversation_id=conversation_id,
            replacement_user_message_id=cast(
                str | None, normalized_event.get("replacement_user_message_id")
            ),
            replacement_agent_message_id=cast(
                str | None, normalized_event.get("replacement_agent_message_id")
            ),
            target_message_id=cast(
                str | None, normalized_event.get("target_message_id")
            ),
            reason=cast(str, normalized_event["reason"]),
        )
        existing_message = await self._support.find_message_by_id_and_sender(
            db,
            user_id=user_id,
            message_id=message_id,
            sender="system",
            conversation_id=conversation_id,
        )
        existing_metadata = (
            cast(dict[str, Any], existing_message.metadata)
            if existing_message is not None
            and isinstance(existing_message.metadata, dict)
            else {}
        )
        resolved_event = _merge_preempt_event(
            existing_event=cast(
                dict[str, Any] | None, existing_metadata.get("preempt")
            ),
            incoming_event=normalized_event,
        )
        message_metadata = {"preempt": resolved_event}
        if existing_message is None:
            system_message = await message_store.create_agent_message(
                db,
                id=message_id,
                created_at=utc_now(),
                user_id=user_id,
                sender="system",
                status="done",
                conversation_id=conversation_id,
                metadata=message_metadata,
            )
        else:
            updated_system_message = await message_store.update_agent_message(
                db,
                message=existing_message,
                status="done",
                message_metadata=message_metadata,
            )
            if updated_system_message is None:
                raise ValueError("message_update_failed")
            system_message = updated_system_message
        await self._support.upsert_single_text_block(
            db,
            user_id=user_id,
            message_id=cast(UUID, system_message.id),
            content=build_preempt_message_content(resolved_event),
            source="invoke_preempt",
        )
        return cast(UUID, system_message.id)

    async def append_agent_message_block_update(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        agent_message_id: UUID,
        seq: int,
        block_type: str,
        content: str,
        append: bool,
        is_finished: bool,
        block_id: str | None = None,
        lane_id: str | None = None,
        operation: str | None = None,
        base_seq: int | None = None,
        event_id: str | None = None,
        source: str | None = None,
        agent_message: AgentMessage | None = None,
    ) -> AgentMessageBlock | None:
        if seq <= 0:
            return None
        message = agent_message
        if message is None:
            message = cast(
                AgentMessage | None,
                await db.scalar(
                    select(AgentMessage).where(
                        and_(
                            AgentMessage.id == agent_message_id,
                            AgentMessage.user_id == user_id,
                            AgentMessage.sender == "agent",
                        )
                    )
                ),
            )
        if message is None:
            return None

        message_metadata = dict(getattr(message, "message_metadata", None) or {})
        cursor_state = read_block_cursor_state(message_metadata)
        if seq <= cursor_state["last_event_seq"]:
            return None

        normalized_type = normalize_block_type(block_type)
        normalized_source = normalize_non_empty_text(source)
        normalized_lane_id = normalize_non_empty_text(lane_id) or _default_lane_id(
            normalized_type
        )
        normalized_operation = _normalize_block_operation(
            operation,
            append=append,
            source=normalized_source,
        )
        normalized_base_seq = (
            int(base_seq) if isinstance(base_seq, int) and base_seq > 0 else None
        )
        if normalized_base_seq is None and normalized_operation in {
            "replace",
            "finalize",
        }:
            normalized_base_seq = seq

        active_block_seq = cursor_state["active_block_seq"]
        active_block: AgentMessageBlock | None = None
        if active_block_seq > 0:
            active_block = await block_store.find_block_by_message_and_block_seq(
                db,
                user_id=user_id,
                message_id=agent_message_id,
                block_seq=active_block_seq,
            )
        if active_block is None:
            active_block = await block_store.find_last_block_for_message(
                db,
                user_id=user_id,
                message_id=agent_message_id,
            )

        latest_text_block: AgentMessageBlock | None = None
        if normalized_type == "text":
            latest_text_block = await block_store.find_last_block_for_message_and_type(
                db,
                user_id=user_id,
                message_id=agent_message_id,
                block_type="text",
            )
        normalized_block_id = normalize_non_empty_text(block_id)
        if not normalized_block_id:
            if (
                normalized_type == "text"
                and is_primary_text_snapshot_source(normalized_source)
                and latest_text_block is not None
            ):
                normalized_block_id = str(latest_text_block.block_id)
            elif (
                active_block is not None
                and str(active_block.lane_id or "") == normalized_lane_id
                and not bool(active_block.is_finished)
            ):
                normalized_block_id = str(active_block.block_id)
            else:
                normalized_block_id = f"{agent_message_id}:{normalized_lane_id}:{seq}"

        target_block = await block_store.find_block_by_message_and_block_id(
            db,
            user_id=user_id,
            message_id=agent_message_id,
            block_id=normalized_block_id,
        )

        normalized_content = str(content or "")
        if (
            normalized_operation == "replace"
            and normalized_type == "text"
            and is_primary_text_snapshot_source(normalized_source)
        ):
            latest_reasoning_block = (
                await block_store.find_last_block_for_message_and_type(
                    db,
                    user_id=user_id,
                    message_id=agent_message_id,
                    block_type="reasoning",
                )
            )
            normalized_content = _trim_overlapping_reasoning_prefix(
                cast(str | None, getattr(latest_reasoning_block, "content", None))
                or "",
                normalized_content,
            )
        if not normalized_content and normalized_operation != "finalize":
            return None

        persisted_block: AgentMessageBlock | None = None
        current_base_seq = (
            int(getattr(target_block, "base_seq", 0) or 0)
            if target_block is not None
            else 0
        )
        if (
            target_block is not None
            and normalized_base_seq is not None
            and current_base_seq > 0
            and normalized_base_seq < current_base_seq
        ):
            return None

        if (
            active_block is not None
            and target_block is not None
            and active_block is not target_block
            and not bool(active_block.is_finished)
        ):
            setattr(active_block, "is_finished", True)

        if normalized_operation == "finalize":
            if target_block is None:
                return None
            setattr(target_block, "is_finished", True)
            setattr(target_block, "block_type", normalized_type)
            setattr(target_block, "lane_id", normalized_lane_id)
            _update_block_event_metadata(
                target_block,
                seq=seq,
                event_id=event_id,
                source=normalized_source,
                base_seq=normalized_base_seq,
            )
            persisted_block = target_block
        elif target_block is not None:
            should_preserve_interrupt_content = (
                _should_preserve_existing_interrupt_content(
                    block_type=normalized_type,
                    operation=normalized_operation,
                    incoming_content=normalized_content,
                )
            )
            if normalized_operation == "append":
                current_content = cast(str | None, target_block.content) or ""
                setattr(
                    target_block, "content", f"{current_content}{normalized_content}"
                )
            else:
                if not should_preserve_interrupt_content:
                    setattr(target_block, "content", normalized_content)
            setattr(target_block, "block_type", normalized_type)
            setattr(target_block, "lane_id", normalized_lane_id)
            setattr(target_block, "is_finished", bool(is_finished))
            _update_block_event_metadata(
                target_block,
                seq=seq,
                event_id=event_id,
                source=normalized_source,
                base_seq=normalized_base_seq,
            )
            persisted_block = target_block
        else:
            if active_block is not None and not bool(active_block.is_finished):
                setattr(active_block, "is_finished", True)
            next_block_seq = (
                max(
                    cursor_state["last_block_seq"],
                    int(getattr(active_block, "block_seq", 0) or 0),
                )
                + 1
            )
            normalized_event_id = normalize_non_empty_text(event_id)
            persisted_block = await create_block_with_conflict_recovery(
                db,
                user_id=user_id,
                message_id=agent_message_id,
                block_seq=next_block_seq,
                block_id=normalized_block_id,
                lane_id=normalized_lane_id,
                block_type=normalized_type,
                content=normalized_content,
                is_finished=bool(is_finished) or normalized_operation == "finalize",
                source=normalized_source,
                start_event_seq=seq,
                end_event_seq=seq,
                base_seq=normalized_base_seq,
                start_event_id=normalized_event_id,
                end_event_id=normalized_event_id,
            )

        if persisted_block is None:
            return None
        cursor_state["last_event_seq"] = seq
        cursor_state["last_block_seq"] = max(
            cursor_state["last_block_seq"],
            int(getattr(persisted_block, "block_seq", 0) or 0),
        )
        next_active_block: AgentMessageBlock | None = None
        if (
            active_block is not None
            and active_block is not persisted_block
            and not bool(active_block.is_finished)
        ):
            next_active_block = active_block
        elif not bool(getattr(persisted_block, "is_finished", False)):
            next_active_block = persisted_block
        if next_active_block is None:
            cursor_state["active_block_seq"] = 0
        else:
            cursor_state["active_block_seq"] = int(
                getattr(next_active_block, "block_seq", 0) or 0
            )
        write_block_cursor_state(message_metadata, cursor_state)
        setattr(message, "message_metadata", message_metadata)
        await db.flush()
        return persisted_block

    async def append_agent_message_block_updates(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        agent_message_id: UUID,
        updates: list[dict[str, Any]],
        agent_message: AgentMessage | None = None,
    ) -> list[AgentMessageBlock]:
        if not updates:
            return []
        message = agent_message
        if message is None:
            message = cast(
                AgentMessage | None,
                await db.scalar(
                    select(AgentMessage).where(
                        and_(
                            AgentMessage.id == agent_message_id,
                            AgentMessage.user_id == user_id,
                            AgentMessage.sender == "agent",
                        )
                    )
                ),
            )
        if message is None:
            return []

        persisted_blocks: list[AgentMessageBlock] = []
        for update in updates:
            persisted = await self.append_agent_message_block_update(
                db,
                user_id=user_id,
                agent_message_id=agent_message_id,
                seq=update["seq"],
                block_type=update["block_type"],
                content=update["content"],
                append=update.get("append", True),
                is_finished=update.get("is_finished", False),
                block_id=update.get("block_id"),
                lane_id=update.get("lane_id"),
                operation=update.get("op"),
                base_seq=update.get("base_seq"),
                event_id=update.get("event_id"),
                source=update.get("source"),
                agent_message=message,
            )
            if persisted:
                persisted_blocks.append(persisted)
        return persisted_blocks

    async def has_agent_message_blocks(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        agent_message_id: UUID,
    ) -> bool:
        return await block_store.has_blocks_for_message(
            db,
            user_id=user_id,
            message_id=agent_message_id,
        )
