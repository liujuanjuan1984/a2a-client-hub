"""Service facade coordinating A2A client access for a2a-client-hub."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.core.config import settings as app_settings
from app.core.logging import get_logger
from app.integrations.a2a_client.config import A2ASettings, load_settings
from app.integrations.a2a_client.gateway import A2AGateway
from app.utils.logging_redaction import redact_url_for_logging

logger = get_logger(__name__)


@dataclass(frozen=True)
class ResolvedAgent:
    """Concrete agent information used for invocation."""

    name: str
    url: str
    description: Optional[str]
    metadata: Dict[str, Any]
    headers: Dict[str, str]


class A2AService:
    """Orchestrates configuration, client caching and invocation helpers."""

    def __init__(self, settings: A2ASettings) -> None:
        self.settings = settings
        self.gateway = A2AGateway(settings)

    async def call_agent(
        self,
        *,
        resolved: ResolvedAgent,
        query: str,
        context_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        timeout_override: Optional[float] = None
        metadata_timeout = resolved.metadata.get("timeout_seconds")
        if isinstance(metadata_timeout, (int, float)) and metadata_timeout > 0:
            timeout_override = float(metadata_timeout)
        logger.info(
            "Invoking A2A agent via service",
            extra={
                "agent_name": resolved.name,
                "agent_url": redact_url_for_logging(resolved.url),
            },
        )
        return await self.gateway.invoke(
            resolved=resolved,
            query=query,
            context_id=context_id,
            metadata=metadata,
            timeout=timeout_override,
        )


_service_instance: Optional[A2AService] = None


def get_a2a_service() -> A2AService:
    global _service_instance
    if _service_instance is None:
        settings = load_settings(app_settings)
        _service_instance = A2AService(settings)
    return _service_instance


async def shutdown_a2a_service() -> None:
    global _service_instance
    if _service_instance is None:
        return
    await _service_instance.gateway.shutdown()
    _service_instance = None


__all__ = [
    "A2AService",
    "ResolvedAgent",
    "get_a2a_service",
    "shutdown_a2a_service",
]
