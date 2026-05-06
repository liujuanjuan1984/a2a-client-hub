from __future__ import annotations

import os

import pytest

from tests.support.env_bootstrap import (
    TEST_BACKEND_ENV_FILE,
    apply_test_environment,
)


def test_apply_test_environment_replaces_ambient_application_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://prod.example.com/prod")
    monkeypatch.setenv("BACKEND_HOST", "0.0.0.0")
    monkeypatch.setenv("JWT_ISSUER", "prod-issuer")
    monkeypatch.setenv("AUTH_REFRESH_COOKIE_SECURE", "true")
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql://localhost/test_db")
    monkeypatch.setenv("TEST_SCHEMA_NAME", "isolated_schema")

    apply_test_environment()

    assert os.environ[TEST_BACKEND_ENV_FILE] == ""
    assert os.environ["APP_ENV"] == "development"
    assert os.environ["DATABASE_URL"] == "postgresql://localhost/test_db"
    assert os.environ["SCHEMA_NAME"] == "isolated_schema"
    assert os.environ["JWT_ISSUER"] == "common-compass-test"
    assert os.environ["AUTH_REFRESH_COOKIE_SECURE"] == "false"
    assert "BACKEND_HOST" not in os.environ


def test_apply_test_environment_uses_local_database_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.delenv("TEST_DATABASE_NAME", raising=False)
    monkeypatch.setenv("USER", "bootstrap-user")

    apply_test_environment()

    assert os.environ["DATABASE_URL"] == "postgresql:///bootstrap-user"
