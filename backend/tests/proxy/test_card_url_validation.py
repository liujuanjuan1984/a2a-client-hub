import pytest
from fastapi import HTTPException

from app.api.routers.card_url_validation import normalize_card_url


def test_normalize_card_url_returns_trimmed_value():
    assert (
        normalize_card_url(
            "  https://example.com/agent.json  ",
            allowed_hosts=["example.com"],
        )
        == "https://example.com/agent.json"
    )


def test_normalize_card_url_rejects_empty_value():
    with pytest.raises(HTTPException) as exc_info:
        normalize_card_url("", allowed_hosts=["example.com"])
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Card URL is required"


def test_normalize_card_url_rejects_non_http_scheme():
    with pytest.raises(HTTPException) as exc_info:
        normalize_card_url(
            "ftp://example.com/agent.json", allowed_hosts=["example.com"]
        )
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Card URL must be http(s)"


def test_normalize_card_url_rejects_disallowed_host():
    with pytest.raises(HTTPException) as exc_info:
        normalize_card_url(
            "https://example.com/agent.json",
            allowed_hosts=["allowed.example.com"],
        )
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == {
        "error_code": "card_url_host_not_allowed",
        "message": "Card URL host is not allowed",
    }
