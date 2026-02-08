"""A2A extension integration package.

This package implements "framework-lite" support for A2A Agent Card extensions.
It focuses on safe discovery + contract validation + transport-specific invocation.
"""

from app.integrations.a2a_extensions.service import (
    get_a2a_extensions_service,
    shutdown_a2a_extensions_service,
)

__all__ = ["get_a2a_extensions_service", "shutdown_a2a_extensions_service"]

