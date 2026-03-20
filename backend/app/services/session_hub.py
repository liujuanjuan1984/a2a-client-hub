"""Compatibility re-export for the legacy session hub service path."""

from app.features.sessions.service import SessionHubService, session_hub_service

__all__ = ["SessionHubService", "session_hub_service"]
