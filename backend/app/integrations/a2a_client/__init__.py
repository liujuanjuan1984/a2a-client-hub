"""A2A integration package for Compass."""


def get_a2a_service() -> object:
    from app.integrations.a2a_client.service import get_a2a_service

    return get_a2a_service()


async def shutdown_a2a_service() -> None:
    from app.integrations.a2a_client.service import shutdown_a2a_service

    await shutdown_a2a_service()
