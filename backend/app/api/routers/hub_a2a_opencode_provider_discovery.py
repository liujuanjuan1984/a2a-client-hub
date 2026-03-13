"""Hub A2A endpoints for OpenCode provider/model discovery."""

from app.api.routers._opencode_provider_discovery_router import (
    create_opencode_provider_discovery_router,
)
from app.services.hub_a2a_runtime import (
    HubA2ARuntimeNotFoundError,
    HubA2ARuntimeValidationError,
    hub_a2a_runtime_builder,
)

router = create_opencode_provider_discovery_router(
    prefix="/a2a/agents",
    build_runtime=hub_a2a_runtime_builder.build,
    runtime_not_found_error=HubA2ARuntimeNotFoundError,
    runtime_validation_error=HubA2ARuntimeValidationError,
    runtime_validation_status_code=403,
    log_scope="Hub A2A",
)

__all__ = ["router"]
