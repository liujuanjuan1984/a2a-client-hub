"""A2A integration package for Compass."""

from app.integrations.a2a_client.types import ResolvedAgent


def get_a2a_service() -> object:
    from app.integrations.a2a_client.service import get_a2a_service as _get

    return _get()


async def shutdown_a2a_service() -> None:
    from app.integrations.a2a_client.service import shutdown_a2a_service as _shutdown

    await _shutdown()


__all__ = ["ResolvedAgent", "get_a2a_service", "shutdown_a2a_service"]
