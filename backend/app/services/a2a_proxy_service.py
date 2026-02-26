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

    @classmethod
    def get_effective_allowed_hosts_sync(cls) -> List[str]:
        """
        Get the effective allowed hosts synchronously from cache.
        If cache is empty or not initialized, returns settings only.
        """
        if not cls._is_initialized or not cls._cached_allowed_hosts:
            return list(settings.a2a_proxy_allowed_hosts)
        return cls._cached_allowed_hosts

    @classmethod
    async def get_effective_allowed_hosts(
        cls, db: AsyncSession, force_refresh: bool = False
    ) -> List[str]:
        """
        Get the effective allowed hosts, refreshing cache if needed.
        """
        now = time.time()
        if (
            force_refresh
            or not cls._is_initialized
            or not cls._cached_allowed_hosts
            or (now - cls._last_refresh > cls._ttl)
        ):
            await cls.refresh_cache(db)

        return cls._cached_allowed_hosts

    @classmethod
    async def refresh_cache(cls, db: AsyncSession):
        """
        Refresh the in-memory cache from DB and settings.
        """
        allowed_hosts = list(settings.a2a_proxy_allowed_hosts)

        try:
            stmt = select(A2AProxyAllowlist.host_pattern).where(A2AProxyAllowlist.is_enabled)
            result = await db.execute(stmt)
            db_hosts = result.scalars().all()
            allowed_hosts.extend(db_hosts)
        except Exception:
            # Fallback to current cache or settings if DB fails
            if not cls._is_initialized:
                cls._cached_allowed_hosts = list(set(allowed_hosts))
                cls._is_initialized = True
            return

        cls._cached_allowed_hosts = list(set(allowed_hosts))
        cls._last_refresh = time.time()
        cls._is_initialized = True


a2a_proxy_service = A2AProxyService()
