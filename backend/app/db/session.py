"""Database session configuration for a2a-client-hub.

This module exposes the SQLAlchemy async session factory used by the API.
Routing dependencies should import `get_async_db` from `app.api.deps` to avoid duplication.
"""

import time
import traceback
from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.runtime.ops_metrics import ops_metrics

_use_null_pool = settings.schema_name.startswith("test_")

# Async engine/session factory (used by new async stack)
async_engine_kwargs: dict[str, Any] = dict(
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
_APP_ROOT = Path(__file__).resolve().parents[1]
_CHECKOUT_STARTED_KEY = "ops_metrics_checkout_started_at"
_CHECKOUT_SOURCE_KEY = "ops_metrics_checkout_source"


def _capture_db_checkout_source() -> str:
    for frame in reversed(traceback.extract_stack(limit=32)[:-1]):
        try:
            relative_path = Path(frame.filename).resolve().relative_to(_APP_ROOT)
        except Exception:
            continue

        relative_text = relative_path.as_posix()
        if relative_text in {"db/session.py", "runtime/ops_metrics.py"}:
            continue
        return f"app/{relative_text}:{frame.lineno}:{frame.name}"

    return "unknown"


@event.listens_for(_pool, "checkout")
def _pool_checkout(*args: Any) -> None:
    ops_metrics.increment_db_pool_checked_out()
    if len(args) < 2:
        return
    connection_record = args[1]
    info = getattr(connection_record, "info", None)
    if not isinstance(info, dict):
        return
    info[_CHECKOUT_STARTED_KEY] = time.perf_counter()
    info[_CHECKOUT_SOURCE_KEY] = _capture_db_checkout_source()


@event.listens_for(_pool, "checkin")
def _pool_checkin(*args: Any) -> None:
    ops_metrics.decrement_db_pool_checked_out()
    if len(args) < 2:
        return
    connection_record = args[1]
    info = getattr(connection_record, "info", None)
    if not isinstance(info, dict):
        return

    started_at = info.pop(_CHECKOUT_STARTED_KEY, None)
    source = str(info.pop(_CHECKOUT_SOURCE_KEY, "unknown"))
    if not isinstance(started_at, (int, float)):
        return

    latency_ms = (time.perf_counter() - float(started_at)) * 1000.0
    ops_metrics.observe_db_connection_hold(
        latency_ms=latency_ms,
        source=source,
        long_hold_threshold_ms=settings.async_db_connection_hold_warn_ms,
    )


AsyncSessionLocal = async_sessionmaker(
    async_engine,
    expire_on_commit=False,
    autoflush=False,
    class_=AsyncSession,
)
