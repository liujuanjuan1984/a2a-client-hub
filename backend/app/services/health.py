"""Health check probe helpers for Common Compass."""

from __future__ import annotations

import asyncio
import time
from threading import Lock
from typing import Any, Dict, Literal

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.cardbox.engine_factory import create_engine
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.integrations.a2a_client import get_a2a_service
from app.integrations.a2a_client.errors import A2AAgentUnavailableError
from app.integrations.a2a_client.metrics import a2a_metrics
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


def _check_database() -> Dict[str, Any]:
    started = time.perf_counter()
    timestamp = utc_now_iso()
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
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


def _check_cardbox() -> Dict[str, Any]:
    started = time.perf_counter()
    timestamp = utc_now_iso()
    try:
        engine = create_engine("__health_probe__", trace_id="health-probe")
        storage = engine.storage_adapter
        storage.load_card_box("__health_probe__", tenant_id="__health_probe__")
        return _format_result(
            "cardbox",
            "healthy",
            (time.perf_counter() - started) * 1000,
            last_checked_at=timestamp,
        )
    except ModuleNotFoundError:
        detail = "card_box_core not installed"
        logger.warning("Cardbox health probe degraded: %s", detail)
        return _format_result(
            "cardbox",
            "degraded",
            (time.perf_counter() - started) * 1000,
            detail=detail,
            last_checked_at=timestamp,
        )
    except Exception as exc:
        logger.error("Cardbox health probe failed", exc_info=exc)
        return _format_result(
            "cardbox",
            "unhealthy",
            (time.perf_counter() - started) * 1000,
            detail=str(exc),
            last_checked_at=timestamp,
        )


_llm_probe_lock = Lock()
_llm_probe_cache: Dict[str, Any] = {"expires_at": 0.0, "result": None}

_a2a_probe_lock = Lock()
_a2a_probe_cache: Dict[str, Any] = {"expires_at": 0.0, "result": None}


def _perform_llm_active_probe(litellm_module: Any, timestamp: str) -> Dict[str, Any]:
    started = time.perf_counter()
    try:
        _list_models(litellm_module)
        status: HealthStatus = "healthy"
        detail = None
    except Exception as exc:  # pragma: no cover - network errors difficult to simulate
        logger.warning("LLM active health probe degraded: %s", exc)
        status = "degraded"
        detail = f"active probe failed: {exc}"
    latency = (time.perf_counter() - started) * 1000
    return _format_result(
        "llm",
        status,
        latency,
        detail=detail,
        last_checked_at=timestamp,
    )


def _list_models(litellm_module: Any) -> Any:
    return litellm_module.list_models()


def _should_run_active_llm_probe() -> bool:
    return bool(settings.health_llm_active_probe_enabled)


def _check_llm() -> Dict[str, Any]:
    timestamp = utc_now_iso()
    started = time.perf_counter()
    try:
        import litellm  # type: ignore[import-not-found]
    except ImportError:
        return _format_result(
            "llm",
            "degraded",
            (time.perf_counter() - started) * 1000,
            detail="litellm not installed",
            last_checked_at=timestamp,
        )

    if not settings.litellm_model:
        return _format_result(
            "llm",
            "degraded",
            (time.perf_counter() - started) * 1000,
            detail="model not configured",
            last_checked_at=timestamp,
        )

    if not settings.litellm_api_key:
        return _format_result(
            "llm",
            "degraded",
            (time.perf_counter() - started) * 1000,
            detail="api key not configured",
            last_checked_at=timestamp,
        )

    if not _should_run_active_llm_probe():
        return _format_result(
            "llm",
            "healthy",
            (time.perf_counter() - started) * 1000,
            last_checked_at=timestamp,
        )

    ttl_seconds = max(settings.health_llm_active_probe_ttl_seconds, 1)
    now_monotonic = time.monotonic()
    with _llm_probe_lock:
        cached = _llm_probe_cache.get("result")
        expires_at = _llm_probe_cache.get("expires_at", 0.0)
        if cached and isinstance(cached, dict) and now_monotonic < float(expires_at):
            return cached

        result = _perform_llm_active_probe(litellm, timestamp)
        _llm_probe_cache["result"] = result
        _llm_probe_cache["expires_at"] = now_monotonic + ttl_seconds
        return result


def run_health_checks() -> tuple[HealthStatus, list[Dict[str, Any]]]:
    checks = [_check_database(), _check_cardbox(), _check_llm(), _check_a2a()]

    overall: HealthStatus = "healthy"
    if any(check["status"] == "unhealthy" for check in checks):
        overall = "unhealthy"
    elif any(check["status"] == "degraded" for check in checks):
        overall = "degraded"

    return overall, checks


def _check_a2a() -> Dict[str, Any]:
    timestamp = utc_now_iso()
    started = time.perf_counter()

    if not settings.a2a_enabled:
        result = _format_result(
            "a2a",
            "degraded",
            (time.perf_counter() - started) * 1000,
            detail="integration disabled",
            last_checked_at=timestamp,
        )
        result["metrics"] = a2a_metrics.snapshot()
        return result

    agent_name = _select_probe_agent()
    if not agent_name:
        result = _format_result(
            "a2a",
            "degraded",
            (time.perf_counter() - started) * 1000,
            detail="no agents configured",
            last_checked_at=timestamp,
        )
        result["metrics"] = a2a_metrics.snapshot()
        return result

    ttl_seconds = max(settings.a2a_health_probe_ttl_seconds, 1)
    now = time.monotonic()
    with _a2a_probe_lock:
        cached = _a2a_probe_cache.get("result")
        expires_at = _a2a_probe_cache.get("expires_at", 0.0)
        if cached and isinstance(cached, dict) and now < float(expires_at):
            base_result = dict(cached)
        else:
            base_result = _perform_a2a_probe(agent_name, timestamp)
            _a2a_probe_cache["result"] = base_result
            _a2a_probe_cache["expires_at"] = now + ttl_seconds

    result = dict(base_result)
    result["metrics"] = a2a_metrics.snapshot(agent_name)
    return result


def _select_probe_agent() -> str | None:
    configured = settings.a2a_health_probe_agent.strip()
    if configured:
        return configured

    agent_names = list((settings.a2a_agents or {}).keys())
    return agent_names[0] if agent_names else None


def _perform_a2a_probe(agent_name: str, timestamp: str) -> Dict[str, Any]:
    started = time.perf_counter()
    status: HealthStatus = "healthy"
    detail: str | None = None

    try:
        _execute_a2a_probe(agent_name)
    except ValueError as exc:
        status = "degraded"
        detail = str(exc)
    except A2AAgentUnavailableError as exc:
        status = "unhealthy"
        detail = str(exc)
    except Exception as exc:  # pragma: no cover - defensive safeguard
        status = "unhealthy"
        detail = f"probe failed: {exc}"

    latency = (time.perf_counter() - started) * 1000
    result = _format_result(
        "a2a",
        status,
        latency,
        detail=detail,
        last_checked_at=timestamp,
    )
    result["agent"] = agent_name
    return result


def _execute_a2a_probe(agent_name: str) -> None:
    async def _probe() -> None:
        service = get_a2a_service()
        resolved = service.resolve_agent(agent=agent_name)
        await service.gateway.fetch_agent_card(resolved, raise_on_failure=True)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(_probe())
        return

    asyncio.run_coroutine_threadsafe(_probe(), loop).result()
