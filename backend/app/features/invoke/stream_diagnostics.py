from __future__ import annotations

from typing import Any, Callable, cast

from app.utils.logging_redaction import redact_sensitive_value

ValidateMessageFn = Callable[[dict[str, Any]], list[Any]]

_LOG_SAMPLE_MAX_DEPTH = 6
_LOG_SAMPLE_MAX_DICT_ITEMS = 20
_LOG_SAMPLE_MAX_LIST_ITEMS = 8
_LOG_SAMPLE_MAX_STRING_LENGTH = 160
_LOG_SAMPLE_SENSITIVE_KEYWORDS = (
    "authorization",
    "cookie",
    "token",
    "ticket",
    "secret",
    "api-key",
    "apikey",
    "password",
    "access_token",
    "refresh_token",
    "api_key",
    "x-api-key",
)


def extract_stream_content_validation_errors(
    payload: dict[str, Any], *, validate_message: ValidateMessageFn
) -> list[str]:
    if not any(
        field in payload for field in ("artifactUpdate", "message", "statusUpdate")
    ):
        return []
    return [str(item) for item in validate_message(payload)]


def _truncate_log_string(value: str) -> str:
    if len(value) <= _LOG_SAMPLE_MAX_STRING_LENGTH:
        return value
    remaining = len(value) - _LOG_SAMPLE_MAX_STRING_LENGTH
    return value[:_LOG_SAMPLE_MAX_STRING_LENGTH] + f"...<truncated:{remaining} chars>"


def _sanitize_log_sample(
    value: Any,
    *,
    key_path: tuple[str, ...] = (),
    depth: int = 0,
) -> Any:
    if depth >= _LOG_SAMPLE_MAX_DEPTH:
        return "<max_depth_exceeded>"

    last_key = key_path[-1].lower() if key_path else ""
    if any(keyword in last_key for keyword in _LOG_SAMPLE_SENSITIVE_KEYWORDS):
        if isinstance(value, str):
            return redact_sensitive_value(value) or "<redacted>"
        return "<redacted>"

    if value is None or isinstance(value, (bool, int, float)):
        return value

    if isinstance(value, str):
        return _truncate_log_string(value)

    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        items = list(value.items())
        for key, child in items[:_LOG_SAMPLE_MAX_DICT_ITEMS]:
            key_str = str(key)
            sanitized[key_str] = _sanitize_log_sample(
                child,
                key_path=(*key_path, key_str),
                depth=depth + 1,
            )
        remaining = len(items) - _LOG_SAMPLE_MAX_DICT_ITEMS
        if remaining > 0:
            sanitized["__truncated_keys__"] = remaining
        return sanitized

    if isinstance(value, list):
        sanitized_list = [
            _sanitize_log_sample(
                child,
                key_path=key_path,
                depth=depth + 1,
            )
            for child in value[:_LOG_SAMPLE_MAX_LIST_ITEMS]
        ]
        remaining = len(value) - _LOG_SAMPLE_MAX_LIST_ITEMS
        if remaining > 0:
            sanitized_list.append(f"<truncated_items:{remaining}>")
        return sanitized_list

    if isinstance(value, tuple):
        return _sanitize_log_sample(
            list(value),
            key_path=key_path,
            depth=depth,
        )

    return _truncate_log_string(repr(value))


def build_stream_content_log_sample(payload: dict[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], _sanitize_log_sample(payload))


def build_validation_errors_log_sample(validation_errors: list[str]) -> list[str]:
    return [
        _truncate_log_string(item)
        for item in validation_errors[:_LOG_SAMPLE_MAX_LIST_ITEMS]
    ]


def warn_non_contract_stream_content_once(
    *,
    seen_reasons: set[str],
    reason: str | None,
    payload: dict[str, Any],
    log_warning: Callable[..., Any] | None,
    log_info: Callable[..., Any] | None,
    log_extra: dict[str, Any],
) -> None:
    if reason is None or reason in seen_reasons:
        return
    seen_reasons.add(reason)
    warning_payload = {
        **log_extra,
        "drop_reason": reason,
        "stream_content_sample": build_stream_content_log_sample(payload),
    }
    if callable(log_warning):
        log_warning(
            "Dropped non-contract stream content event",
            extra=warning_payload,
        )
        return
    if callable(log_info):
        log_info(
            "Dropped non-contract stream content event",
            extra=warning_payload,
        )
