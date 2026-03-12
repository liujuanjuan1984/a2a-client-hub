"""A2A extension endpoints for shared session/interrupt capabilities."""

from __future__ import annotations

from app.api.routers._extension_capability_router import (
    create_extension_capability_router,
)
from app.services.a2a_runtime import (
    A2ARuntimeNotFoundError,
    A2ARuntimeValidationError,
    a2a_runtime_builder,
)

router = create_extension_capability_router(
    prefix="/me/a2a/agents",
    build_runtime=a2a_runtime_builder.build,
    runtime_not_found_error=A2ARuntimeNotFoundError,
    runtime_validation_error=A2ARuntimeValidationError,
    runtime_validation_status_code=400,
    log_scope="",
)

__all__ = ["router"]
