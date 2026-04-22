"""Compatibility service for the OpenCode external session directory."""

from __future__ import annotations

from app.features.external_sessions.directory.adapters import (
    opencode_session_directory_adapter,
)
from app.features.external_sessions.directory.service import (
    ExternalSessionDirectoryService,
)

OPENCODE_PROVIDER = opencode_session_directory_adapter.provider_key


class OpencodeSessionDirectoryService(ExternalSessionDirectoryService):
    """OpenCode-specific compatibility wrapper for the generic directory service."""

    def __init__(self) -> None:
        super().__init__(adapter=opencode_session_directory_adapter)


opencode_session_directory_service = OpencodeSessionDirectoryService()
