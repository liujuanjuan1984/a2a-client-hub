from app.utils.logging_redaction import (
    redact_headers_for_logging,
    redact_query_params_for_logging,
    redact_sensitive_value,
    redact_url_for_logging,
)


def test_redact_sensitive_value():
    assert redact_sensitive_value(None) is None
    assert redact_sensitive_value("") == ""
    assert redact_sensitive_value("short") == "<redacted>"

    val = "verylongsensitivevalue123456"
    redacted = redact_sensitive_value(val)
    assert redacted.startswith("verylo")
    assert "..." in redacted
    assert len(redacted.split("...")[-1]) == 8
    assert val not in redacted


def test_redact_headers_for_logging():
    headers = {
        "Authorization": "Bearer super-secret-token-123456789",
        "X-API-Key": "my-secret-key-123456789",
        "Sec-WebSocket-Protocol": "a" * 48,
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
    }
    redacted = redact_headers_for_logging(headers)

    assert redacted["Authorization"].startswith("Bearer")
    assert "..." in redacted["Authorization"]
    assert redacted["X-API-Key"].startswith("my-sec")
    assert "..." in redacted["Sec-WebSocket-Protocol"]
    assert redacted["Content-Type"] == "application/json"
    assert redacted["User-Agent"] == "Mozilla/5.0"


def test_redact_query_params_for_logging():
    params = {
        "token": "secret-token-123456789",
        "page": "1",
        "q": "search term",
    }
    redacted = redact_query_params_for_logging(params)

    assert redacted["token"].startswith("secret")
    assert "..." in redacted["token"]
    assert redacted["page"] == "1"
    assert redacted["q"] == "search term"


def test_redact_url_for_logging():
    assert (
        redact_url_for_logging(
            "https://user:pass@example.com/path?query=val#frag"  # pragma: allowlist secret
        )
        == "https://example.com"
    )
    assert (
        redact_url_for_logging("http://localhost:8080/foo") == "http://localhost:8080"
    )
    assert redact_url_for_logging("invalid-url") == "invalid-url"
    assert redact_url_for_logging(None) is None
