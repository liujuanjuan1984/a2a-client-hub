import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.features.agents.personal import router as personal_agent_router


def test_proxy_requires_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", [])

    with pytest.raises(HTTPException) as exc:
        personal_agent_router._normalize_card_url("https://example.com/agent-card.json")

    assert exc.value.status_code == 403


def test_proxy_allows_exact_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["example.com"])

    assert (
        personal_agent_router._normalize_card_url("https://example.com/agent-card.json")
        == "https://example.com/agent-card.json"
    )


def test_proxy_allows_subdomain_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["*.example.com"])

    assert (
        personal_agent_router._normalize_card_url("https://api.example.com/card")
        == "https://api.example.com/card"
    )


def test_proxy_blocks_private_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "a2a_proxy_allowed_hosts", ["127.0.0.1"])

    with pytest.raises(HTTPException) as exc:
        personal_agent_router._normalize_card_url("http://127.0.0.1:8000/card")

    assert exc.value.status_code == 403
