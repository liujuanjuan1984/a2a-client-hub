from __future__ import annotations

from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services import health as health_service


@pytest.fixture(autouse=True)
def _reset_llm_cache() -> None:  # pragma: no cover - fixture
    with health_service._llm_probe_lock:
        health_service._llm_probe_cache["result"] = None
        health_service._llm_probe_cache["expires_at"] = 0.0
    yield
    with health_service._llm_probe_lock:
        health_service._llm_probe_cache["result"] = None
        health_service._llm_probe_cache["expires_at"] = 0.0


@pytest.fixture(autouse=True)
def _mock_core_probes(monkeypatch: pytest.MonkeyPatch) -> None:
    timestamp = "2025-01-01T00:00:00Z"

    def healthy_probe(name: str) -> Dict[str, Any]:
        return {
            "name": name,
            "status": "healthy",
            "latency_ms": 0.1,
            "last_checked_at": timestamp,
        }

    monkeypatch.setattr(
        health_service,
        "_check_database",
        lambda: healthy_probe("database"),
    )
    monkeypatch.setattr(
        health_service,
        "_check_a2a",
        lambda: healthy_probe("a2a"),
    )


def test_health_endpoint_returns_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "health_llm_active_probe_enabled", False)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] in {"healthy", "degraded"}
    assert data["version"] == settings.app_version
    assert "timestamp" in data
    checks = {check["name"]: check for check in data["checks"]}
    assert {"database", "llm", "a2a"}.issubset(checks.keys())
    assert response.headers.get("X-Request-ID")


def test_health_endpoint_database_failure_returns_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_db_probe() -> Dict[str, Any]:
        return {
            "name": "database",
            "status": "unhealthy",
            "latency_ms": 0.1,
            "detail": "forced failure",
            "last_checked_at": "2025-01-01T00:00:00Z",
        }

    healthy_probe = {
        "name": "a2a",
        "status": "healthy",
        "latency_ms": 0.1,
        "last_checked_at": "2025-01-01T00:00:00Z",
    }

    monkeypatch.setattr(health_service, "_check_database", failing_db_probe)
    monkeypatch.setattr(health_service, "_check_a2a", lambda: dict(healthy_probe))
    monkeypatch.setattr(
        health_service, "_check_llm", lambda: dict(healthy_probe, name="llm")
    )

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "unhealthy"


def test_health_endpoint_llm_active_probe_uses_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "litellm_api_key", "test-key")
    monkeypatch.setattr(settings, "health_llm_active_probe_enabled", True)
    monkeypatch.setattr(settings, "health_llm_active_probe_ttl_seconds", 60)

    call_count = {"count": 0}

    def fake_list_models(module: Any) -> Any:
        call_count["count"] += 1
        return {"data": []}

    monkeypatch.setattr(health_service, "_list_models", fake_list_models)

    with TestClient(app) as client:
        response_first = client.get("/health")
        response_second = client.get("/health")

    assert response_first.status_code == 200
    assert response_second.status_code == 200
    assert call_count["count"] == 1
