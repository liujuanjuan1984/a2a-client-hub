"""OpenCode sessions directory service.

This service aggregates OpenCode sessions across all agents visible to a user.
To avoid N+1 upstream calls on every UI visit, it maintains a DB-backed TTL cache
per (user, agent_source, agent_id).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models.external_session_directory_cache import (
    ExternalSessionDirectoryCacheEntry,
)
from app.integrations.a2a_extensions import get_a2a_extensions_service
from app.integrations.a2a_extensions.errors import A2AExtensionUpstreamError
from app.integrations.a2a_extensions.service import ExtensionCallResult
from app.services.a2a_agents import a2a_agent_service
from app.services.a2a_runtime import a2a_runtime_builder
from app.services.hub_a2a_agents import hub_a2a_agent_service
from app.services.hub_a2a_runtime import hub_a2a_runtime_builder

logger = get_logger(__name__)
OPENCODE_PROVIDER = "opencode"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_record(value: Any) -> Optional[Dict[str, Any]]:
    if value and isinstance(value, dict):
        return value
    return None


def _pick_str(obj: Optional[Dict[str, Any]], keys: Iterable[str]) -> Optional[str]:
    if not obj:
        return None
    for key in keys:
        value = obj.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _pick_ms(obj: Optional[Dict[str, Any]], keys: Iterable[str]) -> Optional[int]:
    if not obj:
        return None
    for key in keys:
        value = obj.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
    return None


def _to_iso_from_ms(value: Optional[int]) -> Optional[str]:
    if value is None:
        return None
    try:
        dt = datetime.fromtimestamp(value / 1000.0, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return dt.isoformat()


def _extract_session_id(task: Any) -> Optional[str]:
    obj = _as_record(task)
    return _pick_str(obj, ["contextId", "context_id", "id", "session_id", "sessionId"])


def _extract_title(task: Any) -> str:
    obj = _as_record(task) or {}
    metadata = _as_record(obj.get("metadata")) or {}
    opencode = _as_record(metadata.get("opencode")) or {}
    title = _pick_str(opencode, ["title"])
    if title:
        return title
    return (
        _pick_str(obj, ["title", "name", "label"])
        or _extract_session_id(obj)
        or "Session"
    )


def _extract_last_active_at(task: Any) -> Optional[str]:
    obj = _as_record(task) or {}
    # Prefer explicit fields if present.
    direct = _pick_str(
        obj, ["last_active_at", "updated_at", "created_at", "timestamp", "ts"]
    )
    if direct:
        return direct

    metadata = _as_record(obj.get("metadata")) or {}
    opencode = _as_record(metadata.get("opencode")) or {}
    raw = _as_record(opencode.get("raw")) or {}
    raw_direct = _pick_str(
        raw, ["last_active_at", "updated_at", "created_at", "timestamp", "ts"]
    )
    if raw_direct:
        return raw_direct

    time_obj = _as_record(raw.get("time")) or {}
    info = _as_record(raw.get("info")) or {}
    info_time = _as_record(info.get("time")) or {}
    ms = (
        _pick_ms(time_obj, ["updated", "created"])
        or _pick_ms(info_time, ["updated", "created", "completed"])
        or _pick_ms(raw, ["updated", "created"])
    )
    return _to_iso_from_ms(ms)


def _normalize_agent_url(value: str) -> str:
    return (value or "").strip().rstrip("/")


def _compare_last_active(a: Optional[str], b: Optional[str]) -> int:
    """Compare ISO timestamps (best-effort).

    Returns:
        1 if a > b, -1 if a < b, 0 if equal/unknown.
    """

    if not a and not b:
        return 0
    if a and not b:
        return 1
    if b and not a:
        return -1
    assert a is not None and b is not None
    if a == b:
        return 0
    return 1 if a > b else -1


def _prune_task_for_cache(task: Any) -> Optional[Dict[str, Any]]:
    obj = _as_record(task)
    if not obj:
        return None
    session_id = _extract_session_id(obj)
    if not session_id:
        return None

    metadata = _as_record(obj.get("metadata")) or {}
    opencode = _as_record(metadata.get("opencode")) or {}
    raw = _as_record(opencode.get("raw")) or {}
    raw_time = _as_record(raw.get("time")) or {}
    raw_info_time = _as_record((_as_record(raw.get("info")) or {}).get("time")) or {}
    updated = (
        raw_time.get("updated")
        if isinstance(raw_time.get("updated"), (int, float, str))
        else None
    )
    created = (
        raw_time.get("created")
        if isinstance(raw_time.get("created"), (int, float, str))
        else None
    )
    if updated is None and "updated" in raw_info_time:
        updated = raw_info_time.get("updated")
    if created is None and "created" in raw_info_time:
        created = raw_info_time.get("created")

    # Only keep fields required for listing/sorting/binding.
    return {
        "id": obj.get("id"),
        "contextId": obj.get("contextId") or obj.get("context_id") or session_id,
        "metadata": {
            "opencode": {
                "title": opencode.get("title"),
                "raw": {
                    "time": {
                        "updated": updated,
                        "created": created,
                    }
                },
            }
        },
    }


@dataclass(frozen=True)
class _AgentRef:
    agent_id: UUID
    agent_name: str
    agent_source: str  # personal/shared
    agent_url: str


class OpencodeSessionDirectoryService:
    async def _build_directory_snapshot(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        refresh: bool,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        agents = await self._list_visible_agents(db, user_id=user_id)
        total_agents = len(agents)

        cache_entries = await self._load_cache_entries(
            db, user_id=user_id, agents=agents
        )
        now = _utc_now()

        expired: list[_AgentRef] = []
        missing: list[_AgentRef] = []
        cached_agents = 0
        for agent in agents:
            entry = cache_entries.get((agent.agent_source, agent.agent_id))
            if entry is None:
                missing.append(agent)
                continue
            cached_agents += 1
            if entry.expires_at <= now:
                expired.append(agent)

        agents_to_refresh = agents if refresh else missing + expired

        refreshed_agents = 0
        partial_failures = 0
        if agents_to_refresh:
            # AsyncSession cannot be shared across concurrent tasks safely.
            # Build runtimes sequentially (DB-bound), then refresh upstream concurrently.
            runtime_targets: list[tuple[_AgentRef, Any]] = []
            for agent in agents_to_refresh:
                try:
                    runtime = await self._build_runtime(
                        db, user_id=user_id, agent=agent
                    )
                except Exception as exc:  # noqa: BLE001
                    partial_failures += 1
                    logger.warning(
                        "OpenCode sessions cache runtime build failed",
                        extra={
                            "user_id": str(user_id),
                            "agent_id": str(agent.agent_id),
                            "agent_source": agent.agent_source,
                            "error_type": type(exc).__name__,
                        },
                    )
                    continue
                runtime_targets.append((agent, runtime))

            concurrency = max(1, int(settings.opencode_sessions_refresh_concurrency))
            sem = asyncio.Semaphore(concurrency)

            async def _fetch_one(agent: _AgentRef, runtime: Any):
                async with sem:
                    try:
                        result = (
                            await get_a2a_extensions_service().opencode_list_sessions(
                                runtime=runtime,
                                page=1,
                                size=int(settings.opencode_sessions_per_agent_size),
                                query=None,
                            )
                        )
                        return agent, result
                    except A2AExtensionUpstreamError as exc:
                        # Cache negative results for the TTL window to avoid
                        # re-fetching unsupported/unavailable agents on every visit.
                        return agent, ExtensionCallResult(
                            success=False,
                            result=None,
                            error_code=exc.error_code,
                            upstream_error=exc.upstream_error,
                        )
                    except Exception as exc:  # noqa: BLE001
                        return agent, ExtensionCallResult(
                            success=False,
                            result=None,
                            error_code="upstream_error",
                            upstream_error={"type": type(exc).__name__},
                        )

            results = await asyncio.gather(
                *[_fetch_one(agent, runtime) for agent, runtime in runtime_targets],
                return_exceptions=True,
            )

            expires_at = now + timedelta(
                seconds=int(settings.opencode_sessions_cache_ttl_seconds)
            )
            for item in results:
                if isinstance(item, Exception):
                    partial_failures += 1
                    continue
                agent, result = item
                try:
                    ok = await self._write_cache_entry(
                        db,
                        user_id=user_id,
                        agent=agent,
                        now=now,
                        expires_at=expires_at,
                        result=result,
                    )
                except Exception as exc:  # noqa: BLE001
                    partial_failures += 1
                    logger.warning(
                        "OpenCode sessions cache write failed",
                        extra={
                            "user_id": str(user_id),
                            "agent_id": str(agent.agent_id),
                            "agent_source": agent.agent_source,
                            "error_type": type(exc).__name__,
                        },
                    )
                    continue
                refreshed_agents += 1 if ok else 0

            await db.commit()

            # Reload cache entries after refresh attempts.
            cache_entries = await self._load_cache_entries(
                db, user_id=user_id, agents=agents
            )

        directory_items: list[Dict[str, Any]] = []
        # Deduplicate sessions across agents that point to the same upstream
        # (e.g. personal + shared agent records referencing the same OpenCode A2A serve).
        dedup: dict[tuple[str, str], Dict[str, Any]] = {}
        for agent in agents:
            entry = cache_entries.get((agent.agent_source, agent.agent_id))
            if not entry:
                continue
            payload = _as_record(entry.payload) or {}
            tasks = payload.get("items")
            if not isinstance(tasks, list):
                continue
            for task in tasks:
                session_id = _extract_session_id(task)
                if not session_id:
                    continue
                candidate = {
                    "agent_id": agent.agent_id,
                    "agent_source": agent.agent_source,
                    "agent_name": agent.agent_name,
                    "session_id": session_id,
                    "title": _extract_title(task),
                    "last_active_at": _extract_last_active_at(task),
                }
                key = (_normalize_agent_url(agent.agent_url), session_id)
                existing = dedup.get(key)
                if existing is None:
                    dedup[key] = candidate
                    continue

                cmp_active = _compare_last_active(
                    candidate.get("last_active_at"), existing.get("last_active_at")
                )
                if cmp_active > 0:
                    dedup[key] = candidate
                    continue
                if cmp_active < 0:
                    continue

                # Prefer personal agent records when timestamps are equal/missing,
                # to keep user-managed agent naming/credentials as the default.
                existing_source = existing.get("agent_source")
                if existing_source != "personal" and agent.agent_source == "personal":
                    dedup[key] = candidate
                    continue

        directory_items = list(dedup.values())

        directory_items.sort(
            key=lambda item: (
                item.get("last_active_at") or "",
                str(item["agent_id"]),
                item["session_id"],
            ),
            reverse=True,
        )

        meta = {
            "total_agents": total_agents,
            "refreshed_agents": refreshed_agents,
            "cached_agents": cached_agents,
            "partial_failures": partial_failures,
        }
        return directory_items, meta

    async def list_directory(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        page: int,
        size: int,
        refresh: bool,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        directory_items, meta = await self._build_directory_snapshot(
            db,
            user_id=user_id,
            refresh=refresh,
        )
        total = len(directory_items)
        pages = (total + size - 1) // size if size else 0
        offset = (page - 1) * size
        page_items = directory_items[offset : offset + size]
        pagination = {
            "page": page,
            "size": size,
            "total": total,
            "pages": pages,
        }
        return page_items, {"pagination": pagination, "meta": meta}

    async def list_directory_all(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        refresh: bool,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        directory_items, meta = await self._build_directory_snapshot(
            db,
            user_id=user_id,
            refresh=refresh,
        )
        total = len(directory_items)
        pagination = {
            "page": 1,
            "size": total,
            "total": total,
            "pages": 1 if total > 0 else 0,
        }
        return directory_items, {"pagination": pagination, "meta": meta}

    async def _list_visible_agents(
        self, db: AsyncSession, *, user_id: UUID
    ) -> List[_AgentRef]:
        personal_records = await a2a_agent_service.list_agents(db, user_id=user_id)
        personal = [
            _AgentRef(
                agent_id=record.agent.id,
                agent_name=record.agent.name,
                agent_source="personal",
                agent_url=record.agent.card_url,
            )
            for record in personal_records
            if record.agent.enabled
        ]
        hub_agents = await hub_a2a_agent_service.list_visible_agents_for_user(
            db, user_id=user_id
        )
        shared = [
            _AgentRef(
                agent_id=agent.id,
                agent_name=agent.name,
                agent_source="shared",
                agent_url=agent.card_url,
            )
            for agent in hub_agents
        ]
        return [*personal, *shared]

    async def _load_cache_entries(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        agents: List[_AgentRef],
    ) -> Dict[Tuple[str, UUID], ExternalSessionDirectoryCacheEntry]:
        if not agents:
            return {}
        agent_ids = [agent.agent_id for agent in agents]
        stmt = select(ExternalSessionDirectoryCacheEntry).where(
            and_(
                ExternalSessionDirectoryCacheEntry.user_id == user_id,
                ExternalSessionDirectoryCacheEntry.provider == OPENCODE_PROVIDER,
                ExternalSessionDirectoryCacheEntry.agent_id.in_(agent_ids),
            )
        )
        result = await db.execute(stmt)
        entries = list(result.scalars().all())
        return {(e.agent_source, e.agent_id): e for e in entries}

    async def _write_cache_entry(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        agent: _AgentRef,
        now: datetime,
        expires_at: datetime,
        result: Any,
    ) -> bool:
        if not result.success:
            await self._upsert_cache_entry(
                db,
                user_id=user_id,
                agent=agent,
                expires_at=expires_at,
                payload={"items": []},
                last_success_at=None,
                last_error_code=result.error_code,
                last_error_at=now,
            )
            return False

        envelope = _as_record(result.result) or {}
        raw_items = envelope.get("items")
        tasks = raw_items if isinstance(raw_items, list) else []
        pruned = [item for t in tasks if (item := _prune_task_for_cache(t)) is not None]

        await self._upsert_cache_entry(
            db,
            user_id=user_id,
            agent=agent,
            expires_at=expires_at,
            payload={"items": pruned},
            last_success_at=now,
            last_error_code=None,
            last_error_at=None,
        )
        return True

    async def _build_runtime(
        self, db: AsyncSession, *, user_id: UUID, agent: _AgentRef
    ) -> Any:
        if agent.agent_source == "shared":
            return await hub_a2a_runtime_builder.build(
                db, user_id=user_id, agent_id=agent.agent_id
            )
        return await a2a_runtime_builder.build(
            db, user_id=user_id, agent_id=agent.agent_id
        )

    async def _upsert_cache_entry(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        agent: _AgentRef,
        expires_at: datetime,
        payload: Dict[str, Any],
        last_success_at: Optional[datetime],
        last_error_code: Optional[str],
        last_error_at: Optional[datetime],
    ) -> None:
        stmt = insert(ExternalSessionDirectoryCacheEntry).values(
            user_id=user_id,
            provider=OPENCODE_PROVIDER,
            agent_source=agent.agent_source,
            agent_id=agent.agent_id,
            payload=payload,
            expires_at=expires_at,
            last_success_at=last_success_at,
            last_error_code=last_error_code,
            last_error_at=last_error_at,
            refreshed_at=_utc_now(),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id", "provider", "agent_source", "agent_id"],
            set_={
                "payload": payload,
                "expires_at": expires_at,
                "last_success_at": last_success_at,
                "last_error_code": last_error_code,
                "last_error_at": last_error_at,
                "refreshed_at": _utc_now(),
            },
        )
        await db.execute(stmt)


opencode_session_directory_service = OpencodeSessionDirectoryService()

__all__ = ["opencode_session_directory_service", "OpencodeSessionDirectoryService"]
