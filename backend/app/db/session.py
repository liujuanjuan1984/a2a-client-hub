"""Database session configuration for a2a-client-hub.

This module exposes the SQLAlchemy async session factory used by the API.
Routing dependencies should import `get_async_db` from `app.api.deps` to avoid duplication.
"""

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.services.ops_metrics import ops_metrics

_use_null_pool = settings.schema_name.startswith("test_")

# Async engine/session factory (used by new async stack)
async_engine_kwargs = dict(
    echo=settings.database_echo,
    pool_pre_ping=True,
)
if _use_null_pool:
    async_engine_kwargs["poolclass"] = NullPool
else:
    async_engine_kwargs.update(
        pool_size=settings.async_db_pool_size,
        max_overflow=settings.async_db_max_overflow,
        pool_timeout=settings.async_db_pool_timeout,
    )

async_engine = create_async_engine(
    settings.async_database_url,
    **async_engine_kwargs,
)

_pool = async_engine.sync_engine.pool


@event.listens_for(_pool, "checkout")
def _pool_checkout(*_args) -> None:
    ops_metrics.increment_db_pool_checked_out()


@event.listens_for(_pool, "checkin")
def _pool_checkin(*_args) -> None:
    ops_metrics.decrement_db_pool_checked_out()


AsyncSessionLocal = async_sessionmaker(
    async_engine,
    expire_on_commit=False,
    autoflush=False,
    class_=AsyncSession,
)
