"""Configuration helpers for a2a-client-hub A2A client integration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class A2ASettings:
    """Runtime settings for the A2A integration layer."""

    default_timeout: float
    use_client_preference: bool
    card_fetch_timeout: float = 5.0
    invoke_watchdog_interval: float = 5.0
    client_idle_timeout: float = 600.0


def load_settings(raw_settings) -> A2ASettings:
    """Load ``A2ASettings`` from the global ``app.core.config.settings`` object."""

    return A2ASettings(
        default_timeout=float(getattr(raw_settings, "a2a_default_timeout", 30.0)),
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
    )
