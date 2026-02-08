import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.agents.agent_service import AgentService
from app.agents.context_builder import ContextBuildResult
from app.agents.services.context_pipeline import ContextPipeline
from app.agents.services.prompting import PromptBundle
from app.agents.services.tool_executor import ToolExecutionEngine
from app.core.config import settings


class DummyCard:
    def __init__(self, text_value: str | None, metadata: dict | None = None):
        self._text_value = text_value
        self.metadata = metadata or {}
        self.card_id = "CARD-001"

    def text(self) -> str:
        if self._text_value is None:
            raise ValueError("text lookup failed")
        return self._text_value


class FallbackCard(DummyCard):
    def __init__(self, metadata: dict | None = None):
        super().__init__(text_value=None, metadata=metadata)
        self.content = SimpleNamespace(text="fallback content")


@pytest.fixture
def service(monkeypatch):
    # Speed up perf_counter usage inside the service.
    monkeypatch.setattr("app.agents.agent_service.time.perf_counter", lambda: 1.5)
    return AgentService()


def test_card_to_message_preserves_content_and_metadata(service):
    metadata = {"role": "user", "created_at": "2025-10-13T07:30:00Z"}
    card = DummyCard("hello world", metadata)

    message = ContextPipeline._card_to_message(card, source="context_box")

    assert message is not None
    assert message.role == "user"
    assert message.content == "hello world"
    assert message.source == "context_box"
    assert message.metadata == metadata


def test_card_to_message_uses_fallback_content(service):
    metadata = {"role": "assistant"}
    card = FallbackCard(metadata)

    message = ContextPipeline._card_to_message(card, source="context_box")

    assert message is not None
    assert message.role == "assistant"
    assert message.content == "fallback content"


def test_card_to_message_skips_empty_content(service):
    card = DummyCard(" \n", {"role": "system"})

    message = ContextPipeline._card_to_message(card, source="context_box")

    assert message is None


def test_parse_iso_datetime_handles_various_inputs(monkeypatch):
    expected = datetime(2025, 10, 14, 12, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(
        "app.agents.services.context_pipeline.utc_now", lambda: expected
    )

    parser = ContextPipeline._parse_iso_datetime

    assert parser(expected) == expected
    same = parser("2025-10-14T12:00:00")
    assert same.tzinfo == timezone.utc
    fallback = parser("invalid")
    assert fallback == expected


def test_build_tool_event_payload_includes_optional_fields():
    record = {
        "tool_call_id": "tc_1",
        "tool_name": "search",
        "sequence": 2,
        "status": "completed",
        "started_at": "start",
        "finished_at": "end",
        "duration_ms": 150,
        "message": "ok",
        "progress": {"step": 3},
        "arguments": {"query": "hello"},
    }

    engine = ToolExecutionEngine(tool_policy=None)
    payload = engine.build_tool_event_payload(
        record, include_arguments=True, extra_field="value"
    )

    assert payload["tool_call_id"] == "tc_1"
    assert payload["arguments"] == {"query": "hello"}
    assert payload["extra_field"] == "value"


def test_compose_tool_failure_message_formats_entries():
    engine = ToolExecutionEngine(tool_policy=None)
    failures = [
        {"tool": "search", "reason": "timeout"},
        {"tool": "calendar", "reason": "bad input"},
    ]

    message = engine.compose_tool_failure_message(failures)

    assert "search" in message
    assert "calendar" in message


def test_prepare_context_injects_temporal_directive(monkeypatch):
    service = AgentService()
    user_id = uuid4()

    bundle = PromptBundle(prompt="BASE", version="v1")
    monkeypatch.setattr(
        service.prompting_service,
        "build_system_prompt",
        lambda language, profile: bundle,
    )

    captured: dict = {}

    def _fake_build_context(**kwargs):
        captured["system_prompt"] = kwargs["system_prompt"]
        return ContextBuildResult(
            messages=[{"role": "system", "content": kwargs["system_prompt"]}],
            selected_history=[],
            dropped_history=[],
            token_usage={},
        )

    service.context_builder = SimpleNamespace(build_context=_fake_build_context)

    directive = (
        "Temporal directive: Current datetime at the user's location is "
        "2025-12-02T12:00:00+08:00 (timezone: Asia/Shanghai). "
        "Use this reference to interpret relative time expressions such as 今天/明天/这个周末."
    )

    result = service._prepare_conversation_context(
        user_id=user_id,
        user_message="hi",
        conversation_history=[],
        language="zh",
        agent_profile=None,
        datetime_directive=directive,
    )

    assert directive in captured["system_prompt"]
    assert isinstance(result, ContextBuildResult)


def test_resolve_datetime_directive(monkeypatch):
    service = AgentService()
    user_id = uuid4()

    async def fake_timezone(*args, **kwargs):
        return "Asia/Shanghai"

    monkeypatch.setattr(
        "app.agents.agent_service.user_preferences_service.get_user_timezone",
        fake_timezone,
    )
    fixed_now = datetime(2025, 12, 2, 4, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("app.agents.agent_service.utc_now", lambda: fixed_now)

    directive = asyncio.run(service._resolve_datetime_directive(object(), user_id))
    assert directive is not None
    assert "Temporal directive" in directive
    assert "Asia/Shanghai" in directive


def test_agent_service_respects_agent_max_tool_rounds_setting(monkeypatch):
    monkeypatch.setattr(settings, "agent_max_tool_rounds", 9, raising=False)
    service = AgentService()
    assert service.max_tool_rounds == 9
