"""
Database session configuration for Common Compass Backend.

This module exposes the SQLAlchemy `SessionLocal` bound to the configured engine.
Routing dependencies should import `get_db` from `app.api.deps` to avoid duplication.
"""

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import settings

_use_null_pool = settings.schema_name.startswith("test_")

# Create SQLAlchemy engine
sync_engine_kwargs = dict(
    echo=settings.database_echo,
    pool_pre_ping=True,
    pool_recycle=300,
)
if _use_null_pool:
    sync_engine_kwargs["poolclass"] = NullPool

engine = create_engine(
    settings.database_url,
    **sync_engine_kwargs,
)

# Create SessionLocal class for database sessions
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

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

AsyncSessionLocal = async_sessionmaker(
    async_engine,
    expire_on_commit=False,
    autoflush=False,
    class_=AsyncSession,
)
