from app.agents.service_types import LlmInvocationOverrides
from app.agents.services.streaming import StreamingManager
from app.core.config import settings


class _DummyLLMClient:
    def build_params(self, **kwargs):
        return dict(kwargs)


_DUMMY_TOKEN_TRACKER = object()


def _make_manager():
    return StreamingManager(
        llm_client=_DummyLLMClient(),
        token_tracker=_DUMMY_TOKEN_TRACKER,
        model="gpt-4o",
        temperature=0.1,
        max_tokens=1024,
        timeout=30,
        error_cls=RuntimeError,
        sanitize_tool_runs=lambda runs: runs,
    )


def test_build_litellm_params_injects_custom_provider():
    manager = _make_manager()
    overrides = LlmInvocationOverrides(
        token_source="user",
        provider="google",
        api_key="byot-key",
        api_base="https://example.com/v1",
        model_override="google/gemini-2.0-flash",
    )

    params = manager.build_litellm_params(
        messages=[{"role": "user", "content": "hi"}],
        metadata={"message_id": "abc"},
        overrides=overrides,
    )

    assert params["api_key"] == "byot-key"
    assert params["api_base"] == "https://example.com/v1"
    assert params["model"] == "google/gemini-2.0-flash"
    assert params["metadata"]["message_id"] == "abc"
    assert params["metadata"]["llm_token_source"] == "user"
    assert params["metadata"]["llm_provider"] == "google"


def test_build_litellm_params_skips_provider_without_overrides():
    manager = _make_manager()

    params = manager.build_litellm_params(
        messages=[{"role": "user", "content": "hello"}],
        metadata={"foo": "bar"},
    )

    assert params["metadata"]["foo"] == "bar"


def test_build_litellm_params_adds_openrouter_headers(monkeypatch):
    manager = _make_manager()
    monkeypatch.setattr(settings, "frontend_base_url", "https://app.example")
    monkeypatch.setattr(settings, "app_name", "Common Compass")

    overrides = LlmInvocationOverrides(
        token_source="user",
        provider="custom",
        api_key="token",
        api_base="https://openrouter.ai/api/v1",
    )

    params = manager.build_litellm_params(
        messages=[{"role": "user", "content": "hello"}],
        metadata={"foo": "bar"},
        overrides=overrides,
    )

    assert params["extra_headers"]["HTTP-Referer"] == "https://app.example"
    assert params["extra_headers"]["X-Title"] == "Common Compass"
