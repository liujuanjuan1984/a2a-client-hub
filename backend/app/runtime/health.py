"""Health check probe helpers for a2a-client-hub."""

from __future__ import annotations

import time
from typing import Any, Dict, Literal

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal, async_engine
from app.integrations.a2a_client import get_a2a_service
from app.integrations.a2a_client.metrics import a2a_metrics
from app.integrations.a2a_extensions.metrics import a2a_extension_metrics
from app.runtime.ops_metrics import ops_metrics
from app.runtime.ops_metrics_refresh import refresh_db_pool_checked_out
from app.utils.timezone_util import utc_now_iso

HealthStatus = Literal["healthy", "degraded", "unhealthy"]

logger = get_logger(__name__)


def _format_result(
    name: str,
    status: HealthStatus,
    latency_ms: float,
    *,
    detail: str | None = None,
    last_checked_at: str | None = None,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "name": name,
        "status": status,
        "latency_ms": round(latency_ms, 3),
    }
    if detail:
        result["detail"] = detail
    if last_checked_at:
        result["last_checked_at"] = last_checked_at
    return result


async def _check_database() -> Dict[str, Any]:
    started = time.perf_counter()
    timestamp = utc_now_iso()

    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        refresh_db_pool_checked_out(async_engine.sync_engine.pool)
        return _format_result(
            "database",
            "healthy",
            (time.perf_counter() - started) * 1000,
            last_checked_at=timestamp,
        )
    except (
        SQLAlchemyError
    ) as exc:  # pragma: no cover - specific SQL errors hard to trigger
        logger.error("Database health probe failed", exc_info=exc)
        return _format_result(
            "database",
            "unhealthy",
            (time.perf_counter() - started) * 1000,
            detail=str(exc),
            last_checked_at=timestamp,
        )
    except Exception as exc:  # pragma: no cover - safety net
        logger.error("Unexpected database health probe failure", exc_info=exc)
        return _format_result(
            "database",
            "unhealthy",
            (time.perf_counter() - started) * 1000,
            detail=str(exc),
            last_checked_at=timestamp,
        )


async def run_health_checks() -> tuple[HealthStatus, list[Dict[str, Any]]]:
    checks = [await _check_database(), _check_a2a()]

    overall: HealthStatus = "healthy"
    if any(check["status"] == "unhealthy" for check in checks):
        overall = "unhealthy"
    elif any(check["status"] == "degraded" for check in checks):
        overall = "degraded"

    return overall, checks


def _check_a2a() -> Dict[str, Any]:
    timestamp = utc_now_iso()
    started = time.perf_counter()

    status: HealthStatus = "healthy"
    detail: str | None = None
    try:
        # We do not probe external user-managed agents from /health. Instead,
        # ensure the integration layer can be initialised.
        get_a2a_service()
    except Exception as exc:  # pragma: no cover - defensive safeguard
        status = "unhealthy"
        detail = f"initialisation failed: {exc}"

    result = _format_result(
        "a2a",
        status,
        (time.perf_counter() - started) * 1000,
        detail=detail,
        last_checked_at=timestamp,
    )
    result["metrics"] = a2a_metrics.snapshot()
    result["extension_metrics"] = a2a_extension_metrics.snapshot()
    result["ops_metrics"] = ops_metrics.snapshot()
    return result
