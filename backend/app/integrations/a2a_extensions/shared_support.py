from __future__ import annotations

import asyncio
from typing import Any, Dict, Mapping, Optional, cast

import httpx
from a2a.types import AgentCard

from app.core.config import settings
from app.core.http_client import get_global_http_client
from app.integrations.a2a_client import get_a2a_service
from app.integrations.a2a_client.errors import (
    A2AAgentUnavailableError,
    A2AClientResetRequiredError,
)
from app.integrations.a2a_error_contract import (
    coerce_jsonrpc_error_code,
    map_upstream_error_code,
    normalize_error_data_type,
)
from app.integrations.a2a_extensions.errors import A2AExtensionUpstreamError
from app.integrations.a2a_extensions.jsonrpc import JsonRpcClient, JsonRpcResponse
from app.integrations.a2a_extensions.metrics import a2a_extension_metrics
from app.integrations.a2a_extensions.types import (
    ResolvedExtension,
    ResolvedInterruptCallbackExtension,
    ResolvedProviderDiscoveryExtension,
)
from app.services.a2a_proxy_service import a2a_proxy_service
from app.services.a2a_runtime import A2ARuntime
from app.utils.outbound_url import (
    OutboundURLNotAllowedError,
    validate_outbound_http_url,
)


class A2AExtensionSupport:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._jsonrpc: Optional[JsonRpcClient] = None

    async def _get_http(self) -> httpx.AsyncClient:
        async with self._lock:
            http = get_global_http_client()
            if self._jsonrpc is None:
                self._jsonrpc = JsonRpcClient(http)
            return http

    async def shutdown(self) -> None:
        async with self._lock:
            self._jsonrpc = None

    async def fetch_card(self, runtime: A2ARuntime) -> AgentCard:
        self.ensure_outbound_allowed(runtime.resolved.url, purpose="Agent card URL")
        try:
            service = cast(Any, get_a2a_service())
            card = await service.gateway.fetch_agent_card_detail(
                resolved=runtime.resolved,
                raise_on_failure=True,
            )
        except (A2AAgentUnavailableError, A2AClientResetRequiredError) as exc:
            raise A2AExtensionUpstreamError(
                message=str(exc),
                error_code="agent_unavailable",
                upstream_error={"message": str(exc), "type": type(exc).__name__},
            ) from exc
        if card is None:
            raise A2AExtensionUpstreamError(
                message="Agent card unavailable",
                error_code="agent_unavailable",
                upstream_error={"message": "Agent card unavailable"},
            )
        return cast(AgentCard, card)

    def ensure_outbound_allowed(self, url: str, *, purpose: str) -> str:
        try:
            return validate_outbound_http_url(
                url,
                allowed_hosts=a2a_proxy_service.get_effective_allowed_hosts_sync(),
                purpose=purpose,
            )
        except OutboundURLNotAllowedError as exc:
            raise A2AExtensionUpstreamError(
                message=str(exc),
                error_code="outbound_not_allowed",
                upstream_error={"message": str(exc)},
            ) from exc

    async def _call_with_retry(
        self,
        *,
        url: str,
        method: str,
        params: Dict[str, Any],
        headers: Dict[str, str],
        timeout_seconds: float,
        max_attempts: int = 2,
        backoff_seconds: float = 0.2,
    ) -> JsonRpcResponse:
        assert self._jsonrpc is not None
        attempt = 0
        last_exc: Exception | None = None
        while attempt < max_attempts:
            attempt += 1
            try:
                return await self._jsonrpc.call(
                    url=url,
                    method=method,
                    params=params,
                    headers=headers,
                    timeout_seconds=timeout_seconds,
                )
            except httpx.TransportError as exc:
                last_exc = exc
                if attempt >= max_attempts:
                    raise
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                status_code = exc.response.status_code if exc.response else None
                if not status_code or status_code < 500 or attempt >= max_attempts:
                    raise
            if backoff_seconds > 0:
                await asyncio.sleep(backoff_seconds * (2 ** (attempt - 1)))
        assert last_exc is not None
        raise last_exc

    async def perform_jsonrpc_call(
        self,
        *,
        runtime: A2ARuntime,
        jsonrpc_url: str,
        method_name: str,
        params: Dict[str, Any],
    ) -> JsonRpcResponse:
        await self._get_http()
        try:
            return await self._call_with_retry(
                url=jsonrpc_url,
                method=method_name,
                params=params,
                headers=dict(runtime.resolved.headers),
                timeout_seconds=max(settings.a2a_default_timeout, 1.0),
            )
        except httpx.TransportError as exc:
            raise A2AExtensionUpstreamError(
                message=str(exc),
                error_code="upstream_unreachable",
                upstream_error={"message": str(exc), "type": type(exc).__name__},
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise A2AExtensionUpstreamError(
                message=str(exc),
                error_code="upstream_http_error",
                upstream_error={
                    "message": str(exc),
                    "status_code": (exc.response.status_code if exc.response else None),
                },
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise A2AExtensionUpstreamError(
                message=str(exc),
                error_code="upstream_error",
                upstream_error={"message": str(exc), "type": type(exc).__name__},
            ) from exc

    @staticmethod
    def coerce_jsonrpc_error_code(error: Dict[str, Any]) -> Optional[int]:
        return coerce_jsonrpc_error_code(error)

    @staticmethod
    def normalize_error_data_type(error: Dict[str, Any]) -> Optional[str]:
        return normalize_error_data_type(error)

    @staticmethod
    def map_upstream_error_code(
        *,
        error: Dict[str, Any],
        business_code_map: Mapping[int, str],
    ) -> str:
        return map_upstream_error_code(
            jsonrpc_code=error,
            data=error.get("data"),
            message=(
                str(error.get("message")).strip()
                if isinstance(error.get("message"), str)
                else None
            ),
            business_code_map=business_code_map,
            default_error_code="upstream_error",
        )

    @staticmethod
    def map_business_error_code(
        error: Dict[str, Any],
        ext: ResolvedExtension | ResolvedProviderDiscoveryExtension,
    ) -> str:
        return A2AExtensionSupport.map_upstream_error_code(
            error=error,
            business_code_map=ext.business_code_map,
        )

    @staticmethod
    def map_interrupt_business_error_code(
        error: Dict[str, Any],
        ext: ResolvedInterruptCallbackExtension,
    ) -> str:
        return A2AExtensionSupport.map_upstream_error_code(
            error=error,
            business_code_map=ext.business_code_map,
        )

    @staticmethod
    def normalize_extension_metadata(
        metadata: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if metadata is None:
            return None
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be an object")
        return dict(metadata)

    @staticmethod
    def record_extension_metric(
        metric_key: str, success: bool, error_code: Optional[str]
    ) -> None:
        a2a_extension_metrics.record_call(
            metric_key,
            success=success,
            error_code=error_code,
        )
