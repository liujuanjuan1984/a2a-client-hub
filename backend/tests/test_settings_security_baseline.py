from __future__ import annotations

import pytest

from app.core.config import Settings


def _set_base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SCHEMA_NAME", "test_a2a_client_hub_schema")
    monkeypatch.setenv("JWT_ALGORITHM", "RS256")
    monkeypatch.setenv(
        "JWT_PRIVATE_KEY_PEM",
        "-----BEGIN PRIVATE KEY-----\nlocal-test\n-----END PRIVATE KEY-----\n",
    )
    monkeypatch.setenv(
        "JWT_PUBLIC_KEY_PEM",
        "-----BEGIN PUBLIC KEY-----\nlocal-test\n-----END PUBLIC KEY-----\n",
    )
    monkeypatch.setenv("JWT_SECRET_KEY", "this-is-a-strong-test-key-1234567890")
    monkeypatch.setenv("WS_TICKET_SECRET_KEY", "another-strong-test-key-1234567890")
    monkeypatch.setenv("AUTH_REFRESH_COOKIE_SECURE", "true")
    monkeypatch.setenv("AUTH_REFRESH_COOKIE_SAMESITE", "lax")
    monkeypatch.setenv("BACKEND_CORS_ORIGINS", '["https://app.example.com"]')
    monkeypatch.setenv("WS_ALLOWED_ORIGINS", '["https://app.example.com"]')
    monkeypatch.setenv("WS_REQUIRE_ORIGIN", "true")
    monkeypatch.setenv("A2A_PROXY_ALLOWED_HOSTS", '["agent.example.com"]')


def test_production_rejects_weak_default_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_base_env(monkeypatch)
    monkeypatch.setenv("JWT_SECRET_KEY", "change-me-32-chars-minimum-secret-key")

    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        Settings()


def test_production_rejects_relaxed_network_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_base_env(monkeypatch)
    monkeypatch.setenv("BACKEND_CORS_ORIGINS", '["http://localhost:3000"]')
    monkeypatch.setenv("WS_ALLOWED_ORIGINS", "[]")
    monkeypatch.setenv("A2A_PROXY_ALLOWED_HOSTS", "[]")

    with pytest.raises(ValueError) as exc_info:
        Settings()

    message = str(exc_info.value)
    assert "BACKEND_CORS_ORIGINS" in message
    assert "WS_ALLOWED_ORIGINS" in message
    assert "A2A_PROXY_ALLOWED_HOSTS" in message


def test_development_allows_localhost_and_dev_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_base_env(monkeypatch)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("JWT_SECRET_KEY", "change-me-32-chars-minimum-secret-key")
    monkeypatch.setenv("WS_TICKET_SECRET_KEY", "change-me-ws-ticket-secret")
    monkeypatch.setenv("AUTH_REFRESH_COOKIE_SECURE", "false")
    monkeypatch.setenv("BACKEND_CORS_ORIGINS", '["http://localhost:3000"]')
    monkeypatch.setenv("WS_ALLOWED_ORIGINS", "[]")
    monkeypatch.setenv("WS_REQUIRE_ORIGIN", "false")
    monkeypatch.setenv("A2A_PROXY_ALLOWED_HOSTS", "[]")

    settings = Settings()

    assert settings.app_env == "development"
