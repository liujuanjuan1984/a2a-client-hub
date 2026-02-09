"""A2A extension endpoints for OpenCode session query (hub catalog agents)."""

from __future__ import annotations

from app.api.routers._opencode_extension_router import create_opencode_extension_router
from app.services.hub_a2a_runtime import (
    HubA2ARuntimeNotFoundError,
    HubA2ARuntimeValidationError,
    hub_a2a_runtime_builder,
)

router = create_opencode_extension_router(
    prefix="/a2a/agents",
    build_runtime=hub_a2a_runtime_builder.build,
    runtime_not_found_error=HubA2ARuntimeNotFoundError,
    runtime_validation_error=HubA2ARuntimeValidationError,
    runtime_validation_status_code=502,
    log_scope="Hub",
)

__all__ = ["router"]
