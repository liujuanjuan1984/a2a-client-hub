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
    resp = await fetch_and_validate_agent_card(
        gateway=_DummyGateway(), resolved=object()
    )
    assert resp.validation_errors is None

    monkeypatch.setattr(settings, "debug", True)
    resp_debug = await fetch_and_validate_agent_card(
        gateway=_DummyGateway(), resolved=object()
    )
    assert resp_debug.validation_errors == ["bad-card"]


@pytest.mark.asyncio
async def test_fetch_and_validate_agent_card_exposes_invalid_session_query_contract() -> (
    None
):
    class _ExtensionCard:
        def model_dump(self, **kwargs):
            return {
                "name": "dummy",
                "description": "dummy",
                "url": "https://example.com",
                "version": "1.0",
                "capabilities": {
                    "extensions": [
                        {
                            "uri": "urn:opencode-a2a:session-query/v1",
                            "params": {
                                "provider": "opencode",
                                "methods": {
                                    "list_sessions": "shared.sessions.list",
                                    "get_session_messages": (
                                        "shared.sessions.messages.list"
                                    ),
                                },
                                "pagination": {
                                    "mode": "page_size",
                                    "default_size": 20,
                                },
                            },
                        }
                    ]
                },
                "defaultInputModes": [],
                "defaultOutputModes": [],
                "skills": [{"id": "s1", "name": "s1", "description": "d", "tags": []}],
            }

    class _ExtensionGateway:
        async def fetch_agent_card_detail(self, **kwargs):
            from a2a.types import AgentCard

            return AgentCard.model_validate(_ExtensionCard().model_dump())

    resp = await fetch_and_validate_agent_card(
        gateway=_ExtensionGateway(), resolved=object()
    )

    assert resp.success is False
    assert resp.shared_session_query is not None
    assert resp.shared_session_query.status == "invalid"
    assert "Shared session query contract is invalid" in resp.message


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
