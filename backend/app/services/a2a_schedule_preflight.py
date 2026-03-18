"""Preflight diagnostics for scheduled A2A executions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.integrations.a2a_client.gateway import A2AGateway


async def run_schedule_availability_preflight(
    *,
    gateway: "A2AGateway",
    runtime: Any,
) -> None:
    """Probe downstream availability before starting a scheduled invoke.

    This keeps schedule preflight deliberately narrow: fetch the latest agent
    card, re-resolve transport compatibility, and fail fast when metadata is no
    longer reachable or compatible.
    """

    await gateway.fetch_agent_card_detail(
        resolved=runtime.resolved,
        raise_on_failure=True,
        use_temporary_client=True,
        card_fetch_timeout=5.0,
    )


__all__ = ["run_schedule_availability_preflight"]
