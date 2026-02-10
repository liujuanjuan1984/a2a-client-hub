import pytest

from app.core.config import settings
from app.services.a2a_agent_card_validation import fetch_and_validate_agent_card
from app.services.a2a_invoke_service import A2AInvokeService


class _DummyCard:
    def model_dump(self, **kwargs):
        return {"name": "dummy"}


class _DummyGateway:
    async def fetch_agent_card_detail(self, **kwargs):
        return _DummyCard()


@pytest.mark.asyncio
async def test_fetch_and_validate_agent_card_validation_errors_gated(monkeypatch):
    monkeypatch.setattr(
        "app.services.a2a_agent_card_validation.validate_agent_card_payload",
        lambda payload: ["bad-card"],
    )

    monkeypatch.setattr(settings, "debug", False)
    resp = await fetch_and_validate_agent_card(gateway=_DummyGateway(), resolved=object())
    assert resp.validation_errors is None

    monkeypatch.setattr(settings, "debug", True)
    resp_debug = await fetch_and_validate_agent_card(
        gateway=_DummyGateway(), resolved=object()
    )
    assert resp_debug.validation_errors == ["bad-card"]


def test_serialize_stream_event_validation_errors_gated(monkeypatch):
    class _DummyEvent:
        def model_dump(self, **kwargs):
            return {"content": "ok"}

    validate_message = lambda payload: ["bad-event"]  # noqa: E731

    monkeypatch.setattr(settings, "debug", False)
    payload = A2AInvokeService.serialize_stream_event(
        _DummyEvent(), validate_message=validate_message
    )
    assert "validation_errors" not in payload

    monkeypatch.setattr(settings, "debug", True)
    payload_debug = A2AInvokeService.serialize_stream_event(
        _DummyEvent(), validate_message=validate_message
    )
    assert payload_debug["validation_errors"] == ["bad-event"]

