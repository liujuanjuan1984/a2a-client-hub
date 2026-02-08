from __future__ import annotations

import pytest

from app.utils.outbound_url import OutboundURLNotAllowedError, validate_outbound_http_url


def test_outbound_url_requires_allowlist() -> None:
    with pytest.raises(OutboundURLNotAllowedError):
        validate_outbound_http_url(
            "https://example.com/.well-known/agent-card.json",
            allowed_hosts=[],
            purpose="Agent card URL",
        )


def test_outbound_url_allows_exact_host() -> None:
    assert (
        validate_outbound_http_url(
            "https://example.com/.well-known/agent-card.json",
            allowed_hosts=["example.com"],
            purpose="Agent card URL",
        )
        == "https://example.com/.well-known/agent-card.json"
    )

