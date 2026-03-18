from __future__ import annotations

import asyncio
import time
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.a2a_proxy_allowlist import A2AProxyAllowlist


class A2AProxyService:
    _cached_allowed_hosts: List[str] = []
    _last_refresh: float = 0
    _ttl: float = 60  # 1 minute TTL
    _is_initialized: bool = False
    _refresh_lock: asyncio.Lock | None = None
    _refresh_lock_loop: asyncio.AbstractEventLoop | None = None

    @classmethod
    def _get_refresh_lock(cls) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if cls._refresh_lock is None or cls._refresh_lock_loop is not loop:
            cls._refresh_lock = asyncio.Lock()
            cls._refresh_lock_loop = loop
        return cls._refresh_lock

    @staticmethod
    def _dedupe_allowed_hosts(allowed_hosts: List[str]) -> List[str]:
        return list(dict.fromkeys(allowed_hosts))

    @classmethod
    def _needs_refresh(cls, *, now: float | None = None) -> bool:
        current_time = time.time() if now is None else now
        return not cls._is_initialized or (current_time - cls._last_refresh > cls._ttl)

    @classmethod
    def invalidate_cache(cls) -> None:
        """Mark the process-local cache as stale without dropping the snapshot."""

        cls._last_refresh = 0

    @classmethod
    def get_effective_allowed_hosts_sync(cls) -> List[str]:
        """
        Get the effective allowed hosts synchronously from cache.
        If the cache has not been initialized yet, returns settings only.
        """
        if not cls._is_initialized:
            return list(settings.a2a_proxy_allowed_hosts)
        return list(cls._cached_allowed_hosts)

    @classmethod
    async def get_effective_allowed_hosts(
        cls, db: AsyncSession, force_refresh: bool = False
    ) -> List[str]:
        """
        Get the effective allowed hosts, refreshing cache if needed.
        """
        if force_refresh:
            return await cls.refresh_cache(db)

        now = time.time()
        if cls._needs_refresh(now=now):
            async with cls._get_refresh_lock():
                if cls._needs_refresh():
                    await cls._refresh_cache_locked(db)

        return list(cls._cached_allowed_hosts)

    @classmethod
    async def refresh_cache(cls, db: AsyncSession) -> List[str]:
        """
        Refresh the in-memory cache from DB and settings.
        """
        async with cls._get_refresh_lock():
            await cls._refresh_cache_locked(db)
        return list(cls._cached_allowed_hosts)

    @classmethod
    async def prime_cache(cls, db: AsyncSession) -> List[str]:
        """Warm the process-local cache during application startup."""

        return await cls.refresh_cache(db)

    @classmethod
    async def _refresh_cache_locked(cls, db: AsyncSession) -> None:
        allowed_hosts = list(settings.a2a_proxy_allowed_hosts)

        try:
            stmt = select(A2AProxyAllowlist.host_pattern).where(
                A2AProxyAllowlist.is_enabled
            )
            result = await db.execute(stmt)
            db_hosts = result.scalars().all()
            allowed_hosts.extend(db_hosts)
        except Exception:
            # Fallback to the last successful snapshot, or settings-only on first use.
            if not cls._is_initialized:
                cls._cached_allowed_hosts = cls._dedupe_allowed_hosts(allowed_hosts)
                cls._is_initialized = True
                cls._last_refresh = time.time()
            return

        cls._cached_allowed_hosts = cls._dedupe_allowed_hosts(allowed_hosts)
        cls._last_refresh = time.time()
        cls._is_initialized = True


a2a_proxy_service = A2AProxyService()
