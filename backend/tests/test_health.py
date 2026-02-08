from __future__ import annotations

from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services import health as health_service


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
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["version"] == settings.app_version
    assert "timestamp" in data
    checks = {check["name"]: check for check in data["checks"]}
    assert {"database", "a2a"}.issubset(checks.keys())
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

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "unhealthy"
