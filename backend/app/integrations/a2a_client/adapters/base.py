"""Abstract adapter interface for peer-specific A2A transport behavior."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from app.integrations.a2a_client.lifecycle import AdapterLifecycleSnapshot
from app.integrations.a2a_client.models import A2AMessageRequest, A2APeerDescriptor


class A2AAdapter(ABC):
    """Stable protocol boundary consumed by the gateway/client facade."""

    def __init__(self, descriptor: A2APeerDescriptor) -> None:
        self._descriptor = descriptor

    @property
    def descriptor(self) -> A2APeerDescriptor:
        return self._descriptor

    @property
    @abstractmethod
    def dialect(self) -> str:
        """Stable adapter/dialect label for caching and selection."""

    @abstractmethod
    async def send_message(self, request: A2AMessageRequest) -> Any:
        """Execute a blocking invoke against the peer."""

    @abstractmethod
    def stream_message(self, request: A2AMessageRequest) -> AsyncIterator[Any]:
        """Produce normalized or raw streaming payloads."""

    @abstractmethod
    async def get_task(
        self,
        task_id: str,
        *,
        history_length: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        """Fetch a downstream task snapshot."""

    @abstractmethod
    async def cancel_task(
        self,
        task_id: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        """Cancel a downstream task."""

    @abstractmethod
    async def close(self) -> None:
        """Release any owned transport resources."""

    async def retire(self) -> None:
        """Remove the adapter from future routing while draining in-flight work."""

        await self.close()

    def get_lifecycle_snapshot(self) -> AdapterLifecycleSnapshot:
        """Return a lightweight lifecycle snapshot for diagnostics."""

        return AdapterLifecycleSnapshot(
            dialect=self.dialect,
            active_operations=0,
            retired=False,
            closed=False,
        )
