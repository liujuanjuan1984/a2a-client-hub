from types import SimpleNamespace

import pytest

from app.agents.llm.client import LLMClient
from app.core.config import settings


def _build_response(tool_name):
    function = SimpleNamespace(name=tool_name, arguments="{}")
    tool_call = SimpleNamespace(function=function)
    message = SimpleNamespace(tool_calls=[tool_call])
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


@pytest.mark.asyncio
async def test_llm_client_retries_invalid_tool_names(monkeypatch):
    attempts = []
    responses = [
        _build_response(""),
        _build_response("search_tool"),
    ]

    async def fake_acompletion(**kwargs):
        attempts.append(kwargs)
        return responses[len(attempts) - 1]

    monkeypatch.setattr(
        "app.agents.llm.client.litellm.acompletion",
        fake_acompletion,
    )
    monkeypatch.setattr(settings, "agent_tool_name_retry_attempts", 3)
    monkeypatch.setattr(settings, "agent_tool_name_retry_delay_seconds", 0.0)

    client = LLMClient()
    result = await client.completion(messages=[])

    assert len(attempts) == 2
    assert result.choices[0].message.tool_calls[0].function.name == "search_tool"


@pytest.mark.asyncio
async def test_llm_client_stops_after_max_retries(monkeypatch):
    attempts = 0

    async def fake_acompletion(**kwargs):
        nonlocal attempts
        attempts += 1
        return _build_response("")

    monkeypatch.setattr(
        "app.agents.llm.client.litellm.acompletion",
        fake_acompletion,
    )
    monkeypatch.setattr(settings, "agent_tool_name_retry_attempts", 2)
    monkeypatch.setattr(settings, "agent_tool_name_retry_delay_seconds", 0.0)

    client = LLMClient()
    result = await client.completion(messages=[])

    assert attempts == 2
    assert result.choices[0].message.tool_calls[0].function.name == ""


@pytest.mark.asyncio
async def test_llm_client_does_not_retry_streaming(monkeypatch):
    attempts = 0

    async def fake_acompletion(**kwargs):
        nonlocal attempts
        attempts += 1

        async def _aiter():
            yield {"choices": []}

        return _aiter()

    monkeypatch.setattr(
        "app.agents.llm.client.litellm.acompletion",
        fake_acompletion,
    )

    client = LLMClient()
    stream = await client.completion(messages=[], stream=True)

    assert attempts == 1
    assert hasattr(stream, "__anext__")
