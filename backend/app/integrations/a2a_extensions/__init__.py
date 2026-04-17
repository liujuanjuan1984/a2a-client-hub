"""A2A extension integration package.

This package implements "framework-lite" support for A2A Agent Card extensions.
It focuses on safe discovery + contract validation + transport-specific invocation.
"""


def get_a2a_extensions_service() -> object:
    from app.integrations.a2a_extensions.service import get_a2a_extensions_service

    return get_a2a_extensions_service()


async def shutdown_a2a_extensions_service() -> None:
    from app.integrations.a2a_extensions.service import (
        shutdown_a2a_extensions_service,
    )

    await shutdown_a2a_extensions_service()
