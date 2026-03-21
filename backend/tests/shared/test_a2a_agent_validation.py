from typing import Type

import pytest

from app.features.agents_shared.common import AgentValidationMixin


class DummyValidationException(Exception):
    pass


class DummyAgentService(AgentValidationMixin):
    _validation_error_cls: Type[Exception] = DummyValidationException
    _allowed_auth_types = {"none", "bearer"}


@pytest.fixture
def agent_service() -> DummyAgentService:
    return DummyAgentService()


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost",
        "http://localhost:8000/",
        "http://127.0.0.1/abc",
        "http://192.168.1.1",
        "http://169.254.169.254",
        "http://10.0.0.1",
    ],
)
def test_normalize_card_url_blocks_internal_ips(
    agent_service: DummyAgentService, url: str
) -> None:
    with pytest.raises(DummyValidationException) as exc:
        agent_service._normalize_card_url(url)
    assert "not allowed" in str(exc.value) or "private or reserved" in str(exc.value)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/card",
        "http://some-public-domain.org",
        "https://1.1.1.1",
    ],
)
def test_normalize_card_url_allows_public_ips(
    agent_service: DummyAgentService, url: str
) -> None:
    normalized = agent_service._normalize_card_url(url)
    assert normalized == url
