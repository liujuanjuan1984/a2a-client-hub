"""Unified conversation domain helpers and query service.

This module provides a single read model for session list/history/continue across:
- local manual chat sessions
- local scheduled sessions
- remote OpenCode sessions (via extension adapters)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_message import AgentMessage
from app.db.models.conversation_thread import ConversationThread
from app.handlers import agent_message as agent_message_handler
from app.integrations.a2a_extensions import get_a2a_extensions_service
from app.integrations.a2a_extensions.errors import A2AExtensionUpstreamError
from app.services.a2a_runtime import (
    A2ARuntimeNotFoundError,
    A2ARuntimeValidationError,
    a2a_runtime_builder,
)
from app.services.conversation_identity import conversation_identity_service
from app.services.hub_a2a_runtime import (
    HubA2ARuntimeNotFoundError,
    HubA2ARuntimeValidationError,
    hub_a2a_runtime_builder,
)
from app.services.opencode_session_directory import opencode_session_directory_service
from app.utils.payload_extract import (
    as_dict,
    extract_context_id,
    extract_provider_and_external_session_id,
    pick_first_non_empty_str,
)
from app.utils.session_identity import normalize_non_empty_text, normalize_provider
from app.utils.timezone_util import utc_now

SessionSource = Literal["manual", "scheduled", "opencode"]
ResolvedSource = Literal["manual", "scheduled", "opencode"]


@dataclass(frozen=True)
class ResolvedConversationTarget:
    source: ResolvedSource
    local_session_id: Optional[UUID] = None
    conversation_id: UUID | None = None
    agent_id: Optional[UUID] = None
    agent_source: Optional[Literal["personal", "shared"]] = None
    external_session_id: Optional[str] = None


def _to_utc_epoch_seconds(value: Any) -> float:
    if isinstance(value, datetime):
        normalized = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return normalized.astimezone(timezone.utc).timestamp()
    if isinstance(value, str):
        try:
            normalized = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return float("-inf")
        if normalized.tzinfo is None:
            normalized = normalized.replace(tzinfo=timezone.utc)
        return normalized.astimezone(timezone.utc).timestamp()
    return float("-inf")


def _session_order_key(item: dict[str, Any]) -> tuple[float, float, str]:
    last_active = _to_utc_epoch_seconds(item.get("last_active_at"))
    created = _to_utc_epoch_seconds(item.get("created_at"))
    conversation_id = str(item.get("conversationId") or "")
    return (last_active, created, conversation_id)


class SessionHubService:
    _LOCAL_SESSION_SOURCES: set[ResolvedSource] = {
        "manual",
        "scheduled",
    }

    async def list_sessions(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        page: int,
        size: int,
        refresh: bool,
        source: Optional[SessionSource],
    ) -> tuple[list[dict[str, Any]], dict[str, Any], bool]:
        local_items: list[dict[str, Any]] = []
        opencode_items: list[dict[str, Any]] = []
        merged_items: list[dict[str, Any]] = []
        opencode_meta: dict[str, Any] = {}
        db_mutated = False

        if source in {None, "manual", "scheduled"}:
            local_items = await self._list_local_sessions(
                db, user_id=user_id, source=source
            )

        if source in {None, "opencode"}:
            raw_opencode_items, opencode_meta = await self._list_all_opencode_sessions(
                db,
                user_id=user_id,
                refresh=refresh,
            )
            normalized_lookup_items: list[
                tuple[UUID, Literal["personal", "shared"], str, dict[str, Any]]
            ] = []
            external_session_ids: list[str] = []
            seen_external_session_ids: set[str] = set()
            for item in raw_opencode_items:
                raw_agent_id = item.get("agent_id")
                raw_agent_source = item.get("agent_source")
                raw_session_id = item.get("session_id")
                if (
                    not isinstance(raw_agent_id, UUID)
                    or raw_agent_source not in {"personal", "shared"}
                    or not isinstance(raw_session_id, str)
                    or not raw_session_id.strip()
                ):
                    continue
                normalized_session_id = raw_session_id.strip()
                normalized_lookup_items.append(
                    (raw_agent_id, raw_agent_source, normalized_session_id, item)
                )
                if normalized_session_id in seen_external_session_ids:
                    continue
                seen_external_session_ids.add(normalized_session_id)
                external_session_ids.append(normalized_session_id)

            external_conversation_map = await conversation_identity_service.find_conversation_ids_for_external_batch(
                db,
                user_id=user_id,
                provider="opencode",
                external_session_ids=external_session_ids,
            )

            normalized_opencode_items: list[dict[str, Any]] = []
            for (
                raw_agent_id,
                raw_agent_source,
                normalized_session_id,
                item,
            ) in normalized_lookup_items:
                conversation_id = external_conversation_map.get(normalized_session_id)
                if conversation_id is None:
                    bind_result = await conversation_identity_service.bind_external_session_with_state(
                        db,
                        user_id=user_id,
                        conversation_id=None,
                        provider="opencode",
                        external_session_id=normalized_session_id,
                        agent_id=raw_agent_id,
                        agent_source=raw_agent_source,
                        context_id=(
                            str(item.get("contextId")).strip()
                            if isinstance(item.get("contextId"), str)
                            else None
                        ),
                        title=str(item.get("title") or "Session"),
                        binding_metadata={"provider": "opencode"},
                    )
                    conversation_id = bind_result.conversation_id
                    db_mutated = db_mutated or bind_result.mutated
                    external_conversation_map[normalized_session_id] = conversation_id
                normalized_opencode_items.append(
                    {
                        "conversationId": str(conversation_id),
                        "source": "opencode",
                        "provider": "opencode",
                        "external_session_id": normalized_session_id,
                        "agent_id": raw_agent_id,
                        "agent_source": raw_agent_source,
                        "title": item.get("title") or "Session",
                        "last_active_at": item.get("last_active_at"),
                        "created_at": None,
                    }
                )
            opencode_items = normalized_opencode_items

        local_items.sort(key=_session_order_key, reverse=True)
        opencode_items.sort(key=_session_order_key, reverse=True)
        if source is None:
            merged_items = self._dedup_cross_source_sessions(
                local_items, opencode_items
            )
            total = len(merged_items)
            pages = (total + size - 1) // size if size else 0
            offset = (page - 1) * size
            page_items = merged_items[offset : offset + size]
        elif source in {"manual", "scheduled"}:
            total = len(local_items)
            pages = (total + size - 1) // size if size else 0
            offset = (page - 1) * size
            page_items = local_items[offset : offset + size]
        else:
            total = len(opencode_items)
            pages = (total + size - 1) // size if size else 0
            offset = (page - 1) * size
            page_items = opencode_items[offset : offset + size]

        meta = {
            "opencode_total_agents": int(opencode_meta.get("total_agents") or 0),
            "opencode_refreshed_agents": int(
                opencode_meta.get("refreshed_agents") or 0
            ),
            "opencode_cached_agents": int(opencode_meta.get("cached_agents") or 0),
            "opencode_partial_failures": int(
                opencode_meta.get("partial_failures") or 0
            ),
        }
        pagination = {
            "page": page,
            "size": size,
            "total": total,
            "pages": pages,
        }
        return page_items, {"pagination": pagination, "meta": meta}, db_mutated

    async def _list_local_sessions(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        source: Optional[SessionSource],
    ) -> list[dict[str, Any]]:
        stmt = (
            select(ConversationThread)
            .where(
                and_(
                    ConversationThread.user_id == user_id,
                    ConversationThread.status == ConversationThread.STATUS_ACTIVE,
                    ConversationThread.source.in_(
                        [
                            ConversationThread.SOURCE_MANUAL,
                            ConversationThread.SOURCE_SCHEDULED,
                        ]
                    ),
                )
            )
            .order_by(
                ConversationThread.last_active_at.desc(),
                ConversationThread.created_at.desc(),
            )
        )
        threads = list((await db.execute(stmt)).scalars().all())

        session_ids = [thread.id for thread in threads]
        latest_metadata_map = await self._latest_local_message_metadata_map(
            db, user_id=user_id, local_conversation_ids=session_ids
        )
        binding_conversation_map = await conversation_identity_service.find_conversation_ids_for_local_sessions_batch(
            db,
            user_id=user_id,
            local_session_ids=session_ids,
        )
        binding_locator_map = await conversation_identity_service.find_latest_external_bindings_for_local_sessions_batch(
            db,
            user_id=user_id,
            local_session_ids=session_ids,
        )
        context_ids = [
            context_id
            for context_id in (
                extract_context_id(latest_metadata_map.get(session.id, {}))
                for session in threads
            )
            if isinstance(context_id, str) and context_id
        ]
        context_conversation_map = (
            await conversation_identity_service.find_conversation_ids_for_context_batch(
                db,
                user_id=user_id,
                context_ids=context_ids,
            )
        )
        items: list[dict[str, Any]] = []

        for thread in threads:
            latest_metadata = latest_metadata_map.get(thread.id, {})
            (
                metadata_provider,
                metadata_external_id,
            ) = extract_provider_and_external_session_id(latest_metadata)
            metadata_context_id = extract_context_id(latest_metadata)
            binding_locator = binding_locator_map.get(thread.id)
            if not metadata_provider and binding_locator:
                metadata_provider = binding_locator.provider
            if not metadata_external_id and binding_locator:
                metadata_external_id = binding_locator.external_session_id
            if not metadata_context_id and binding_locator:
                metadata_context_id = binding_locator.context_id
            conversation_id = binding_conversation_map.get(thread.id)
            if conversation_id is None and binding_locator:
                conversation_id = binding_locator.conversation_id
            if conversation_id is None and metadata_context_id:
                conversation_id = context_conversation_map.get(metadata_context_id)

            if thread.source == ConversationThread.SOURCE_MANUAL:
                if source not in {None, "manual"}:
                    continue
                items.append(
                    {
                        "conversationId": str(conversation_id or thread.id),
                        "source": "manual",
                        "agent_id": thread.agent_id,
                        "agent_source": thread.agent_source,
                        "provider": metadata_provider,
                        "external_session_id": metadata_external_id,
                        "context_id": metadata_context_id,
                        "title": thread.title or "Manual Session",
                        "last_active_at": thread.last_active_at,
                        "created_at": thread.created_at,
                    }
                )
                continue

            if thread.source == ConversationThread.SOURCE_SCHEDULED:
                if source not in {None, "scheduled"}:
                    continue
                items.append(
                    {
                        "conversationId": str(conversation_id or thread.id),
                        "source": "scheduled",
                        "agent_id": thread.agent_id,
                        "agent_source": thread.agent_source or "personal",
                        "provider": metadata_provider,
                        "external_session_id": metadata_external_id,
                        "context_id": metadata_context_id,
                        "title": thread.title or "Scheduled Session",
                        "last_active_at": thread.last_active_at,
                        "created_at": thread.created_at,
                    }
                )

        return items

    async def _latest_local_message_metadata_map(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        local_conversation_ids: list[UUID],
    ) -> dict[UUID, Dict[str, Any]]:
        if not local_conversation_ids:
            return {}
        stmt = (
            select(AgentMessage.conversation_id, AgentMessage.message_metadata)
            .where(
                and_(
                    AgentMessage.user_id == user_id,
                    AgentMessage.conversation_id.in_(local_conversation_ids),
                )
            )
            .order_by(
                AgentMessage.conversation_id.asc(),
                AgentMessage.created_at.desc(),
                AgentMessage.id.desc(),
            )
            .distinct(AgentMessage.conversation_id)
        )
        rows = (await db.execute(stmt)).all()
        mapped: dict[UUID, Dict[str, Any]] = {}
        for row in rows:
            conversation_id = row.conversation_id
            if not isinstance(conversation_id, UUID):
                continue
            metadata = (
                dict(row.message_metadata)
                if isinstance(row.message_metadata, dict)
                else {}
            )
            mapped[conversation_id] = metadata
        return mapped

    def _dedup_cross_source_sessions(
        self,
        local_items: list[dict[str, Any]],
        opencode_items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        merged = list(opencode_items)
        provider_key = normalize_provider("opencode")
        remote_conversation_ids = {
            str(item.get("conversationId"))
            for item in opencode_items
            if isinstance(item.get("conversationId"), str)
            and item.get("conversationId")
        }
        remote_external_keys: set[tuple[str, str]] = set()
        remote_agent_external_keys: set[tuple[str, str]] = set()
        remote_external_ids: set[str] = set()
        remote_by_external_id: dict[str, dict[str, Any]] = {}
        for item in opencode_items:
            remote_external_id = normalize_non_empty_text(
                item.get("external_session_id")
            )
            if not remote_external_id:
                continue
            remote_external_ids.add(remote_external_id)
            if provider_key:
                remote_external_keys.add((provider_key, remote_external_id))
            raw_agent_id = item.get("agent_id")
            if isinstance(raw_agent_id, UUID):
                remote_agent_external_keys.add((str(raw_agent_id), remote_external_id))
            remote_by_external_id.setdefault(remote_external_id, item)

        for local_item in local_items:
            local_conversation_id = local_item.get("conversationId")
            if (
                isinstance(local_conversation_id, str)
                and local_conversation_id
                and local_conversation_id in remote_conversation_ids
            ):
                continue

            local_external_id = normalize_non_empty_text(
                local_item.get("external_session_id")
            )
            local_provider = normalize_provider(local_item.get("provider"))
            local_agent_id = local_item.get("agent_id")
            local_context_id = normalize_non_empty_text(local_item.get("context_id"))

            matched_remote: dict[str, Any] | None = None
            if (
                local_provider
                and local_external_id
                and (local_provider, local_external_id) in remote_external_keys
            ):
                matched_remote = remote_by_external_id.get(local_external_id)
            elif (
                isinstance(local_agent_id, UUID)
                and local_external_id
                and (str(local_agent_id), local_external_id)
                in remote_agent_external_keys
            ):
                matched_remote = remote_by_external_id.get(local_external_id)
            elif local_context_id and local_context_id in remote_external_ids:
                matched_remote = remote_by_external_id.get(local_context_id)

            if matched_remote is not None:
                if (
                    not matched_remote.get("conversationId")
                    and isinstance(local_conversation_id, str)
                    and local_conversation_id
                ):
                    matched_remote["conversationId"] = local_conversation_id
                continue

            merged.append(local_item)

        merged.sort(key=_session_order_key, reverse=True)
        return merged

    async def list_messages(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: str,
        page: int,
        size: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any], bool]:
        db_mutated = False
        resolved_conversation_id = _parse_conversation_id(conversation_id)
        target = await self._resolve_conversation_target(
            db,
            user_id=user_id,
            conversation_id=resolved_conversation_id,
        )
        if target is None:
            pagination = {
                "page": page,
                "size": size,
                "total": 0,
                "pages": 0,
            }
            meta = {
                "conversationId": str(resolved_conversation_id),
                "source": "manual",
            }
            return [], {"pagination": pagination, "meta": meta}, False

        if target.source in {"manual", "scheduled"}:
            assert target.local_session_id is not None
            try:
                session = await self._get_local_session(
                    db,
                    user_id=user_id,
                    local_session_id=target.local_session_id,
                    source=target.source,
                )
            except ValueError as exc:
                if target.source != "manual" or str(exc) != "session_not_found":
                    raise
                pagination = {
                    "page": page,
                    "size": size,
                    "total": 0,
                    "pages": 0,
                }
                meta = {
                    "conversationId": str(resolved_conversation_id),
                    "source": target.source,
                }
                return [], {"pagination": pagination, "meta": meta}, False
            latest_metadata_map = await self._latest_local_message_metadata_map(
                db,
                user_id=user_id,
                local_conversation_ids=[session.id],
            )
            latest_metadata = latest_metadata_map.get(session.id, {})
            (
                provider,
                external_session_id,
            ) = extract_provider_and_external_session_id(latest_metadata)
            context_id = extract_context_id(latest_metadata)
            binding_locator = await conversation_identity_service.find_latest_external_binding_for_local_session(
                db,
                user_id=user_id,
                local_session_id=session.id,
            )
            if not provider and binding_locator:
                provider = binding_locator.provider
            if not external_session_id and binding_locator:
                external_session_id = binding_locator.external_session_id
            if not context_id and binding_locator:
                context_id = binding_locator.context_id
            conversation_id = await conversation_identity_service.find_conversation_id_for_local_session(
                db,
                user_id=user_id,
                local_session_id=session.id,
            )
            if conversation_id is None and binding_locator:
                conversation_id = binding_locator.conversation_id
            if conversation_id is None and provider and external_session_id:
                conversation_id = await conversation_identity_service.find_conversation_id_for_external(
                    db,
                    user_id=user_id,
                    provider=provider,
                    external_session_id=external_session_id,
                )
            if conversation_id is None and context_id:
                conversation_id = await conversation_identity_service.find_conversation_id_for_context(
                    db,
                    user_id=user_id,
                    context_id=context_id,
                    provider=provider,
                )
            offset = (page - 1) * size
            messages = await agent_message_handler.list_agent_messages(
                db,
                user_id=user_id,
                limit=size,
                offset=offset,
                conversation_id=resolved_conversation_id,
            )
            total = await agent_message_handler.count_agent_messages(
                db,
                user_id=user_id,
                conversation_id=resolved_conversation_id,
            )
            pages = (total + size - 1) // size if size else 0
            items: list[dict[str, Any]] = []
            for message in messages:
                message_metadata = dict(
                    getattr(message, "message_metadata", None) or {}
                )
                message_metadata.setdefault("local_message_id", str(message.id))
                items.append(
                    {
                        "id": _resolve_local_message_item_id(message, message_metadata),
                        "role": _sender_to_role(getattr(message, "sender", "")),
                        "content": message.content or "",
                        "created_at": message.created_at,
                        "metadata": message_metadata,
                    }
                )
            meta = {
                "conversationId": str(resolved_conversation_id),
                "source": target.source,
            }
            pagination = {
                "page": page,
                "size": size,
                "total": int(total),
                "pages": pages,
            }
            return items, {"pagination": pagination, "meta": meta}, db_mutated

        assert target.source == "opencode"
        assert target.agent_id is not None
        assert target.agent_source in {"personal", "shared"}
        assert target.external_session_id is not None

        try:
            try:
                runtime = await self._build_runtime(
                    db,
                    user_id=user_id,
                    agent_source=target.agent_source,
                    agent_id=target.agent_id,
                )
            except (A2ARuntimeNotFoundError, HubA2ARuntimeNotFoundError) as exc:
                raise ValueError("session_not_found") from exc
            except (A2ARuntimeValidationError, HubA2ARuntimeValidationError) as exc:
                raise ValueError("runtime_invalid") from exc
            result = await get_a2a_extensions_service().opencode_get_session_messages(
                runtime=runtime,
                session_id=target.external_session_id,
                page=page,
                size=size,
                query=None,
            )
        except A2AExtensionUpstreamError as exc:
            raise ValueError(exc.error_code or "upstream_error") from exc

        if not result.success:
            raise ValueError(result.error_code or "upstream_error")

        envelope = result.result if isinstance(result.result, dict) else {}
        raw_items = (
            envelope.get("items") if isinstance(envelope.get("items"), list) else []
        )
        items = [
            _map_opencode_message(item, index) for index, item in enumerate(raw_items)
        ]

        pagination_raw = (
            envelope.get("pagination")
            if isinstance(envelope.get("pagination"), dict)
            else {}
        )
        total = int(pagination_raw.get("total") or len(items))
        pages = int(
            pagination_raw.get("pages") or ((total + size - 1) // size if size else 0)
        )
        conversation_id = (
            await conversation_identity_service.find_conversation_id_for_external(
                db,
                user_id=user_id,
                provider="opencode",
                external_session_id=target.external_session_id,
            )
        )
        meta = {
            "conversationId": str(conversation_id or resolved_conversation_id),
            "source": "opencode",
            "agent_id": str(target.agent_id),
            "agent_source": target.agent_source,
            "upstream_session_id": target.external_session_id,
        }
        pagination = {
            "page": int(pagination_raw.get("page") or page),
            "size": int(pagination_raw.get("size") or size),
            "total": total,
            "pages": pages,
        }
        return items, {"pagination": pagination, "meta": meta}, False

    async def continue_session(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: str,
    ) -> tuple[dict[str, Any], bool]:
        resolved_conversation_id = _parse_conversation_id(conversation_id)
        target = await self._resolve_conversation_target(
            db,
            user_id=user_id,
            conversation_id=resolved_conversation_id,
        )
        if target is None:
            return (
                _build_continue_response(
                    conversation_id=resolved_conversation_id,
                    source="manual",
                    provider=None,
                    external_session_id=None,
                    context_id=None,
                    metadata={},
                ),
                False,
            )

        if target.source == "opencode":
            assert target.agent_id is not None
            assert target.agent_source in {"personal", "shared"}
            assert target.external_session_id is not None

            try:
                runtime = await self._build_runtime(
                    db,
                    user_id=user_id,
                    agent_source=target.agent_source,
                    agent_id=target.agent_id,
                )
            except (A2ARuntimeNotFoundError, HubA2ARuntimeNotFoundError) as exc:
                raise ValueError("session_not_found") from exc
            except (A2ARuntimeValidationError, HubA2ARuntimeValidationError) as exc:
                raise ValueError("runtime_invalid") from exc

            try:
                result = await get_a2a_extensions_service().opencode_continue_session(
                    runtime=runtime,
                    session_id=target.external_session_id,
                )
            except A2AExtensionUpstreamError as exc:
                raise ValueError(exc.error_code or "upstream_error") from exc
            if not result.success:
                raise ValueError(result.error_code or "upstream_error")
            payload = result.result if isinstance(result.result, dict) else {}
            context_id = extract_context_id(payload)
            metadata = (
                payload.get("metadata")
                if isinstance(payload.get("metadata"), dict)
                else {}
            )
            (
                provider_from_payload,
                external_from_payload,
            ) = extract_provider_and_external_session_id(
                payload,
            )
            (
                provider,
                external_session_id,
            ) = extract_provider_and_external_session_id(metadata)
            resolved_provider = normalize_provider(
                provider_from_payload or provider or "opencode"
            )
            resolved_external_session_id = (
                external_from_payload
                or external_session_id
                or target.external_session_id
            )
            continue_metadata = _build_continue_invoke_metadata(
                provider=resolved_provider,
                external_session_id=resolved_external_session_id,
            )
            bind_result = (
                await conversation_identity_service.bind_external_session_with_state(
                    db,
                    user_id=user_id,
                    conversation_id=resolved_conversation_id,
                    provider=resolved_provider,
                    agent_id=target.agent_id,
                    agent_source=target.agent_source,
                    external_session_id=resolved_external_session_id,
                    context_id=context_id if isinstance(context_id, str) else None,
                    title="Session",
                    binding_metadata={
                        "provider": resolved_provider,
                        "external_session_id": resolved_external_session_id,
                    },
                )
            )
            return (
                _build_continue_response(
                    conversation_id=bind_result.conversation_id,
                    source="opencode",
                    provider=resolved_provider,
                    external_session_id=resolved_external_session_id,
                    context_id=context_id if isinstance(context_id, str) else None,
                    metadata=continue_metadata,
                ),
                bind_result.mutated,
            )

        assert target.local_session_id is not None
        try:
            session = await self._get_local_session(
                db,
                user_id=user_id,
                local_session_id=target.local_session_id,
                source=target.source,
            )
        except ValueError as exc:
            if target.source != "manual" or str(exc) != "session_not_found":
                raise
            return (
                _build_continue_response(
                    conversation_id=resolved_conversation_id,
                    source="manual",
                    provider=None,
                    external_session_id=None,
                    context_id=None,
                    metadata={},
                ),
                False,
            )
        latest_stmt = (
            select(AgentMessage)
            .where(
                and_(
                    AgentMessage.user_id == user_id,
                    AgentMessage.conversation_id == session.id,
                )
            )
            .order_by(AgentMessage.created_at.desc(), AgentMessage.id.desc())
            .limit(1)
        )
        latest = await db.scalar(latest_stmt)
        metadata_raw = getattr(latest, "message_metadata", None) if latest else None
        metadata = dict(metadata_raw) if isinstance(metadata_raw, dict) else {}
        context_id = extract_context_id(metadata)
        provider, external_session_id = extract_provider_and_external_session_id(
            metadata
        )
        binding_locator = await conversation_identity_service.find_latest_external_binding_for_local_session(
            db,
            user_id=user_id,
            local_session_id=session.id,
        )
        if not provider and binding_locator:
            provider = binding_locator.provider
        if not external_session_id and binding_locator:
            external_session_id = binding_locator.external_session_id
        if not isinstance(context_id, str) and binding_locator:
            context_id = binding_locator.context_id
        conversation_id = session.id
        db_mutated = False
        if provider and external_session_id:
            bind_result = (
                await conversation_identity_service.bind_external_session_with_state(
                    db,
                    user_id=user_id,
                    conversation_id=conversation_id or resolved_conversation_id,
                    provider=provider,
                    external_session_id=external_session_id,
                    agent_id=(
                        binding_locator.agent_id
                        if binding_locator
                        and isinstance(binding_locator.agent_id, UUID)
                        else session.agent_id
                    ),
                    agent_source=(
                        binding_locator.agent_source
                        if binding_locator
                        and binding_locator.agent_source in {"personal", "shared"}
                        else "personal"
                    ),
                    context_id=context_id if isinstance(context_id, str) else None,
                    title=session.title or "Session",
                    binding_metadata=metadata,
                    local_session_id=session.id,
                )
            )
            conversation_id = bind_result.conversation_id
            db_mutated = bind_result.mutated
        resolved_provider = normalize_provider(provider)
        resolved_external_session_id = normalize_non_empty_text(external_session_id)
        continue_metadata = _build_continue_invoke_metadata(
            provider=resolved_provider,
            external_session_id=resolved_external_session_id,
        )
        return (
            _build_continue_response(
                conversation_id=conversation_id or resolved_conversation_id,
                source=target.source,
                provider=resolved_provider,
                external_session_id=resolved_external_session_id,
                context_id=context_id if isinstance(context_id, str) else None,
                metadata=continue_metadata,
            ),
            db_mutated,
        )

    async def ensure_local_session_for_invoke(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        agent_id: UUID,
        agent_source: Literal["personal", "shared"],
        conversation_id: Optional[str],
    ) -> tuple[Optional[ConversationThread], Optional[SessionSource]]:
        if not conversation_id:
            return None, None
        try:
            normalized_conversation_id = _parse_conversation_id(conversation_id)
        except ValueError as exc:
            raise ValueError("invalid_conversation_id") from exc

        target = await self._resolve_conversation_target(
            db,
            user_id=user_id,
            conversation_id=normalized_conversation_id,
        )
        if target and target.source == "opencode":
            return None, None

        local_session_id = (
            target.local_session_id
            if target and isinstance(target.local_session_id, UUID)
            else normalized_conversation_id
        )

        session = await db.scalar(
            select(ConversationThread).where(
                and_(
                    ConversationThread.id == local_session_id,
                    ConversationThread.user_id == user_id,
                    ConversationThread.status == ConversationThread.STATUS_ACTIVE,
                )
            )
        )

        if session is None:
            existing_session_id = await db.scalar(
                select(ConversationThread.id).where(
                    ConversationThread.id == local_session_id
                )
            )
            if existing_session_id is not None:
                raise ValueError("invalid_conversation_id")
            session = ConversationThread(
                id=local_session_id,
                user_id=user_id,
                source=ConversationThread.SOURCE_MANUAL,
                agent_id=agent_id,
                agent_source=agent_source,
                title=f"Manual Session {str(local_session_id)[:8]}",
                last_active_at=utc_now(),
                status=ConversationThread.STATUS_ACTIVE,
            )
            db.add(session)
            try:
                await db.flush()
            except IntegrityError as exc:
                await db.rollback()
                raise ValueError("invalid_conversation_id") from exc

        local_source: SessionSource
        if session.source == ConversationThread.SOURCE_MANUAL:
            local_source = "manual"
        elif session.source == ConversationThread.SOURCE_SCHEDULED:
            local_source = "scheduled"
        else:
            raise ValueError("invalid_conversation_id")

        session.agent_id = agent_id
        session.agent_source = agent_source
        session.last_active_at = utc_now()
        if local_source == "manual":
            await self._ensure_local_conversation_thread(
                db,
                user_id=user_id,
                conversation_id=session.id,
                agent_id=agent_id,
                agent_source=agent_source,
                title=session.title or "Session",
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
        agent_source: Literal["personal", "shared"],
        query: str,
        response_content: str,
        success: bool,
        context_id: Optional[str],
        user_message_id: Optional[str] = None,
        client_agent_message_id: Optional[str] = None,
        invoke_metadata: Optional[Dict[str, Any]] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
        response_metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        metadata: Dict[str, Any] = {
            "source": source,
            "agent_id": str(agent_id),
            "conversation_id": str(session.id),
            "success": success,
        }
        (
            provider_from_invoke,
            external_session_id,
        ) = extract_provider_and_external_session_id(invoke_metadata or {})
        if context_id and isinstance(context_id, str):
            metadata["context_id"] = context_id
        if provider_from_invoke:
            metadata["provider"] = provider_from_invoke
        if external_session_id:
            metadata["external_session_id"] = external_session_id
        if extra_metadata:
            metadata.update(extra_metadata)
        normalized_user_message_id = normalize_non_empty_text(user_message_id)
        normalized_client_agent_message_id = normalize_non_empty_text(
            client_agent_message_id
        )
        if normalized_user_message_id:
            metadata["client_message_id"] = normalized_user_message_id

        conversation_id: UUID | None = session.id
        if source == "manual":
            await self._ensure_local_conversation_thread(
                db,
                user_id=user_id,
                conversation_id=session.id,
                agent_id=agent_id,
                agent_source=agent_source,
                title=session.title or "Session",
                source="manual",
            )
        if provider_from_invoke and external_session_id:
            conversation_id = await conversation_identity_service.bind_external_session(
                db,
                user_id=user_id,
                conversation_id=conversation_id,
                provider=provider_from_invoke,
                external_session_id=external_session_id,
                agent_id=agent_id,
                agent_source=agent_source,
                context_id=context_id if isinstance(context_id, str) else None,
                title=session.title or "Session",
                binding_metadata=invoke_metadata,
                local_session_id=session.id,
            )
        elif context_id and isinstance(context_id, str):
            conversation_id = (
                await conversation_identity_service.find_conversation_id_for_context(
                    db,
                    user_id=user_id,
                    context_id=context_id,
                    provider=provider_from_invoke,
                )
            )

        await agent_message_handler.create_agent_message(
            db,
            user_id=user_id,
            content=query,
            sender="user",
            conversation_id=conversation_id,
            metadata=metadata,
        )
        agent_metadata = dict(metadata)
        if normalized_client_agent_message_id:
            agent_metadata["client_message_id"] = normalized_client_agent_message_id
        if response_metadata:
            for key, value in response_metadata.items():
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
        await agent_message_handler.create_agent_message(
            db,
            user_id=user_id,
            content=response_content,
            sender="agent",
            conversation_id=conversation_id,
            metadata=agent_metadata,
        )
        session.last_active_at = utc_now()

    async def _build_runtime(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        agent_source: Literal["personal", "shared"],
        agent_id: UUID,
    ):
        if agent_source == "shared":
            return await hub_a2a_runtime_builder.build(
                db, user_id=user_id, agent_id=agent_id
            )
        return await a2a_runtime_builder.build(db, user_id=user_id, agent_id=agent_id)

    async def _get_local_session(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        local_session_id: UUID,
        source: Literal["manual", "scheduled"],
    ) -> ConversationThread:
        expected_source = (
            ConversationThread.SOURCE_MANUAL
            if source == "manual"
            else ConversationThread.SOURCE_SCHEDULED
        )
        session = await db.scalar(
            select(ConversationThread).where(
                and_(
                    ConversationThread.id == local_session_id,
                    ConversationThread.user_id == user_id,
                    ConversationThread.status == ConversationThread.STATUS_ACTIVE,
                    ConversationThread.source == expected_source,
                )
            )
        )
        if session is None:
            raise ValueError("session_not_found")
        return session

    async def _get_local_session_by_id(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        local_session_id: UUID,
    ) -> ConversationThread | None:
        return await db.scalar(
            select(ConversationThread).where(
                and_(
                    ConversationThread.id == local_session_id,
                    ConversationThread.user_id == user_id,
                    ConversationThread.status == ConversationThread.STATUS_ACTIVE,
                    ConversationThread.source.in_(
                        [
                            ConversationThread.SOURCE_MANUAL,
                            ConversationThread.SOURCE_SCHEDULED,
                        ]
                    ),
                )
            )
        )

    async def _resolve_conversation_target(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: UUID,
    ) -> ResolvedConversationTarget | None:
        binding_locator = await conversation_identity_service.find_latest_external_binding_for_conversation(
            db,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        if (
            binding_locator
            and normalize_provider(binding_locator.provider) == "opencode"
            and isinstance(binding_locator.agent_id, UUID)
            and binding_locator.agent_source in {"personal", "shared"}
            and isinstance(binding_locator.external_session_id, str)
            and binding_locator.external_session_id
        ):
            return ResolvedConversationTarget(
                source="opencode",
                conversation_id=conversation_id,
                local_session_id=(
                    binding_locator.local_session_id
                    if isinstance(binding_locator.local_session_id, UUID)
                    else None
                ),
                agent_id=binding_locator.agent_id,
                agent_source=binding_locator.agent_source,  # type: ignore[arg-type]
                external_session_id=binding_locator.external_session_id,
            )

        local_session_id = (
            binding_locator.local_session_id
            if binding_locator and isinstance(binding_locator.local_session_id, UUID)
            else conversation_id
        )
        local_session = await self._get_local_session_by_id(
            db,
            user_id=user_id,
            local_session_id=local_session_id,
        )
        if local_session is None:
            return None
        if local_session.source == ConversationThread.SOURCE_MANUAL:
            return ResolvedConversationTarget(
                source="manual",
                local_session_id=local_session.id,
                conversation_id=conversation_id,
            )
        if local_session.source == ConversationThread.SOURCE_SCHEDULED:
            return ResolvedConversationTarget(
                source="scheduled",
                local_session_id=local_session.id,
                conversation_id=conversation_id,
            )
        return None

    async def _ensure_local_conversation_thread(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: UUID,
        agent_id: Optional[UUID],
        agent_source: Optional[Literal["personal", "shared"]],
        title: str,
        source: Literal["manual", "scheduled"],
    ) -> bool:
        existing = await db.scalar(
            select(ConversationThread).where(
                and_(
                    ConversationThread.id == conversation_id,
                    ConversationThread.user_id == user_id,
                )
            )
        )
        if existing:
            mutated = False
            if agent_id and existing.agent_id != agent_id:
                existing.agent_id = agent_id
                mutated = True
            if agent_source and existing.agent_source != agent_source:
                existing.agent_source = agent_source
                mutated = True
            if title and existing.title != title:
                existing.title = title
                mutated = True
            expected_source = (
                ConversationThread.SOURCE_MANUAL
                if source == "manual"
                else ConversationThread.SOURCE_SCHEDULED
            )
            if existing.source != expected_source:
                existing.source = expected_source
                mutated = True
            existing.last_active_at = utc_now()
            return mutated

        db.add(
            ConversationThread(
                id=conversation_id,
                user_id=user_id,
                agent_id=agent_id,
                agent_source=agent_source,
                source=(
                    ConversationThread.SOURCE_MANUAL
                    if source == "manual"
                    else ConversationThread.SOURCE_SCHEDULED
                ),
                title=title or "Session",
                last_active_at=utc_now(),
                status=ConversationThread.STATUS_ACTIVE,
            )
        )
        await db.flush()
        return True

    async def _list_all_opencode_sessions(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        refresh: bool,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        items, extra = await opencode_session_directory_service.list_directory_all(
            db,
            user_id=user_id,
            refresh=refresh,
        )
        meta = dict(extra.get("meta") or {}) if isinstance(extra, dict) else {}
        return items, meta


def _parse_conversation_id(value: str) -> UUID:
    trimmed = (value or "").strip()
    if not trimmed:
        raise ValueError("conversation_id is required")
    try:
        return UUID(trimmed)
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid_conversation_id") from exc


def _build_continue_response(
    *,
    conversation_id: UUID,
    source: ResolvedSource,
    provider: Optional[str],
    external_session_id: Optional[str],
    context_id: Optional[str],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return {
        "conversationId": str(conversation_id),
        "source": source,
        "provider": provider,
        "externalSessionId": external_session_id,
        "contextId": context_id,
        "metadata": metadata,
    }


def _build_continue_invoke_metadata(
    *,
    provider: str | None,
    external_session_id: str | None,
) -> dict[str, Any]:
    if normalize_provider(provider) == "opencode" and isinstance(
        external_session_id, str
    ):
        normalized = external_session_id.strip()
        if normalized:
            # Upstream opencode-a2a-serve contract requires this key explicitly.
            return {"opencode_session_id": normalized}
    return {}


def _sender_to_role(sender: str) -> str:
    normalized = (sender or "").strip().lower()
    if normalized in {"user", "automation"}:
        return "user"
    if normalized == "agent":
        return "agent"
    return "system"


def _resolve_local_message_item_id(
    message: AgentMessage, metadata: dict[str, Any]
) -> str:
    role = _sender_to_role(getattr(message, "sender", ""))
    if role == "agent":
        upstream_message_id = normalize_non_empty_text(
            metadata.get("upstream_message_id")
            or metadata.get("message_id")
            or metadata.get("messageId")
        )
        if upstream_message_id:
            return upstream_message_id
    if role in {"user", "agent"}:
        client_message_id = normalize_non_empty_text(
            metadata.get("client_message_id")
            or metadata.get("clientMessageId")
            or metadata.get("request_message_id")
            or metadata.get("requestMessageId")
        )
        if client_message_id:
            return client_message_id
    return str(message.id)


def _map_opencode_message(item: Any, index: int) -> Dict[str, Any]:
    obj = as_dict(item)
    message_id = str(
        obj.get("id")
        or obj.get("message_id")
        or obj.get("messageId")
        or f"opencode-{index}"
    )

    role = _map_role(
        pick_first_non_empty_str(obj, ["role", "type", "sender"])
        or pick_first_non_empty_str(
            as_dict(
                as_dict(
                    as_dict(as_dict(obj.get("metadata")).get("opencode")).get("raw")
                ).get("info")
            ),
            ["role"],
        )
    )

    content = _extract_content(obj)
    created_at = _extract_timestamp(obj)

    return {
        "id": message_id,
        "role": role,
        "content": content,
        "created_at": created_at,
        "metadata": {"raw": item},
    }


def _map_role(raw: Optional[str]) -> str:
    normalized = (raw or "").strip().lower()
    if normalized in {"assistant", "agent"}:
        return "agent"
    if normalized in {"user", "human", "automation"}:
        return "user"
    return "system"


def _extract_content(obj: Dict[str, Any]) -> str:
    direct = pick_first_non_empty_str(obj, ["text", "content", "message"])
    if direct:
        return direct

    if obj.get("kind") == "message":
        parts = obj.get("parts") if isinstance(obj.get("parts"), list) else []
        collected: list[str] = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            kind = str(part.get("kind") or part.get("type") or "")
            text = part.get("text")
            if kind == "text" and isinstance(text, str) and text:
                collected.append(text)
        if collected:
            return "".join(collected)

    return json.dumps(obj, ensure_ascii=False)[:1200]


def _extract_timestamp(obj: Dict[str, Any]) -> datetime:
    direct = pick_first_non_empty_str(
        obj, ["created_at", "createdAt", "timestamp", "ts"]
    )
    if direct:
        try:
            return datetime.fromisoformat(direct.replace("Z", "+00:00")).astimezone(
                timezone.utc
            )
        except ValueError:
            pass

    ms = None
    for key in ["created", "updated"]:
        value = obj.get(key)
        if isinstance(value, int):
            ms = value
            break
        if isinstance(value, float) and value.is_integer():
            ms = int(value)
            break

    if isinstance(ms, int):
        try:
            return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            pass

    return utc_now()


session_hub_service = SessionHubService()

__all__ = [
    "ResolvedConversationTarget",
    "SessionHubService",
    "SessionSource",
    "session_hub_service",
]
