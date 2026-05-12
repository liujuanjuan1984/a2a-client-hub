"""A2A extension endpoints for session/interrupt capabilities."""

from __future__ import annotations

from typing import Any, Callable

from app.api.routing import StrictAPIRouter
from app.features.agents.personal.runtime import (
    A2ARuntimeNotFoundError,
    A2ARuntimeValidationError,
    a2a_runtime_builder,
)
from app.features.extension_capabilities.common_router import (
    create_extension_capability_router,
)
from app.integrations.a2a_extensions.service import get_a2a_extensions_service


def create_router(
    *,
    extensions_service_getter: Callable[[], Any] = get_a2a_extensions_service,
) -> StrictAPIRouter:
    return create_extension_capability_router(
        prefix="/me/a2a/agents",
        build_runtime=a2a_runtime_builder.build,
        runtime_not_found_error=A2ARuntimeNotFoundError,
        runtime_validation_error=A2ARuntimeValidationError,
        runtime_validation_status_code=400,
        log_scope="",
        extensions_service_getter=extensions_service_getter,
    )


router = create_router()
