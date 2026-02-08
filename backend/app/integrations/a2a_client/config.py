"""Configuration helpers for Compass A2A integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

from pydantic import BaseModel, Field, ValidationError


class A2AAgentConfig(BaseModel):
    """Normalized configuration for an external A2A agent."""

    url: str
    name: str
    description: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    headers: Dict[str, str] = Field(default_factory=dict)

    @classmethod
    def from_mapping(cls, name: str, payload: Any) -> "A2AAgentConfig":
        """Normalize arbitrary payloads into an ``A2AAgentConfig`` instance."""

        if isinstance(payload, str):
            value = payload.strip()
            if not value:
                raise ValidationError.from_exception_data(
                    "A2AAgentConfig",
                    [
                        {
                            "loc": ("url",),
                            "msg": "URL must be a non-empty string",
                            "type": "value_error",
                        }
                    ],
                )
            return cls(url=value, name=name)

        if isinstance(payload, Mapping):
            data = {
                "url": payload.get("url", "").strip(),
                "name": payload.get("name", name),
            }
            if not data["url"]:
                raise ValidationError.from_exception_data(
                    "A2AAgentConfig",
                    [
                        {
                            "loc": ("url",),
                            "msg": "Agent configuration requires non-empty 'url'",
                            "type": "value_error",
                        }
                    ],
                )
            if "description" in payload:
                data["description"] = payload.get("description")
            if "metadata" in payload and isinstance(payload["metadata"], Mapping):
                data["metadata"] = dict(payload["metadata"])
            if "headers" in payload and isinstance(payload["headers"], Mapping):
                data["headers"] = {
                    str(k): str(v) for k, v in payload["headers"].items()
                }
            return cls(**data)

        raise ValidationError.from_exception_data(
            "A2AAgentConfig",
            [
                {
                    "loc": ("url",),
                    "msg": "Unsupported agent configuration type",
                    "type": "type_error",
                }
            ],
        )


@dataclass(frozen=True)
class A2ASettings:
    """Runtime settings for the A2A integration layer."""

    enabled: bool
    default_timeout: float
    max_connections: int
    use_client_preference: bool
    agents: Dict[str, A2AAgentConfig]
    card_fetch_timeout: float = 5.0
    invoke_watchdog_interval: float = 5.0
    client_idle_timeout: float = 600.0

    @property
    def has_agents(self) -> bool:
        return bool(self.agents)


def load_settings(raw_settings) -> A2ASettings:
    """Load ``A2ASettings`` from the global ``app.core.config.settings`` object."""

    agents: Dict[str, A2AAgentConfig] = {}
    raw_agents = getattr(raw_settings, "a2a_agents", {}) or {}
    for name, payload in raw_agents.items():
        agents[name] = A2AAgentConfig.from_mapping(name, payload)

    return A2ASettings(
        enabled=getattr(raw_settings, "a2a_enabled", False),
        default_timeout=float(getattr(raw_settings, "a2a_default_timeout", 30.0)),
        max_connections=int(getattr(raw_settings, "a2a_max_connections", 20)),
        use_client_preference=bool(
            getattr(raw_settings, "a2a_use_client_preference", False)
        ),
        card_fetch_timeout=float(getattr(raw_settings, "a2a_card_fetch_timeout", 5.0)),
        invoke_watchdog_interval=float(
            getattr(raw_settings, "a2a_invoke_watchdog_interval", 5.0)
        ),
        client_idle_timeout=float(
            getattr(raw_settings, "a2a_client_idle_timeout", 600.0)
        ),
        agents=agents,
    )
