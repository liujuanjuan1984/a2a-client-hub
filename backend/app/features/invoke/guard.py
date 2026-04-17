"""Helpers for guarding duplicate inflight invoke requests."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator, Literal
from uuid import UUID

from app.schemas.a2a_invoke import A2AAgentInvokeRequest

AgentSource = Literal["personal", "shared"]

_invoke_inflight_guard = asyncio.Lock()
_invoke_inflight_keys: dict[str, int] = {}


def normalize_query_for_invoke_guard(query: str) -> str:
    return " ".join(query.split())


def build_invoke_guard_key(
    *,
    user_id: UUID,
    agent_id: UUID,
    agent_source: AgentSource,
    payload: A2AAgentInvokeRequest,
) -> str | None:
    conversation_id = (
        payload.conversation_id.strip()
        if isinstance(payload.conversation_id, str)
        else ""
    )
    if not conversation_id:
        return None
    normalized_query = normalize_query_for_invoke_guard(payload.query)
    return f"{user_id}:{agent_source}:{agent_id}:{conversation_id}::{normalized_query}"


@asynccontextmanager
async def guard_inflight_invoke(guard_key: str | None) -> AsyncIterator[None]:
    if not guard_key:
        yield
        return

    acquired = await try_acquire_invoke_guard(guard_key)
    if not acquired:
        raise ValueError("invoke_inflight")

    try:
        yield
    finally:
        await release_invoke_guard(guard_key)


async def try_acquire_invoke_guard(guard_key: str) -> bool:
    async with _invoke_inflight_guard:
        active_count = _invoke_inflight_keys.get(guard_key, 0)
        if active_count > 0:
            return False
        _invoke_inflight_keys[guard_key] = 1
        return True


async def release_invoke_guard(guard_key: str) -> None:
    async with _invoke_inflight_guard:
        remaining = _invoke_inflight_keys.get(guard_key, 0) - 1
        if remaining <= 0:
            _invoke_inflight_keys.pop(guard_key, None)
        else:
            _invoke_inflight_keys[guard_key] = remaining


def reset_invoke_guard_state() -> None:
    _invoke_inflight_keys.clear()


def snapshot_invoke_guard_keys() -> dict[str, int]:
    return dict(_invoke_inflight_keys)
