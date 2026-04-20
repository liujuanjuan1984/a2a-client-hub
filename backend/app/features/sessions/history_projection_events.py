"""System-event persistence helpers for session history projection."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.features.sessions import common as session_common
from app.features.sessions import message_store
from app.features.sessions.support import SessionHubSupport
from app.utils.session_identity import normalize_non_empty_text
from app.utils.timezone_util import utc_now


def _merge_preempt_event(
    *,
    existing_event: dict[str, Any] | None,
    incoming_event: dict[str, Any],
) -> dict[str, Any]:
    normalized_existing = session_common.normalize_preempt_event(existing_event)
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


class SessionHistoryEventService:
    """Persists normalized interrupt and preempt events as durable system messages."""

    def __init__(self, *, support: SessionHubSupport) -> None:
        self._support = support

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
        normalized_event = session_common.normalize_interrupt_lifecycle_event(event)
        if normalized_event is None:
            return None

        message_id = session_common.build_interrupt_lifecycle_message_id(
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
            content=session_common.build_interrupt_lifecycle_message_content(
                normalized_event
            ),
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
        normalized_event = session_common.normalize_preempt_event(event)
        if normalized_event is None:
            return None

        message_id = session_common.build_preempt_message_id(
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
            content=session_common.build_preempt_message_content(resolved_event),
            source="invoke_preempt",
        )
        return cast(UUID, system_message.id)
