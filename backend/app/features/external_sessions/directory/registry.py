"""Provider registry for external session directory aggregation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.features.external_sessions.directory.adapters import (
    ExternalSessionDirectoryAdapter,
    opencode_session_directory_adapter,
)
from app.features.external_sessions.directory.service import (
    ExternalSessionDirectoryService,
)


@dataclass(frozen=True)
class ExternalSessionDirectoryProvider:
    provider_key: str
    service: ExternalSessionDirectoryService


class ExternalSessionDirectoryRegistry:
    def __init__(self, providers: Iterable[ExternalSessionDirectoryProvider]) -> None:
        self._providers = {
            provider.provider_key.strip().lower(): provider for provider in providers
        }

    def get_service(self, provider: str) -> ExternalSessionDirectoryService | None:
        registered = self._providers.get(provider.strip().lower())
        if registered is None:
            return None
        return registered.service

    def provider_keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))


def create_external_session_directory_provider(
    adapter: ExternalSessionDirectoryAdapter,
) -> ExternalSessionDirectoryProvider:
    return ExternalSessionDirectoryProvider(
        provider_key=adapter.provider_key,
        service=ExternalSessionDirectoryService(adapter=adapter),
    )


external_session_directory_registry = ExternalSessionDirectoryRegistry(
    providers=[
        create_external_session_directory_provider(opencode_session_directory_adapter),
    ]
)


def get_external_session_directory_registry() -> ExternalSessionDirectoryRegistry:
    return external_session_directory_registry
