from uuid import uuid4

import pytest

from app.features.invoke import guard as invoke_guard
from app.schemas.a2a_invoke import A2AAgentInvokeRequest


def test_build_invoke_guard_key_normalizes_query_and_uses_conversation_or_context() -> (
    None
):
    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "  run   task  ",
            "conversationId": str(uuid4()),
            "contextId": " ctx-1 ",
            "metadata": {},
        }
    )

    guard_key = invoke_guard.build_invoke_guard_key(
        user_id=uuid4(),
        agent_id=uuid4(),
        agent_source="shared",
        payload=payload,
    )

    assert guard_key is not None
    assert "run task" in guard_key
    assert ":ctx-1:" in guard_key


@pytest.mark.asyncio
async def test_try_acquire_invoke_guard_rejects_duplicate_until_release() -> None:
    invoke_guard.reset_invoke_guard_state()
    guard_key = "user:shared:agent:conv::run"

    assert await invoke_guard.try_acquire_invoke_guard(guard_key) is True
    assert await invoke_guard.try_acquire_invoke_guard(guard_key) is False
    assert invoke_guard.snapshot_invoke_guard_keys() == {guard_key: 1}

    await invoke_guard.release_invoke_guard(guard_key)

    assert invoke_guard.snapshot_invoke_guard_keys() == {}
