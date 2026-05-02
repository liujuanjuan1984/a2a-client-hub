"""Generic external session directory aggregation service."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Sequence, cast
from uuid import UUID

from sqlalchemy import and_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.a2a_agent import A2AAgent
from app.db.models.a2a_agent_credential import A2AAgentCredential
from app.db.models.external_session_directory_cache import (
    ExternalSessionDirectoryCacheEntry,
)
from app.db.models.hub_a2a_user_credential import HubA2AUserCredential
from app.db.session import AsyncSessionLocal
from app.db.transaction import run_in_read_session, run_in_write_session
from app.features.agents.personal.runtime import a2a_runtime_builder
from app.features.agents.personal.service import a2a_agent_service
from app.features.agents.shared.runtime import shared_agent_runtime_builder
from app.features.agents.shared.service import shared_agent_service
from app.features.external_sessions.directory.adapters import (
    ExternalSessionDirectoryAdapter,
)
from app.integrations.a2a_client.types import ResolvedAgent
from app.integrations.a2a_extensions import get_a2a_extensions_service
from app.integrations.a2a_extensions.errors import A2AExtensionUpstreamError
from app.integrations.a2a_extensions.service import ExtensionCallResult

logger = get_logger(__name__)

AgentSource = Literal["personal", "shared"]
Credential = A2AAgentCredential | HubA2AUserCredential


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_record(value: Any) -> dict[str, Any] | None:
    if value and isinstance(value, dict):
        return cast(dict[str, Any], value)
    return None


def _compare_last_active(a: str | None, b: str | None) -> int:
    """Compare ISO timestamps (best-effort)."""

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


@dataclass(frozen=True)
class AgentRef:
    agent_id: UUID
    agent_name: str
    agent_source: AgentSource
    agent_url: str
    auth_type: str
    auth_header: str | None
    auth_scheme: str | None
    credential_mode: str
    extra_headers: dict[str, str] | None


@dataclass(frozen=True)
class DirectoryRuntime:
    resolved: ResolvedAgent


class ExternalSessionDirectoryService:
    """Aggregate external provider sessions across visible agents."""

    def __init__(self, *, adapter: ExternalSessionDirectoryAdapter) -> None:
        self._adapter = adapter

    @property
    def provider_key(self) -> str:
        return self._adapter.provider_key

    async def list_directory(
        self,
        *,
        user_id: UUID,
        page: int,
        size: int,
        refresh: bool,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        directory_items, meta = await self._build_directory_snapshot(
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

    async def _build_directory_snapshot(
        self,
        *,
        user_id: UUID,
        refresh: bool,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        agents, cache_entries = await run_in_read_session(
            lambda db: self._load_agents_and_cache_entries(db, user_id=user_id),
            session_factory=AsyncSessionLocal,
        )
        total_agents = len(agents)
        now = _utc_now()

        expired: list[AgentRef] = []
        missing: list[AgentRef] = []
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
            credentials_by_agent_ref = await run_in_read_session(
                lambda db: self._load_credentials_by_agent_ref(
                    db,
                    user_id=user_id,
                    agents=agents_to_refresh,
                ),
                session_factory=AsyncSessionLocal,
            )
            runtime_targets: list[tuple[AgentRef, DirectoryRuntime]] = []
            for agent in agents_to_refresh:
                try:
                    runtime = self._build_runtime_from_prefetched(
                        agent=agent,
                        credential=credentials_by_agent_ref.get(
                            (agent.agent_source, agent.agent_id)
                        ),
                    )
                except Exception as exc:
                    partial_failures += 1
                    logger.warning(
                        "External session directory runtime build failed",
                        extra={
                            "provider": self.provider_key,
                            "user_id": str(user_id),
                            "agent_id": str(agent.agent_id),
                            "agent_source": agent.agent_source,
                            "error_type": type(exc).__name__,
                        },
                    )
                    continue
                runtime_targets.append((agent, runtime))

            concurrency = max(1, int(self._adapter.refresh_concurrency))
            sem = asyncio.Semaphore(concurrency)

            async def _fetch_one(
                agent: AgentRef, runtime: DirectoryRuntime
            ) -> tuple[AgentRef, ExtensionCallResult]:
                async with sem:
                    try:
                        extensions_service = cast(Any, get_a2a_extensions_service())
                        result = await extensions_service.list_sessions(
                            runtime=runtime,
                            page=1,
                            size=int(self._adapter.per_agent_size),
                            query=None,
                        )
                        return agent, result
                    except A2AExtensionUpstreamError as exc:
                        return agent, ExtensionCallResult(
                            success=False,
                            result=None,
                            error_code=exc.error_code,
                            upstream_error=exc.upstream_error,
                        )
                    except Exception as exc:
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

            expires_at = now + timedelta(seconds=int(self._adapter.cache_ttl_seconds))
            (
                refreshed_agents,
                write_partial_failures,
            ) = await run_in_write_session(
                lambda db: self._persist_refresh_results(
                    db,
                    user_id=user_id,
                    now=now,
                    expires_at=expires_at,
                    results=results,
                ),
                session_factory=AsyncSessionLocal,
            )
            partial_failures += write_partial_failures

            cache_entries = await run_in_read_session(
                lambda db: self._load_cache_entries(db, user_id=user_id, agents=agents),
                session_factory=AsyncSessionLocal,
            )

        directory_items = self._build_directory_items(
            agents=agents,
            cache_entries=cache_entries,
        )

        meta = {
            "provider": self.provider_key,
            "total_agents": total_agents,
            "refreshed_agents": refreshed_agents,
            "cached_agents": cached_agents,
            "partial_failures": partial_failures,
        }
        return directory_items, meta

    def _build_directory_items(
        self,
        *,
        agents: list[AgentRef],
        cache_entries: dict[
            tuple[str, UUID],
            ExternalSessionDirectoryCacheEntry,
        ],
    ) -> list[dict[str, Any]]:
        dedup: dict[tuple[str, str], dict[str, Any]] = {}
        for agent in agents:
            entry = cache_entries.get((agent.agent_source, agent.agent_id))
            if not entry:
                continue
            payload = _as_record(entry.payload) or {}
            tasks = payload.get("items")
            if not isinstance(tasks, list):
                continue
            for task in tasks:
                normalized = self._adapter.normalize_task(task)
                if normalized is None:
                    continue
                candidate = {
                    "provider": self.provider_key,
                    "agent_id": agent.agent_id,
                    "agent_source": agent.agent_source,
                    "agent_name": agent.agent_name,
                    "session_id": normalized.session_id,
                    "title": normalized.title,
                    "last_active_at": normalized.last_active_at,
                }
                key = (
                    (agent.agent_url or "").strip().rstrip("/"),
                    normalized.session_id,
                )
                existing = dedup.get(key)
                if existing is None:
                    dedup[key] = candidate
                    continue

                cmp_active = _compare_last_active(
                    cast(str | None, candidate.get("last_active_at")),
                    cast(str | None, existing.get("last_active_at")),
                )
                if cmp_active > 0:
                    dedup[key] = candidate
                    continue
                if cmp_active < 0:
                    continue

                existing_source = existing.get("agent_source")
                if existing_source != "personal" and agent.agent_source == "personal":
                    dedup[key] = candidate

        directory_items = list(dedup.values())
        directory_items.sort(
            key=lambda item: (
                item.get("last_active_at") or "",
                str(item["agent_id"]),
                item["session_id"],
            ),
            reverse=True,
        )
        return directory_items

    async def _load_agents_and_cache_entries(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
    ) -> tuple[
        list[AgentRef], dict[tuple[str, UUID], ExternalSessionDirectoryCacheEntry]
    ]:
        agents = await self._list_visible_agents(db, user_id=user_id)
        cache_entries = await self._load_cache_entries(
            db, user_id=user_id, agents=agents
        )
        return agents, cache_entries

    async def _list_visible_agents(
        self, db: AsyncSession, *, user_id: UUID
    ) -> list[AgentRef]:
        personal_records = await a2a_agent_service.list_all_agents(db, user_id=user_id)
        personal = [
            AgentRef(
                agent_id=record.id,
                agent_name=record.name,
                agent_source="personal",
                agent_url=record.card_url,
                auth_type=record.auth_type,
                auth_header=record.auth_header,
                auth_scheme=record.auth_scheme,
                credential_mode=A2AAgent.CREDENTIAL_SHARED,
                extra_headers=record.extra_headers or None,
            )
            for record in personal_records
            if record.enabled
        ]
        shared_agents = await shared_agent_service.list_all_visible_agents_for_user(
            db, user_id=user_id
        )
        shared = [
            AgentRef(
                agent_id=cast(UUID, agent.id),
                agent_name=cast(str, agent.name),
                agent_source="shared",
                agent_url=cast(str, agent.card_url),
                auth_type=cast(str, agent.auth_type),
                auth_header=cast(str | None, agent.auth_header),
                auth_scheme=cast(str | None, agent.auth_scheme),
                credential_mode=cast(
                    str,
                    getattr(agent, "credential_mode", A2AAgent.CREDENTIAL_NONE),
                ),
                extra_headers=cast(dict[str, str] | None, agent.extra_headers),
            )
            for agent in shared_agents
        ]
        return [*personal, *shared]

    async def _load_cache_entries(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        agents: list[AgentRef],
    ) -> dict[tuple[str, UUID], ExternalSessionDirectoryCacheEntry]:
        if not agents:
            return {}
        agent_ids = [agent.agent_id for agent in agents]
        stmt = select(ExternalSessionDirectoryCacheEntry).where(
            and_(
                ExternalSessionDirectoryCacheEntry.user_id == user_id,
                ExternalSessionDirectoryCacheEntry.provider == self.provider_key,
                ExternalSessionDirectoryCacheEntry.agent_id.in_(agent_ids),
            )
        )
        result = await db.execute(stmt)
        entries = list(result.scalars().all())
        return {(cast(str, e.agent_source), cast(UUID, e.agent_id)): e for e in entries}

    async def _load_credentials_by_agent_ref(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        agents: list[AgentRef],
    ) -> dict[tuple[str, UUID], Credential]:
        personal_ids = [
            agent.agent_id
            for agent in agents
            if agent.agent_source == "personal"
            and agent.auth_type in {"bearer", "basic"}
        ]
        shared_credential_ids = [
            agent.agent_id
            for agent in agents
            if agent.agent_source == "shared"
            and agent.auth_type in {"bearer", "basic"}
            and agent.credential_mode == A2AAgent.CREDENTIAL_SHARED
        ]
        user_credential_ids = [
            agent.agent_id
            for agent in agents
            if agent.agent_source == "shared"
            and agent.auth_type in {"bearer", "basic"}
            and agent.credential_mode == A2AAgent.CREDENTIAL_USER
        ]

        credentials: dict[tuple[str, UUID], Credential] = {}
        agent_credential_ids = [*personal_ids, *shared_credential_ids]
        if agent_credential_ids:
            stmt = select(A2AAgentCredential).where(
                A2AAgentCredential.agent_id.in_(agent_credential_ids)
            )
            result = await db.execute(stmt)
            for credential in result.scalars().all():
                agent_id = cast(UUID, credential.agent_id)
                source = "personal" if agent_id in personal_ids else "shared"
                credentials[(source, agent_id)] = credential

        if user_credential_ids:
            stmt = select(HubA2AUserCredential).where(
                and_(
                    HubA2AUserCredential.user_id == user_id,
                    HubA2AUserCredential.agent_id.in_(user_credential_ids),
                )
            )
            result = await db.execute(stmt)
            for credential in result.scalars().all():
                credentials[("shared", cast(UUID, credential.agent_id))] = credential

        return credentials

    async def _write_cache_entry(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        agent: AgentRef,
        now: datetime,
        expires_at: datetime,
        result: Any,
    ) -> bool:
        if not result.success:
            await self._mark_cache_entry_refresh_failed(
                db,
                user_id=user_id,
                agent=agent,
                last_error_code=result.error_code,
                last_error_at=now,
            )
            return False

        envelope = _as_record(result.result) or {}
        raw_items = envelope.get("items")
        tasks = raw_items if isinstance(raw_items, list) else []
        pruned = [
            item
            for task in tasks
            if (item := self._adapter.prune_task_for_cache(task)) is not None
        ]

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

    async def _persist_refresh_results(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        now: datetime,
        expires_at: datetime,
        results: Sequence[tuple[AgentRef, ExtensionCallResult] | BaseException],
    ) -> tuple[int, int]:
        refreshed_agents = 0
        partial_failures = 0
        for item in results:
            if isinstance(item, BaseException):
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
            except Exception as exc:
                partial_failures += 1
                logger.warning(
                    "External session directory cache write failed",
                    extra={
                        "provider": self.provider_key,
                        "user_id": str(user_id),
                        "agent_id": str(agent.agent_id),
                        "agent_source": agent.agent_source,
                        "error_type": type(exc).__name__,
                    },
                )
                continue
            if ok:
                refreshed_agents += 1
            else:
                partial_failures += 1

        return refreshed_agents, partial_failures

    def _build_runtime_from_prefetched(
        self,
        *,
        agent: AgentRef,
        credential: Credential | None,
    ) -> DirectoryRuntime:
        if agent.agent_source == "shared":
            resolved, _ = shared_agent_runtime_builder.resolve_prefetched(
                name=agent.agent_name,
                card_url=agent.agent_url,
                extra_headers=agent.extra_headers,
                auth_type=agent.auth_type,
                auth_header=agent.auth_header,
                auth_scheme=agent.auth_scheme,
                credential=credential,
            )
            return DirectoryRuntime(resolved=resolved)
        resolved, _ = a2a_runtime_builder.resolve_prefetched(
            name=agent.agent_name,
            card_url=agent.agent_url,
            extra_headers=agent.extra_headers,
            auth_type=agent.auth_type,
            auth_header=agent.auth_header,
            auth_scheme=agent.auth_scheme,
            credential=credential,
        )
        return DirectoryRuntime(resolved=resolved)

    async def _upsert_cache_entry(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        agent: AgentRef,
        expires_at: datetime,
        payload: dict[str, Any],
        last_success_at: datetime | None,
        last_error_code: str | None,
        last_error_at: datetime | None,
    ) -> None:
        stmt = insert(ExternalSessionDirectoryCacheEntry).values(
            user_id=user_id,
            provider=self.provider_key,
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

    async def _mark_cache_entry_refresh_failed(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        agent: AgentRef,
        last_error_code: str | None,
        last_error_at: datetime,
    ) -> None:
        stmt = (
            update(ExternalSessionDirectoryCacheEntry)
            .where(
                and_(
                    ExternalSessionDirectoryCacheEntry.user_id == user_id,
                    ExternalSessionDirectoryCacheEntry.provider == self.provider_key,
                    ExternalSessionDirectoryCacheEntry.agent_source
                    == agent.agent_source,
                    ExternalSessionDirectoryCacheEntry.agent_id == agent.agent_id,
                )
            )
            .values(
                last_error_code=last_error_code,
                last_error_at=last_error_at,
            )
        )
        await db.execute(stmt)
