"""A2A extension endpoints for shared session/interrupt capabilities."""

from __future__ import annotations

from app.features.agents.shared.runtime import (
    SharedAgentRuntimeNotFoundError,
    SharedAgentRuntimeValidationError,
    shared_agent_runtime_builder,
)
from app.features.extension_capabilities.common_router import (
    create_extension_capability_router,
)

router = create_extension_capability_router(
    prefix="/a2a/agents",
    build_runtime=shared_agent_runtime_builder.build,
    runtime_not_found_error=SharedAgentRuntimeNotFoundError,
    runtime_validation_error=SharedAgentRuntimeValidationError,
    runtime_validation_status_code=502,
    log_scope="Hub",
)
