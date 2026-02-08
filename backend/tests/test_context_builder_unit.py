from datetime import datetime, timezone

from app.agents.context_builder import ContextBudget, ContextBuilder
from app.agents.conversation_history import ConversationMessage
from app.agents.token_estimator import EstimationResult
from app.core.config import settings


class DummyEstimator:
    def __init__(self, history_token: int = 5):
        self.history_token = history_token

    def estimate_text_tokens(self, text: str, model: str) -> int:
        return len(text)

    def estimate_message_tokens(
        self, message: ConversationMessage, model: str
    ) -> EstimationResult:
        total = len(message.content) + 2
        return EstimationResult(message_tokens=len(message.content), total_tokens=total)


def _make_message(content: str, role: str = "user") -> ConversationMessage:
    return ConversationMessage(
        role=role,
        content=content,
        created_at=datetime(2025, 10, 14, tzinfo=timezone.utc),
        source="conversation",
    )


def test_estimate_history_tokens_respects_budget(monkeypatch):
    builder = ContextBuilder()
    builder._estimator = DummyEstimator()
    history = [
        _make_message("first"),
        _make_message("second"),
        _make_message("third"),
    ]

    selected, dropped, history_tokens = builder._estimate_history_tokens(
        history,
        model="test",
        budget=ContextBudget(max_context_tokens=10, buffer_tokens=0),
    )

    assert [msg.content for msg in selected] == ["third"]
    assert [msg.content for msg in dropped] == ["first", "second"]
    assert history_tokens == len("third") + 2


def test_build_context_trims_when_base_tokens_exceed(monkeypatch):
    builder = ContextBuilder()
    builder._estimator = DummyEstimator()

    monkeypatch.setattr(settings, "litellm_context_window_tokens", 5, raising=False)
    monkeypatch.setattr(settings, "conversation_context_buffer", 1, raising=False)
    monkeypatch.setattr(settings, "conversation_context_budget", 5, raising=False)
    monkeypatch.setattr(settings, "conversation_summary_min_messages", 2, raising=False)

    history = [_make_message("past message", role="assistant")]

    result = builder.build_context(
        user_id=None,
        user_message="user",
        history=history,
        model="gpt",
        system_prompt="sys",
    )

    assert len(result.messages) == 2
    assert result.selected_history == []
    assert result.dropped_history == history
    assert result.summary_candidates == history


def test_build_context_includes_history_within_budget(monkeypatch):
    builder = ContextBuilder()
    builder._estimator = DummyEstimator()

    monkeypatch.setattr(settings, "litellm_context_window_tokens", 60, raising=False)
    monkeypatch.setattr(settings, "conversation_context_buffer", 5, raising=False)
    monkeypatch.setattr(settings, "conversation_context_budget", 60, raising=False)
    monkeypatch.setattr(settings, "conversation_summary_min_messages", 5, raising=False)

    history = [
        _make_message("alpha", role="assistant"),
        _make_message("beta", role="user"),
    ]

    result = builder.build_context(
        user_id=None,
        user_message="hello",
        history=history,
        model="gpt",
        system_prompt="system",
    )

    assert [msg["role"] for msg in result.messages] == [
        "system",
        "assistant",
        "user",
        "user",
    ]
    assert result.selected_history == history
    assert result.dropped_history == []
    assert result.summary_candidates == []
    assert result.token_usage["history_tokens"] == (len("alpha") + 2 + len("beta") + 2)
