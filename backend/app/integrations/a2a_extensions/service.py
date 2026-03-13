"""Service facade for A2A Agent Card extensions."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from app.core.logging import get_logger
from app.integrations.a2a_extensions.errors import A2AExtensionUpstreamError
from app.integrations.a2a_extensions.interrupt_extension_service import (
    InterruptExtensionService,
)
from app.integrations.a2a_extensions.opencode_discovery_service import (
    OpencodeDiscoveryService,
)
from app.integrations.a2a_extensions.service_common import ExtensionCallResult
from app.integrations.a2a_extensions.session_extension_service import (
    SessionExtensionService,
)
from app.integrations.a2a_extensions.shared_support import A2AExtensionSupport
from app.integrations.a2a_extensions.types import (
    ResolvedExtension,
    ResolvedInterruptCallbackExtension,
    ResolvedProviderDiscoveryExtension,
    ResultEnvelopeMapping,
)
from app.services.a2a_runtime import A2ARuntime

logger = get_logger(__name__)


class A2AExtensionsService:
    def __init__(self) -> None:
        self._support = A2AExtensionSupport()
        self._session_extensions = SessionExtensionService(self._support)
        self._interrupt_extensions = InterruptExtensionService(self._support)
        self._opencode_discovery = OpencodeDiscoveryService(self._support)

    async def shutdown(self) -> None:
        await self._support.shutdown()

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
        return A2AExtensionSupport.map_business_error_code(error, ext)

    @staticmethod
    def _map_interrupt_business_error_code(
        error: Dict[str, Any],
        ext: ResolvedInterruptCallbackExtension,
    ) -> str:
        return A2AExtensionSupport.map_interrupt_business_error_code(error, ext)

    @staticmethod
    def _coerce_jsonrpc_error_code(error: Dict[str, Any]) -> Optional[int]:
        return A2AExtensionSupport.coerce_jsonrpc_error_code(error)

    @staticmethod
    def _normalize_error_data_type(error: Dict[str, Any]) -> Optional[str]:
        return A2AExtensionSupport.normalize_error_data_type(error)

    @staticmethod
    def _map_upstream_error_code(
        *,
        error: Dict[str, Any],
        business_code_map: Mapping[int, str],
    ) -> str:
        return A2AExtensionSupport.map_upstream_error_code(
            error=error,
            business_code_map=business_code_map,
        )

    @staticmethod
    def _normalize_extension_metadata(
        metadata: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        return A2AExtensionSupport.normalize_extension_metadata(metadata)

    @staticmethod
    def _record_extension_metric(
        metric_key: str, success: bool, error_code: Optional[str]
    ) -> None:
        A2AExtensionSupport.record_extension_metric(metric_key, success, error_code)

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
