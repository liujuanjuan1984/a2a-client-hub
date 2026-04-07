import logging

from app.core.config import settings
from app.core.logging import JsonFormatter, TextFormatter


def test_text_formatter_renders_human_readable_context() -> None:
    formatter = TextFormatter()
    record = logging.LogRecord(
        name="app.runtime.scheduler",
        level=logging.INFO,
        pathname=__file__,
        lineno=12,
        msg="APScheduler started.",
        args=(),
        exc_info=None,
    )
    record.request_id = "-"
    record.user_id = "-"
    record.taskName = "Task-2"

    rendered = formatter.format(record)

    assert "INFO app.runtime.scheduler" in rendered
    assert "[request_id=- user_id=- taskName=Task-2]" in rendered
    assert rendered.endswith("APScheduler started.")


def test_json_formatter_preserves_structured_fields() -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="app.runtime.scheduler",
        level=logging.INFO,
        pathname=__file__,
        lineno=28,
        msg="APScheduler started.",
        args=(),
        exc_info=None,
    )
    record.request_id = "-"
    record.user_id = "-"
    record.taskName = "Task-2"

    rendered = formatter.format(record)

    assert '"logger": "app.runtime.scheduler"' in rendered
    assert '"message": "APScheduler started."' in rendered
    assert '"taskName": "Task-2"' in rendered


def test_resolved_log_format_defaults_to_text_outside_production() -> None:
    original_env = settings.app_env
    original_log_format = settings.log_format
    try:
        settings.app_env = "development"
        settings.log_format = "auto"
        assert settings.resolved_log_format == "text"
    finally:
        settings.app_env = original_env
        settings.log_format = original_log_format


def test_resolved_log_format_defaults_to_json_in_production() -> None:
    original_env = settings.app_env
    original_log_format = settings.log_format
    try:
        settings.app_env = "production"
        settings.log_format = "auto"
        assert settings.resolved_log_format == "json"
    finally:
        settings.app_env = original_env
        settings.log_format = original_log_format
