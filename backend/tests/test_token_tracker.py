from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.agents.token_tracker import TokenTracker


def test_manual_pricing_skips_litellm(monkeypatch: pytest.MonkeyPatch) -> None:
    tracker = TokenTracker()
    completion = SimpleNamespace(
        model="openai/GLM-4.5-Air",
        usage=SimpleNamespace(
            prompt_tokens=1000, completion_tokens=500, total_tokens=1500
        ),
    )

    def _unexpected_call(*_args, **_kwargs):
        raise AssertionError("litellm.completion_cost should not run for manual models")

    monkeypatch.setattr(
        "app.agents.token_tracker.litellm.completion_cost",
        _unexpected_call,
    )

    assert tracker.calculate_cost(completion) == Decimal("0.001250")
