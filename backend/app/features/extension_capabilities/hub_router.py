"""A2A extension endpoints for shared session/interrupt capabilities."""

from __future__ import annotations

from app.features.extension_capabilities.common_router import (
    create_extension_capability_router,
)
from app.features.hub_agents.runtime import (
    HubA2ARuntimeNotFoundError,
    HubA2ARuntimeValidationError,
    hub_a2a_runtime_builder,
)

router = create_extension_capability_router(
    prefix="/a2a/agents",
    build_runtime=hub_a2a_runtime_builder.build,
    runtime_not_found_error=HubA2ARuntimeNotFoundError,
    runtime_validation_error=HubA2ARuntimeValidationError,
    runtime_validation_status_code=502,
    log_scope="Hub",
)
