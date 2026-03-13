"""A2A endpoints for OpenCode provider/model discovery."""

from app.api.routers._opencode_provider_discovery_router import (
    create_opencode_provider_discovery_router,
)
from app.services.a2a_runtime import (
    A2ARuntimeNotFoundError,
    A2ARuntimeValidationError,
    a2a_runtime_builder,
)

router = create_opencode_provider_discovery_router(
    prefix="/me/a2a/agents",
    build_runtime=a2a_runtime_builder.build,
    runtime_not_found_error=A2ARuntimeNotFoundError,
    runtime_validation_error=A2ARuntimeValidationError,
    runtime_validation_status_code=400,
    log_scope="A2A",
)

__all__ = ["router"]
