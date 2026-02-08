from __future__ import annotations

from app.middleware.debug_logging import (
    redact_headers_for_logging,
    redact_query_params_for_logging,
)


def test_redact_headers_for_logging_masks_sensitive_headers() -> None:
    headers = {
        "Authorization": "Bearer abc.def.ghi",
        "Cookie": "cc_refresh_token=abc",
        "X-API-Key": "secret",
        "Content-Type": "application/json",
    }
    redacted = redact_headers_for_logging(headers)
    assert redacted["Authorization"] == "<redacted>"
    assert redacted["Cookie"] == "<redacted>"
    assert redacted["X-API-Key"] == "<redacted>"
    assert redacted["Content-Type"] == "application/json"


def test_redact_query_params_for_logging_masks_sensitive_params() -> None:
    params = {
        "ticket": "abc",
        "access_token": "abc",
        "q": "hello",
    }
    redacted = redact_query_params_for_logging(params)
    assert redacted["ticket"] == "<redacted>"
    assert redacted["access_token"] == "<redacted>"
    assert redacted["q"] == "hello"
