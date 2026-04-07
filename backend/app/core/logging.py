"""Logging configuration for a2a-client-hub."""

import logging
import sys
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from typing import Any, Dict

from app.core.config import settings
from app.utils.json_encoder import json_dumps

_request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
_user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)


class RequestIdFilter(logging.Filter):
    """Inject the current request id into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        record.request_id = _request_id_var.get() or "-"
        record.user_id = _user_id_var.get() or "-"
        return True


class JsonFormatter(logging.Formatter):
    """Render log records as JSON for downstream consumption."""

    reserved_fields = {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
        "request_id",
        "user_id",
    }

    def format(self, record: logging.LogRecord) -> str:  # noqa: D401
        log_entry: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
            "user_id": getattr(record, "user_id", "-"),
        }

        extra = {
            key: value
            for key, value in record.__dict__.items()
            if key not in self.reserved_fields and not key.startswith("_")
        }
        if extra:
            log_entry.update(extra)

        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            log_entry["stack"] = record.stack_info

        return json_dumps(log_entry, default=str)


class TextFormatter(logging.Formatter):
    """Render log records in a compact human-readable format."""

    reserved_fields = JsonFormatter.reserved_fields

    def format(self, record: logging.LogRecord) -> str:  # noqa: D401
        timestamp = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        extra = {
            key: value
            for key, value in record.__dict__.items()
            if key not in self.reserved_fields and not key.startswith("_")
        }

        context_parts = [
            f"request_id={getattr(record, 'request_id', '-')}",
            f"user_id={getattr(record, 'user_id', '-')}",
        ]
        for key in sorted(extra):
            context_parts.append(f"{key}={extra[key]}")

        rendered = (
            f"{timestamp} {record.levelname} {record.name} "
            f"[{' '.join(context_parts)}] {record.getMessage()}"
        )

        if record.exc_info:
            rendered = f"{rendered}\n{self.formatException(record.exc_info)}"
        if record.stack_info:
            rendered = f"{rendered}\n{record.stack_info}"

        return rendered


def set_request_id(request_id: str) -> Token[str | None]:
    """Bind a request id to the current context."""

    return _request_id_var.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    """Reset the request id context."""

    _request_id_var.reset(token)


def clear_user_context() -> Token[str | None]:
    """Clear the current user id context."""

    return _user_id_var.set(None)


def set_user_context(user_id: str | None) -> Token[str | None]:
    """Bind a user id to the current logging context."""

    return _user_id_var.set(user_id)


def reset_user_context(token: Token[str | None]) -> None:
    """Reset the user id context."""

    _user_id_var.reset(token)


def setup_logging() -> None:
    """
    Set up application logging configuration

    This function configures process-wide logging.
    """

    # Clear existing handlers to prevent duplicate output.
    root_logger = logging.getLogger()
    root_logger.handlers.clear()

    formatter: logging.Formatter
    if settings.log_format == "json":
        formatter = JsonFormatter()
    else:
        formatter = TextFormatter()

    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(RequestIdFilter())

    # Configure root logger
    root_logger.setLevel(getattr(logging, settings.log_level.upper()))
    root_logger.addHandler(console_handler)

    # Disable upward propagation on root logger to avoid duplicate records.
    root_logger.propagate = False

    # Configure specific loggers
    app_logger = logging.getLogger("app")
    app_logger.setLevel(logging.DEBUG)
    app_logger.propagate = True  # Allow propagation to the root logger.

    # Ensure SQLAlchemy logs are visible for debugging
    sqlalchemy_logger = logging.getLogger("sqlalchemy.engine")
    sqlalchemy_logger.setLevel(logging.WARNING)
    sqlalchemy_logger.propagate = True

    # Configure uvicorn access logs
    uvicorn_logger = logging.getLogger("uvicorn.access")
    uvicorn_logger.setLevel(logging.INFO)
    uvicorn_logger.propagate = True

    # Suppress verbose upstream agent-card payload logs from a2a sdk.
    card_resolver_logger = logging.getLogger("a2a.client.card_resolver")
    card_resolver_logger.setLevel(logging.WARNING)
    card_resolver_logger.propagate = True


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance with proper configuration

    Args:
        name: Logger name (usually __name__)

    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)
