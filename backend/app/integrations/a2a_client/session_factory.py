"""Invoke-session factory for shared and ephemeral A2A execution paths."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator, Awaitable, Callable

from app.integrations.a2a_client.errors import A2AClientResetRequiredError
from app.integrations.a2a_client.invoke_session import (
    A2AInvokeSession,
    AgentResolutionPolicy,
    AgentSnapshotSource,
    InvokeSessionOwnership,
    ResolvedAgentSnapshot,
)
from app.utils.async_cleanup import await_cancel_safe
from app.utils.timezone_util import utc_now

if TYPE_CHECKING:  # pragma: no cover - import for typing only
    from app.integrations.a2a_client.client import A2AClient

    from .types import ResolvedAgent


class A2AInvokeSessionFactory:
    """Build invoke sessions with explicit shared or ephemeral ownership."""

    def __init__(
        self,
        *,
        shared_client_getter: Callable[["ResolvedAgent"], Awaitable["A2AClient"]],
        shared_client_invalidator: Callable[["ResolvedAgent"], Awaitable[None]],
        ephemeral_client_builder: Callable[..., "A2AClient"],
    ) -> None:
        self._shared_client_getter = shared_client_getter
        self._shared_client_invalidator = shared_client_invalidator
        self._ephemeral_client_builder = ephemeral_client_builder

    @asynccontextmanager
    async def open_session(
        self,
        *,
        resolved: "ResolvedAgent",
        policy: AgentResolutionPolicy,
        card_fetch_timeout: float | None = None,
    ) -> AsyncIterator[A2AInvokeSession]:
        uses_shared_client = policy == AgentResolutionPolicy.CACHED_SHARED
        client = (
            await self._shared_client_getter(resolved)
            if uses_shared_client
            else self._ephemeral_client_builder(
                resolved,
                card_fetch_timeout=card_fetch_timeout,
            )
        )
        try:
            try:
                snapshot = await self._resolve_snapshot(
                    client=client,
                    resolved=resolved,
                    source=(
                        AgentSnapshotSource.SHARED_CACHE
                        if uses_shared_client
                        else AgentSnapshotSource.FRESH_FETCH
                    ),
                    card_fetch_timeout=card_fetch_timeout,
                )
            except A2AClientResetRequiredError:
                if uses_shared_client:
                    await self._shared_client_invalidator(resolved)
                raise
            yield A2AInvokeSession(
                client=client,
                snapshot=snapshot,
                policy=policy,
                ownership=(
                    InvokeSessionOwnership.SHARED
                    if uses_shared_client
                    else InvokeSessionOwnership.EPHEMERAL
                ),
            )
        finally:
            if not uses_shared_client:
                await await_cancel_safe(client.close())

    async def handle_client_reset(
        self,
        *,
        resolved: "ResolvedAgent",
        session: A2AInvokeSession,
    ) -> None:
        if session.is_shared:
            await self._shared_client_invalidator(resolved)

    async def _resolve_snapshot(
        self,
        *,
        client: "A2AClient",
        resolved: "ResolvedAgent",
        source: AgentSnapshotSource,
        card_fetch_timeout: float | None,
    ) -> ResolvedAgentSnapshot:
        agent_card, peer_descriptor = await client.get_agent_resolution()
        return ResolvedAgentSnapshot(
            resolved=resolved,
            agent_card=agent_card,
            peer_descriptor=peer_descriptor,
            resolved_at=utc_now(),
            source=source,
            card_fetch_timeout=card_fetch_timeout,
        )
