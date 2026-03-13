"""Service facade for A2A Agent Card extensions."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Mapping, Optional

import httpx
from a2a.types import AgentCard

from app.core.config import settings
from app.core.http_client import get_global_http_client
from app.core.logging import get_logger
from app.integrations.a2a_client import get_a2a_service
from app.integrations.a2a_client.errors import (
    A2AAgentUnavailableError,
    A2AClientResetRequiredError,
)
from app.integrations.a2a_extensions.errors import A2AExtensionUpstreamError
from app.integrations.a2a_extensions.interrupt_extension_service import (
    InterruptExtensionService,
)
from app.integrations.a2a_extensions.jsonrpc import JsonRpcClient, JsonRpcResponse
from app.integrations.a2a_extensions.metrics import a2a_extension_metrics
from app.integrations.a2a_extensions.opencode_discovery_service import (
    OpencodeDiscoveryService,
)
from app.integrations.a2a_extensions.service_common import ExtensionCallResult
from app.integrations.a2a_extensions.session_extension_service import (
    SessionExtensionService,
)
from app.integrations.a2a_extensions.types import (
    ResolvedExtension,
    ResolvedInterruptCallbackExtension,
    ResolvedProviderDiscoveryExtension,
    ResultEnvelopeMapping,
)
from app.services.a2a_proxy_service import a2a_proxy_service
from app.services.a2a_runtime import A2ARuntime
from app.utils.outbound_url import (
    OutboundURLNotAllowedError,
    validate_outbound_http_url,
)

logger = get_logger(__name__)

_JSONRPC_STANDARD_ERROR_CODE_MAP: dict[int, str] = {
    -32600: "invalid_request",
    -32601: "method_not_supported",
    -32602: "invalid_params",
}

_ERROR_DATA_TYPE_TO_ERROR_CODE: dict[str, str] = {
    "session_not_found": "session_not_found",
    "session_forbidden": "session_forbidden",
    "method_disabled": "method_disabled",
    "upstream_unreachable": "upstream_unreachable",
    "upstream_http_error": "upstream_http_error",
    "upstream_payload_error": "upstream_payload_error",
    "interrupt_request_not_found": "interrupt_request_not_found",
    "interrupt_request_expired": "interrupt_request_expired",
    "interrupt_type_mismatch": "interrupt_type_mismatch",
    "invalid_field": "invalid_params",
    "missing_field": "invalid_params",
    "invalid_pagination_mode": "invalid_params",
}


class A2AExtensionsService:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._jsonrpc: Optional[JsonRpcClient] = None
        self._session_extensions = SessionExtensionService(self)
        self._interrupt_extensions = InterruptExtensionService(self)
        self._opencode_discovery = OpencodeDiscoveryService(self)

    async def _get_http(self) -> httpx.AsyncClient:
        async with self._lock:
            http = get_global_http_client()
            if self._jsonrpc is None:
                self._jsonrpc = JsonRpcClient(http)
            return http

    async def shutdown(self) -> None:
        async with self._lock:
            self._jsonrpc = None

    async def _fetch_card(self, runtime: A2ARuntime) -> AgentCard:
        # Validate the agent card URL before any outbound request.
        self._ensure_outbound_allowed(runtime.resolved.url, purpose="Agent card URL")
        try:
            card = await get_a2a_service().gateway.fetch_agent_card_detail(
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
        return card

    def _ensure_outbound_allowed(self, url: str, *, purpose: str) -> str:
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

    @staticmethod
    def _normalize_envelope(
        result: Any,
        *,
        page: int,
        size: int,
        result_envelope: ResultEnvelopeMapping | None = None,
        include_raw: bool = False,
    ) -> Optional[Dict[str, Any]]:
        return SessionExtensionService._normalize_envelope(
            result,
            page=page,
            size=size,
            result_envelope=result_envelope,
            include_raw=include_raw,
        )

    @staticmethod
    def _resolve_result_field(
        result: Mapping[str, Any],
        *,
        path: str,
        fallback_path: str | None = None,
    ) -> tuple[Any, bool]:
        return SessionExtensionService._resolve_result_field(
            result,
            path=path,
            fallback_path=fallback_path,
        )

    @staticmethod
    def _validate_query_result(envelope: Dict[str, Any]) -> Dict[str, Any]:
        return SessionExtensionService._validate_query_result(envelope)

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
    ):
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
                # Retry only on server-side errors.
                status_code = exc.response.status_code if exc.response else None
                if not status_code or status_code < 500 or attempt >= max_attempts:
                    raise
            if backoff_seconds > 0:
                await asyncio.sleep(backoff_seconds * (2 ** (attempt - 1)))
        assert last_exc is not None
        raise last_exc

    @staticmethod
    def _coerce_page_size(
        *,
        default_size: int,
        max_size: int,
        page: int,
        size: Optional[int],
    ) -> tuple[int, int]:
        return SessionExtensionService._coerce_page_size(
            default_size=default_size,
            max_size=max_size,
            page=page,
            size=size,
        )

    @staticmethod
    def _build_pagination_params(
        *,
        mode: str,
        page: int,
        size: int,
        supports_offset: bool,
    ) -> Dict[str, int]:
        return SessionExtensionService._build_pagination_params(
            mode=mode,
            page=page,
            size=size,
            supports_offset=supports_offset,
        )

    @staticmethod
    def _build_call_meta(
        *,
        ext: ResolvedExtension,
        page: int,
        size: int,
        meta_extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return SessionExtensionService._build_call_meta(
            ext=ext,
            page=page,
            size=size,
            meta_extra=meta_extra,
        )

    @staticmethod
    def _map_business_error_code(
        error: Dict[str, Any],
        ext: ResolvedExtension | ResolvedProviderDiscoveryExtension,
    ) -> str:
        return A2AExtensionsService._map_upstream_error_code(  # noqa: SLF001
            error=error,
            business_code_map=ext.business_code_map,
        )

    @staticmethod
    def _map_interrupt_business_error_code(
        error: Dict[str, Any],
        ext: ResolvedInterruptCallbackExtension,
    ) -> str:
        return A2AExtensionsService._map_upstream_error_code(  # noqa: SLF001
            error=error,
            business_code_map=ext.business_code_map,
        )

    @staticmethod
    def _coerce_jsonrpc_error_code(error: Dict[str, Any]) -> Optional[int]:
        code = error.get("code")
        if isinstance(code, bool):
            return None
        if isinstance(code, int):
            return code
        if isinstance(code, str):
            normalized = code.strip()
            if normalized.lstrip("-").isdigit():
                return int(normalized)
        return None

    @staticmethod
    def _normalize_error_data_type(error: Dict[str, Any]) -> Optional[str]:
        data = error.get("data")
        if not isinstance(data, dict):
            return None
        raw_type = data.get("type")
        if not isinstance(raw_type, str):
            return None
        normalized = []
        pending_sep = False
        for ch in raw_type.strip().lower():
            if ch.isalnum():
                if pending_sep and normalized:
                    normalized.append("_")
                normalized.append(ch)
                pending_sep = False
                continue
            pending_sep = True
        token = "".join(normalized).strip("_")
        return token or None

    @staticmethod
    def _map_upstream_error_code(
        *,
        error: Dict[str, Any],
        business_code_map: Mapping[int, str],
    ) -> str:
        normalized_data_type = A2AExtensionsService._normalize_error_data_type(error)
        if normalized_data_type:
            mapped_by_type = _ERROR_DATA_TYPE_TO_ERROR_CODE.get(normalized_data_type)
            if mapped_by_type:
                return mapped_by_type
            if normalized_data_type.startswith("invalid_"):
                return "invalid_params"

        numeric_code = A2AExtensionsService._coerce_jsonrpc_error_code(error)
        if numeric_code is not None:
            mapped = business_code_map.get(numeric_code)
            if mapped:
                return mapped
            mapped_standard = _JSONRPC_STANDARD_ERROR_CODE_MAP.get(numeric_code)
            if mapped_standard:
                return mapped_standard

        return "upstream_error"

    @staticmethod
    def _normalize_extension_metadata(
        metadata: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if metadata is None:
            return None
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be an object")
        return dict(metadata)

    @staticmethod
    def _record_extension_metric(
        metric_key: str, success: bool, error_code: Optional[str]
    ) -> None:
        a2a_extension_metrics.record_call(
            metric_key,
            success=success,
            error_code=error_code,
        )

    async def _perform_jsonrpc_call(
        self,
        *,
        runtime: A2ARuntime,
        jsonrpc_url: str,
        method_name: str,
        params: Dict[str, Any],
    ) -> JsonRpcResponse:
        await self._get_http()
        assert self._jsonrpc is not None  # constructed alongside _http
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

    async def list_sessions(
        self,
        *,
        runtime: A2ARuntime,
        page: int,
        size: Optional[int],
        query: Optional[Dict[str, Any]],
        include_raw: bool = False,
    ) -> ExtensionCallResult:
        return await self._session_extensions.list_sessions(
            runtime=runtime,
            page=page,
            size=size,
            query=query,
            include_raw=include_raw,
        )

    async def get_session_messages(
        self,
        *,
        runtime: A2ARuntime,
        session_id: str,
        page: int,
        size: Optional[int],
        query: Optional[Dict[str, Any]],
        include_raw: bool = False,
    ) -> ExtensionCallResult:
        return await self._session_extensions.get_session_messages(
            runtime=runtime,
            session_id=session_id,
            page=page,
            size=size,
            query=query,
            include_raw=include_raw,
        )

    async def continue_session(
        self,
        *,
        runtime: A2ARuntime,
        session_id: str,
    ) -> ExtensionCallResult:
        return await self._session_extensions.continue_session(
            runtime=runtime,
            session_id=session_id,
        )

    async def prompt_session_async(
        self,
        *,
        runtime: A2ARuntime,
        session_id: str,
        request_payload: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        return await self._session_extensions.prompt_session_async(
            runtime=runtime,
            session_id=session_id,
            request_payload=request_payload,
            metadata=metadata,
        )

    async def list_opencode_providers(
        self,
        *,
        runtime: A2ARuntime,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        return await self._opencode_discovery.list_opencode_providers(
            runtime=runtime,
            metadata=metadata,
        )

    async def list_opencode_models(
        self,
        *,
        runtime: A2ARuntime,
        provider_id: str | None = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        return await self._opencode_discovery.list_opencode_models(
            runtime=runtime,
            provider_id=provider_id,
            metadata=metadata,
        )

    async def reply_permission_interrupt(
        self,
        *,
        runtime: A2ARuntime,
        request_id: str,
        reply: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        return await self._interrupt_extensions.reply_permission_interrupt(
            runtime=runtime,
            request_id=request_id,
            reply=reply,
            metadata=metadata,
        )

    async def reply_question_interrupt(
        self,
        *,
        runtime: A2ARuntime,
        request_id: str,
        answers: list[list[str]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        return await self._interrupt_extensions.reply_question_interrupt(
            runtime=runtime,
            request_id=request_id,
            answers=answers,
            metadata=metadata,
        )

    async def reject_question_interrupt(
        self,
        *,
        runtime: A2ARuntime,
        request_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        return await self._interrupt_extensions.reject_question_interrupt(
            runtime=runtime,
            request_id=request_id,
            metadata=metadata,
        )


_service_instance: Optional[A2AExtensionsService] = None


def get_a2a_extensions_service() -> A2AExtensionsService:
    global _service_instance
    if _service_instance is None:
        _service_instance = A2AExtensionsService()
        logger.info("A2A extensions service initialised")
    return _service_instance


async def shutdown_a2a_extensions_service() -> None:
    global _service_instance
    if _service_instance is None:
        return
    await _service_instance.shutdown()
    _service_instance = None


__all__ = [
    "A2AExtensionsService",
    "ExtensionCallResult",
    "get_a2a_extensions_service",
    "shutdown_a2a_extensions_service",
    "A2AExtensionUpstreamError",
]
