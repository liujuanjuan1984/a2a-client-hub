import pytest

from app.core.config import _resolve_settings_env_file


def test_settings_env_file_enabled_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("A2A_SETTINGS_DISABLE_ENV_FILE", raising=False)

    assert _resolve_settings_env_file() == ".env"


def test_settings_env_file_can_be_disabled_for_tests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("A2A_SETTINGS_DISABLE_ENV_FILE", "true")

    assert _resolve_settings_env_file() is None
