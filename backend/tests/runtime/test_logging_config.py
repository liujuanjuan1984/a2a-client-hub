import logging

from app.core.config import settings
from app.core.logging import (
    JsonFormatter,
    RequestIdFilter,
    TextFormatter,
    clear_actor_context,
    reset_actor_context,
)


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
    record.principal_user_id = "-"
    record.actor_type = "-"
    record.admin_mode = None
    record.taskName = "Task-2"

    rendered = formatter.format(record)

    assert "INFO app.runtime.scheduler" in rendered
    assert (
        "[request_id=- user_id=- principal_user_id=- actor_type=- "
        "admin_mode=- taskName=Task-2]" in rendered
    )
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
    record.principal_user_id = "-"
    record.actor_type = "-"
    record.admin_mode = None
    record.taskName = "Task-2"

    rendered = formatter.format(record)

    assert '"logger": "app.runtime.scheduler"' in rendered
    assert '"message": "APScheduler started."' in rendered
    assert '"taskName": "Task-2"' in rendered


def test_request_id_filter_injects_actor_context_defaults() -> None:
    record = logging.LogRecord(
        name="app.runtime.scheduler",
        level=logging.INFO,
        pathname=__file__,
        lineno=44,
        msg="tick",
        args=(),
        exc_info=None,
    )

    tokens = clear_actor_context()
    try:
        RequestIdFilter().filter(record)
    finally:
        reset_actor_context(tokens)

    assert record.request_id == "-"
    assert record.user_id == "-"
    assert record.principal_user_id == "-"
    assert record.actor_type == "-"
    assert record.admin_mode is None


def test_log_format_setting_defaults_to_text() -> None:
    assert type(settings).model_fields["log_format"].default == "text"


def test_log_format_accepts_explicit_json_and_text_values() -> None:
    original_log_format = settings.log_format
    try:
        settings.log_format = "json"
        assert settings.log_format == "json"
        settings.log_format = "text"
        assert settings.log_format == "text"
    finally:
        settings.log_format = original_log_format
