"""A2A integration package for Compass."""

from app.integrations.a2a_client.service import get_a2a_service, shutdown_a2a_service

__all__ = ["get_a2a_service", "shutdown_a2a_service"]
