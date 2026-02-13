"""Unified session domain helpers and query service.

This module provides a single read model for session list/history/continue across:
- local manual chat sessions
- local scheduled sessions
- remote OpenCode sessions (via extension adapters)
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.a2a_schedule_execution import A2AScheduleExecution
from app.db.models.a2a_schedule_task import A2AScheduleTask
from app.db.models.agent_message import AgentMessage
from app.db.models.agent_session import AgentSession
from app.handlers import agent_message as agent_message_handler
from app.integrations.a2a_extensions import get_a2a_extensions_service
from app.integrations.a2a_extensions.errors import A2AExtensionUpstreamError
from app.services.a2a_runtime import (
    A2ARuntimeNotFoundError,
    A2ARuntimeValidationError,
    a2a_runtime_builder,
)
from app.services.hub_a2a_runtime import (
    HubA2ARuntimeNotFoundError,
    HubA2ARuntimeValidationError,
    hub_a2a_runtime_builder,
)
from app.services.opencode_session_directory import opencode_session_directory_service
from app.utils.timezone_util import utc_now

SessionSource = Literal["manual", "scheduled", "opencode"]

_MANUAL_PREFIX = "manual:"
_SCHEDULED_PREFIX = "scheduled:"
_OPENCODE_PREFIX = "opencode:"


@dataclass(frozen=True)
class ParsedSessionKey:
    source: SessionSource
    local_session_id: Optional[UUID] = None
    agent_id: Optional[UUID] = None
    agent_source: Optional[Literal["personal", "shared"]] = None
    upstream_session_id: Optional[str] = None


def _urlsafe_b64encode_json(data: Dict[str, Any]) -> str:
    raw = json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _urlsafe_b64decode_json(value: str) -> Dict[str, Any]:
    padded = value + "=" * (-len(value) % 4)
    raw = base64.urlsafe_b64decode(padded.encode("ascii"))
    decoded = json.loads(raw.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("invalid payload")
    return decoded


def build_manual_session_key(session_id: UUID) -> str:
    return f"{_MANUAL_PREFIX}{session_id}"


def build_scheduled_session_key(session_id: UUID) -> str:
    return f"{_SCHEDULED_PREFIX}{session_id}"


def build_opencode_session_key(
    *,
    agent_id: UUID,
    agent_source: Literal["personal", "shared"],
    upstream_session_id: str,
) -> str:
    token = _urlsafe_b64encode_json(
        {
            "agent_id": str(agent_id),
            "agent_source": agent_source,
            "session_id": upstream_session_id,
        }
    )
    return f"{_OPENCODE_PREFIX}{token}"


def parse_session_key(value: str) -> ParsedSessionKey:
    trimmed = (value or "").strip()
    if not trimmed:
        raise ValueError("session_id is required")

    if trimmed.startswith(_MANUAL_PREFIX):
        raw_uuid = trimmed[len(_MANUAL_PREFIX) :]
        return ParsedSessionKey(source="manual", local_session_id=UUID(raw_uuid))

    if trimmed.startswith(_SCHEDULED_PREFIX):
        raw_uuid = trimmed[len(_SCHEDULED_PREFIX) :]
        return ParsedSessionKey(source="scheduled", local_session_id=UUID(raw_uuid))

    if trimmed.startswith(_OPENCODE_PREFIX):
        token = trimmed[len(_OPENCODE_PREFIX) :]
        payload = _urlsafe_b64decode_json(token)
        raw_agent_id = str(payload.get("agent_id") or "").strip()
        raw_agent_source = str(payload.get("agent_source") or "").strip()
        raw_session_id = str(payload.get("session_id") or "").strip()
        if not raw_agent_id or raw_agent_source not in {"personal", "shared"}:
            raise ValueError("invalid opencode session key")
        if not raw_session_id:
            raise ValueError("invalid opencode session key")
        return ParsedSessionKey(
            source="opencode",
            agent_id=UUID(raw_agent_id),
            agent_source=raw_agent_source,  # type: ignore[arg-type]
            upstream_session_id=raw_session_id,
        )

    # Fail fast: one-shot migration expects all clients to use unified keys.
    raise ValueError("invalid unified session id")


class SessionHubService:
    _LOCAL_SESSION_SOURCES: set[SessionSource] = {"manual", "scheduled"}

    async def list_sessions(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        page: int,
        size: int,
        refresh: bool,
        source: Optional[SessionSource],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        items: list[dict[str, Any]] = []
        opencode_meta: dict[str, Any] = {}

        if source in {None, "manual", "scheduled"}:
            items.extend(
                await self._list_local_sessions(db, user_id=user_id, source=source)
            )

        if source in {None, "opencode"}:
            opencode_items, opencode_meta = await self._list_all_opencode_sessions(
                db,
                user_id=user_id,
                size=size,
                refresh=refresh,
            )
            for item in opencode_items:
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
                items.append(
                    {
                        "id": build_opencode_session_key(
                            agent_id=raw_agent_id,
                            agent_source=raw_agent_source,
                            upstream_session_id=raw_session_id.strip(),
                        ),
                        "source": "opencode",
                        "source_session_id": raw_session_id.strip(),
                        "agent_id": raw_agent_id,
                        "agent_source": raw_agent_source,
                        "title": item.get("title") or "Session",
                        "last_active_at": item.get("last_active_at"),
                        "created_at": None,
                    }
                )

        items.sort(
            key=lambda item: (
                str(item.get("last_active_at") or ""),
                str(item.get("created_at") or ""),
                str(item.get("id") or ""),
            ),
            reverse=True,
        )

        total = len(items)
        pages = (total + size - 1) // size if size else 0
        offset = (page - 1) * size
        page_items = items[offset : offset + size]

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
        return page_items, {"pagination": pagination, "meta": meta}

    async def _list_local_sessions(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        source: Optional[SessionSource],
    ) -> list[dict[str, Any]]:
        stmt = (
            select(AgentSession)
            .where(
                and_(
                    AgentSession.user_id == user_id,
                    AgentSession.deleted_at.is_(None),
                    AgentSession.session_type.in_(
                        [AgentSession.TYPE_CHAT, AgentSession.TYPE_SCHEDULED]
                    ),
                )
            )
            .order_by(
                AgentSession.last_activity_at.desc(), AgentSession.created_at.desc()
            )
        )
        sessions = list((await db.execute(stmt)).scalars().all())

        scheduled_agent_map = await self._scheduled_session_agent_map(
            db, user_id=user_id
        )
        items: list[dict[str, Any]] = []

        for session in sessions:
            if session.session_type == AgentSession.TYPE_CHAT:
                if source not in {None, "manual"}:
                    continue
                agent_id: UUID | None = None
                if isinstance(session.module_key, str):
                    try:
                        agent_id = UUID(session.module_key.strip())
                    except (ValueError, TypeError):
                        agent_id = None
                items.append(
                    {
                        "id": build_manual_session_key(session.id),
                        "source": "manual",
                        "source_session_id": str(session.id),
                        "agent_id": agent_id,
                        "agent_source": None,
                        "title": session.name or "Manual Session",
                        "last_active_at": session.last_activity_at,
                        "created_at": session.created_at,
                    }
                )
                continue

            if session.session_type == AgentSession.TYPE_SCHEDULED:
                if source not in {None, "scheduled"}:
                    continue
                scheduled_meta = scheduled_agent_map.get(session.id, {})
                items.append(
                    {
                        "id": build_scheduled_session_key(session.id),
                        "source": "scheduled",
                        "source_session_id": str(session.id),
                        "agent_id": scheduled_meta.get("agent_id"),
                        "agent_source": "personal",
                        "title": session.name or "Scheduled Session",
                        "last_active_at": session.last_activity_at,
                        "created_at": session.created_at,
                    }
                )

        return items

    async def _scheduled_session_agent_map(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
    ) -> dict[UUID, dict[str, Any]]:
        latest_exec_key = (
            select(
                A2AScheduleExecution.session_id.label("session_id"),
                func.max(A2AScheduleExecution.created_at).label("max_created_at"),
            )
            .where(
                and_(
                    A2AScheduleExecution.user_id == user_id,
                    A2AScheduleExecution.session_id.is_not(None),
                )
            )
            .group_by(A2AScheduleExecution.session_id)
            .subquery()
        )
        latest_exec = A2AScheduleExecution.__table__.alias("latest_exec")
        stmt = (
            select(
                latest_exec.c.session_id.label("session_id"),
                latest_exec.c.task_id.label("task_id"),
                A2AScheduleTask.agent_id.label("agent_id"),
                latest_exec.c.id.label("run_id"),
            )
            .join(
                latest_exec_key,
                and_(
                    latest_exec.c.session_id == latest_exec_key.c.session_id,
                    latest_exec.c.created_at == latest_exec_key.c.max_created_at,
                ),
            )
            .outerjoin(A2AScheduleTask, A2AScheduleTask.id == latest_exec.c.task_id)
        )
        rows = (await db.execute(stmt)).all()
        mapped: dict[UUID, dict[str, Any]] = {}
        for row in rows:
            session_id = row.session_id
            if isinstance(session_id, UUID):
                mapped[session_id] = {
                    "agent_id": row.agent_id,
                    "task_id": row.task_id,
                    "run_id": row.run_id,
                }
        return mapped

    async def list_messages(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        session_key: str,
        page: int,
        size: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        parsed = parse_session_key(session_key)
        if parsed.source in {"manual", "scheduled"}:
            assert parsed.local_session_id is not None
            try:
                session = await self._get_local_session(
                    db,
                    user_id=user_id,
                    local_session_id=parsed.local_session_id,
                    source=parsed.source,
                )
            except ValueError as exc:
                if parsed.source != "manual" or str(exc) != "session_not_found":
                    raise
                pagination = {
                    "page": page,
                    "size": size,
                    "total": 0,
                    "pages": 0,
                }
                meta = {"session_id": session_key, "source": parsed.source}
                return [], {"pagination": pagination, "meta": meta}
            offset = (page - 1) * size
            messages = await agent_message_handler.list_agent_messages(
                db,
                user_id=user_id,
                limit=size,
                offset=offset,
                session_id=session.id,
            )
            total = await agent_message_handler.count_agent_messages(
                db,
                user_id=user_id,
                session_id=session.id,
            )
            pages = (total + size - 1) // size if size else 0
            items = [
                {
                    "id": str(message.id),
                    "role": _sender_to_role(getattr(message, "sender", "")),
                    "content": message.content or "",
                    "created_at": message.created_at,
                    "metadata": dict(getattr(message, "message_metadata", None) or {}),
                }
                for message in messages
            ]
            meta = {
                "session_id": session_key,
                "source": parsed.source,
            }
            pagination = {
                "page": page,
                "size": size,
                "total": int(total),
                "pages": pages,
            }
            return items, {"pagination": pagination, "meta": meta}

        assert parsed.source == "opencode"
        assert parsed.agent_id is not None
        assert parsed.agent_source in {"personal", "shared"}
        assert parsed.upstream_session_id is not None

        runtime = await self._build_runtime(
            db,
            user_id=user_id,
            agent_source=parsed.agent_source,
            agent_id=parsed.agent_id,
        )
        try:
            try:
                runtime = await self._build_runtime(
                    db,
                    user_id=user_id,
                    agent_source=parsed.agent_source,
                    agent_id=parsed.agent_id,
                )
            except (A2ARuntimeNotFoundError, HubA2ARuntimeNotFoundError) as exc:
                raise ValueError("session_not_found") from exc
            except (A2ARuntimeValidationError, HubA2ARuntimeValidationError) as exc:
                raise ValueError("runtime_invalid") from exc
            result = await get_a2a_extensions_service().opencode_get_session_messages(
                runtime=runtime,
                session_id=parsed.upstream_session_id,
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
        meta = {
            "session_id": session_key,
            "source": "opencode",
            "agent_id": str(parsed.agent_id),
            "agent_source": parsed.agent_source,
            "upstream_session_id": parsed.upstream_session_id,
        }
        pagination = {
            "page": int(pagination_raw.get("page") or page),
            "size": int(pagination_raw.get("size") or size),
            "total": total,
            "pages": pages,
        }
        return items, {"pagination": pagination, "meta": meta}

    async def continue_session(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        session_key: str,
    ) -> dict[str, Any]:
        parsed = parse_session_key(session_key)
        if parsed.source == "opencode":
            assert parsed.agent_id is not None
            assert parsed.agent_source in {"personal", "shared"}
            assert parsed.upstream_session_id is not None

            try:
                runtime = await self._build_runtime(
                    db,
                    user_id=user_id,
                    agent_source=parsed.agent_source,
                    agent_id=parsed.agent_id,
                )
            except (A2ARuntimeNotFoundError, HubA2ARuntimeNotFoundError) as exc:
                raise ValueError("session_not_found") from exc
            except (A2ARuntimeValidationError, HubA2ARuntimeValidationError) as exc:
                raise ValueError("runtime_invalid") from exc

            try:
                result = await get_a2a_extensions_service().opencode_continue_session(
                    runtime=runtime,
                    session_id=parsed.upstream_session_id,
                )
            except A2AExtensionUpstreamError as exc:
                raise ValueError(exc.error_code or "upstream_error") from exc
            if not result.success:
                raise ValueError(result.error_code or "upstream_error")
            payload = result.result if isinstance(result.result, dict) else {}
            context_id = payload.get("contextId") or payload.get("context_id")
            metadata = (
                payload.get("metadata")
                if isinstance(payload.get("metadata"), dict)
                else {}
            )
            return {
                "session_id": session_key,
                "source": "opencode",
                "contextId": context_id if isinstance(context_id, str) else None,
                "metadata": metadata,
            }

        assert parsed.local_session_id is not None
        session = await self._get_local_session(
            db,
            user_id=user_id,
            local_session_id=parsed.local_session_id,
            source=parsed.source,
        )
        latest_stmt = (
            select(AgentMessage)
            .where(
                and_(
                    AgentMessage.user_id == user_id,
                    AgentMessage.session_id == session.id,
                )
            )
            .order_by(AgentMessage.created_at.desc(), AgentMessage.id.desc())
            .limit(1)
        )
        latest = await db.scalar(latest_stmt)
        metadata_raw = getattr(latest, "message_metadata", None) if latest else None
        metadata = dict(metadata_raw) if isinstance(metadata_raw, dict) else {}
        context_id = metadata.get("context_id") or metadata.get("contextId")
        return {
            "session_id": session_key,
            "source": parsed.source,
            "contextId": context_id if isinstance(context_id, str) else None,
            "metadata": metadata,
        }

    async def ensure_local_session_for_invoke(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        agent_id: UUID,
        session_key: Optional[str],
    ) -> tuple[Optional[AgentSession], Optional[SessionSource]]:
        if not session_key:
            return None, None
        try:
            parsed = parse_session_key(session_key)
        except ValueError as exc:
            raise ValueError("invalid_session_id") from exc

        if parsed.source not in self._LOCAL_SESSION_SOURCES:
            return None, None
        assert parsed.local_session_id is not None

        session = await db.scalar(
            select(AgentSession).where(
                and_(
                    AgentSession.id == parsed.local_session_id,
                    AgentSession.user_id == user_id,
                    AgentSession.deleted_at.is_(None),
                )
            )
        )

        if session is None and parsed.source == "manual":
            session = AgentSession(
                id=parsed.local_session_id,
                user_id=user_id,
                name=f"Manual Session {str(parsed.local_session_id)[:8]}",
                module_key=str(agent_id),
                session_type=AgentSession.TYPE_CHAT,
                last_activity_at=utc_now(),
            )
            db.add(session)
            await db.flush()

        if session is None:
            raise ValueError("session_not_found")

        if parsed.source == "manual" and session.session_type != AgentSession.TYPE_CHAT:
            raise ValueError("invalid_session_id")
        if (
            parsed.source == "scheduled"
            and session.session_type != AgentSession.TYPE_SCHEDULED
        ):
            raise ValueError("invalid_session_id")

        session.module_key = str(agent_id)
        session.touch()
        return session, parsed.source

    async def record_local_invoke_messages(
        self,
        db: AsyncSession,
        *,
        session: AgentSession,
        source: SessionSource,
        user_id: UUID,
        agent_id: UUID,
        query: str,
        response_content: str,
        success: bool,
        context_id: Optional[str],
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        metadata: Dict[str, Any] = {
            "source": source,
            "agent_id": str(agent_id),
            "session_id": str(session.id),
            "success": success,
        }
        if context_id and isinstance(context_id, str):
            metadata["context_id"] = context_id
        if extra_metadata:
            metadata.update(extra_metadata)

        await agent_message_handler.create_agent_message(
            db,
            user_id=user_id,
            content=query,
            sender="user",
            session_id=session.id,
            session=session,
            metadata=metadata,
        )
        await agent_message_handler.create_agent_message(
            db,
            user_id=user_id,
            content=response_content,
            sender="agent",
            session_id=session.id,
            session=session,
            metadata=metadata,
        )
        session.touch()

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
    ) -> AgentSession:
        expected_type = (
            AgentSession.TYPE_CHAT
            if source == "manual"
            else AgentSession.TYPE_SCHEDULED
        )
        session = await db.scalar(
            select(AgentSession).where(
                and_(
                    AgentSession.id == local_session_id,
                    AgentSession.user_id == user_id,
                    AgentSession.session_type == expected_type,
                    AgentSession.deleted_at.is_(None),
                )
            )
        )
        if session is None:
            raise ValueError("session_not_found")
        return session

    async def _list_all_opencode_sessions(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        size: int,
        refresh: bool,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        page = 1
        per_page = max(size, 200)
        collected: list[dict[str, Any]] = []
        meta: dict[str, Any] = {}

        while True:
            page_items, extra = await opencode_session_directory_service.list_directory(
                db,
                user_id=user_id,
                page=page,
                size=per_page,
                refresh=refresh if page == 1 else False,
            )
            if page == 1:
                meta = dict(extra.get("meta") or {})
            collected.extend(page_items)

            pagination = extra.get("pagination") if isinstance(extra, dict) else {}
            if not isinstance(pagination, dict):
                break
            pages = int(pagination.get("pages") or 0)
            if pages <= page:
                break
            page += 1

        return collected, meta


def _sender_to_role(sender: str) -> str:
    normalized = (sender or "").strip().lower()
    if normalized in {"user", "automation"}:
        return "user"
    if normalized == "agent":
        return "agent"
    return "system"


def _map_opencode_message(item: Any, index: int) -> Dict[str, Any]:
    obj = item if isinstance(item, dict) else {}
    message_id = str(
        obj.get("id")
        or obj.get("message_id")
        or obj.get("messageId")
        or f"opencode-{index}"
    )

    role = _map_role(
        _pick_str(obj, ["role", "type", "sender"])
        or _pick_str(
            _as_dict(
                _as_dict(_as_dict(obj.get("metadata")).get("opencode")).get("raw")
            ).get("info"),
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


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _pick_str(obj: Dict[str, Any], keys: list[str]) -> Optional[str]:
    for key in keys:
        value = obj.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _map_role(raw: Optional[str]) -> str:
    normalized = (raw or "").strip().lower()
    if normalized in {"assistant", "agent"}:
        return "agent"
    if normalized in {"user", "human", "automation"}:
        return "user"
    return "system"


def _extract_content(obj: Dict[str, Any]) -> str:
    direct = _pick_str(obj, ["text", "content", "message"])
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
    direct = _pick_str(obj, ["created_at", "createdAt", "timestamp", "ts"])
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
    "ParsedSessionKey",
    "SessionHubService",
    "SessionSource",
    "build_manual_session_key",
    "build_opencode_session_key",
    "build_scheduled_session_key",
    "parse_session_key",
    "session_hub_service",
]
