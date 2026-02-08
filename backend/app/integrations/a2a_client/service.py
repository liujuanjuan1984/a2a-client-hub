"""Service facade coordinating A2A client access for Compass."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.core.config import settings as app_settings
from app.core.logging import get_logger
from app.integrations.a2a_client.config import A2ASettings, load_settings
from app.integrations.a2a_client.gateway import A2AGateway

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

    def resolve_agent(
        self,
        *,
        agent: Optional[str] = None,
        agent_url: Optional[str] = None,
    ) -> ResolvedAgent:
        logger.info(
            "Resolving A2A agent",
            extra={"configured_agent": agent, "agent_url": agent_url},
        )
        if agent:
            config = self.settings.agents.get(agent)
            if config is None:
                raise ValueError(f"Unknown A2A agent '{agent}'")
            resolved = ResolvedAgent(
                name=config.name,
                url=config.url,
                description=config.description,
                metadata=dict(config.metadata),
                headers=dict(config.headers),
            )
            logger.info(
                "Resolved configured A2A agent",
                extra={
                    "agent": agent,
                    "resolved_name": resolved.name,
                    "resolved_url": resolved.url,
                    "metadata_keys": sorted(resolved.metadata.keys()),
                    "header_keys": sorted(resolved.headers.keys()),
                },
            )
            return resolved

        if agent_url:
            normalized_url = agent_url.strip()
            if not normalized_url:
                raise ValueError("'agent_url' must be a non-empty string")
            resolved = ResolvedAgent(
                name=agent_url,
                url=normalized_url,
                description=None,
                metadata={},
                headers={},
            )
            logger.info(
                "Using direct A2A agent URL",
                extra={"agent_url": normalized_url},
            )
            return resolved

        raise ValueError("Either 'agent' or 'agent_url' must be provided")

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
                "agent_url": resolved.url,
            },
        )
        return await self.gateway.invoke(
            resolved=resolved,
            query=query,
            context_id=context_id,
            metadata=metadata,
            timeout=timeout_override,
        )

    def build_prompt_section(self, language: str = "en") -> str:
        if not self.settings.has_agents:
            return ""

        _ = language  # preserved for backward compatibility

        lines = [
            "A2A tool usage guidelines:",
            "1. Invoke an A2A agent only when cross-system expertise is required; prefer reusing the existing context first.",
            "2. Limit to two consecutive attempts; if both fail to add new value or miss the intent, stop calling tools and summarize with what you have.",
            "3. When a tool response repeats the prior one or is clearly low relevance, explain the issue and answer directly instead of calling again.",
            "4. When a user only asks whether you *can* use an A2A agent, describe the option and ask for permission before running any tool.",
            "",
            "Example:",
            "User: Can you look up AI research papers?",
            "You: I can call the arxiv_query_agent to fetch the latest AI papers. Would you like me to do that now?",
            "",
            "Available A2A agents:",
        ]
        for name, config in self.settings.agents.items():
            description = config.description or f"Specialised agent '{name}'"
            lines.append(f"- {name}: {description}")
        return "\n".join(lines)


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
