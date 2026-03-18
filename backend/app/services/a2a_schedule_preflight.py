"""Preflight diagnostics for scheduled A2A executions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.integrations.a2a_client.gateway import A2AGateway


async def run_schedule_agent_card_preflight(
    *,
    gateway: "A2AGateway",
    runtime: Any,
) -> None:
    """Run a narrow Agent Card preflight before a scheduled invoke.

    This is intentionally not a full upstream health check. It only confirms
    that the latest Agent Card is reachable within a short timeout and that the
    current client can still resolve a compatible transport from that card.
    """

    await gateway.fetch_agent_card_detail(
        resolved=runtime.resolved,
        raise_on_failure=True,
        use_temporary_client=True,
        card_fetch_timeout=5.0,
    )


__all__ = ["run_schedule_agent_card_preflight"]
