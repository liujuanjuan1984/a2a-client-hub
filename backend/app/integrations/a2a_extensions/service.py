"""Service facade for A2A Agent Card extensions."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

import httpx
from a2a.types import AgentCard

from app.core.config import settings
from app.services.a2a_proxy_service import a2a_proxy_service
from app.core.http_client import get_global_http_client
from app.core.logging import get_logger
from app.integrations.a2a_client import get_a2a_service
from app.integrations.a2a_client.errors import (
    A2AAgentUnavailableError,
    A2AClientResetRequiredError,
)
from app.integrations.a2a_extensions.errors import (
    A2AExtensionContractError,
    A2AExtensionUpstreamError,
)
from app.integrations.a2a_extensions.jsonrpc import JsonRpcClient, JsonRpcResponse
from app.integrations.a2a_extensions.metrics import a2a_extension_metrics
from app.integrations.a2a_extensions.opencode_interrupt_callback import (
    resolve_opencode_interrupt_callback,
)
from app.integrations.a2a_extensions.opencode_session_query import (
    resolve_opencode_session_query,
)
from app.integrations.a2a_extensions.types import (
    ResolvedExtension,
    ResolvedInterruptCallbackExtension,
)
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


@dataclass(frozen=True, slots=True)
class ExtensionCallResult:
    success: bool
    result: Optional[Dict[str, Any]] = None
    error_code: Optional[str] = None
    upstream_error: Optional[Dict[str, Any]] = None
    meta: Optional[Dict[str, Any]] = None


class A2AExtensionsService:
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
    ) -> Optional[Dict[str, Any]]:
        if result is None:
            return None
        # Upstream extensions may return either:
        # - a pre-wrapped envelope (dict), or
        # - a plain list of items.
        if isinstance(result, list):
            return {
                "raw": result,
                "items": result,
                "pagination": {"page": page, "size": size},
            }

        if not isinstance(result, dict):
            return {
                "raw": result,
                "items": [],
                "pagination": {"page": page, "size": size},
            }

        envelope: Dict[str, Any] = dict(result)
        envelope.setdefault("raw", result)

        items = envelope.get("items")
        if not isinstance(items, list):
            raw = envelope.get("raw")
            if items is None and isinstance(raw, list):
                envelope["items"] = raw
            else:
                envelope["items"] = []

        pagination = envelope.get("pagination")
        if not isinstance(pagination, dict):
            envelope["pagination"] = {"page": page, "size": size}

        return envelope

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
        resolved_page = int(page)
        if resolved_page < 1:
            raise ValueError("page must be >= 1")
        resolved_size = default_size if size is None else int(size)
        if resolved_size < 1:
            raise ValueError("size must be >= 1")
        if resolved_size > max_size:
            raise ValueError(f"size must be <= {max_size}")
        return resolved_page, resolved_size

    @staticmethod
    def _build_pagination_params(
        *,
        mode: str,
        page: int,
        size: int,
        supports_offset: bool,
    ) -> Dict[str, int]:
        if mode == "page_size":
            return {"page": page, "size": size}
        if mode == "limit":
            if supports_offset:
                return {"offset": (page - 1) * size, "limit": size}
            if page > 1:
                raise ValueError(
                    "limit pagination without offset does not support page > 1"
                )
            return {"limit": size}
        raise ValueError(f"unsupported pagination mode: {mode}")

    @staticmethod
    def _build_call_meta(
        *,
        ext: ResolvedExtension,
        page: int,
        size: int,
        meta_extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        meta = {
            "extension_uri": ext.uri,
            "jsonrpc_fallback_used": ext.jsonrpc.fallback_used,
            "pagination_mode": ext.pagination.mode,
            "pagination_params": list(ext.pagination.params),
            "pagination_supports_offset": ext.pagination.supports_offset,
            "page": page,
            "size": size,
            "max_size": ext.pagination.max_size,
            "default_size": ext.pagination.default_size,
        }
        if meta_extra:
            meta.update(meta_extra)
        return meta

    async def _resolve_opencode_extension(
        self, runtime: A2ARuntime
    ) -> tuple[ResolvedExtension, str]:
        card = await self._fetch_card(runtime)
        ext = resolve_opencode_session_query(card)
        jsonrpc_url = self._ensure_outbound_allowed(
            ext.jsonrpc.url, purpose="JSON-RPC interface URL"
        )
        return ext, jsonrpc_url

    @staticmethod
    def _map_business_error_code(error: Dict[str, Any], ext: ResolvedExtension) -> str:
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

        normalized = dict(metadata)
        opencode_raw = normalized.get("opencode")
        if opencode_raw is None:
            return normalized
        if not isinstance(opencode_raw, dict):
            raise ValueError("metadata.opencode must be an object")

        opencode = dict(opencode_raw)
        if "directory" in opencode:
            raw_directory = opencode.get("directory")
            if not isinstance(raw_directory, str) or not raw_directory.strip():
                raise ValueError(
                    "metadata.opencode.directory must be a non-empty string"
                )
            opencode["directory"] = raw_directory.strip()

        normalized["opencode"] = opencode
        return normalized

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

    async def _invoke_opencode_method(
        self,
        *,
        runtime: A2ARuntime,
        ext: ResolvedExtension,
        jsonrpc_url: str,
        method_key: str,
        params: Dict[str, Any],
        page: int,
        size: int,
        normalize_envelope: bool = True,
        meta_extra: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        method_name = ext.methods.get(method_key)
        if not method_name:
            return ExtensionCallResult(
                success=False,
                error_code="method_not_supported",
                upstream_error={
                    "message": f"Method {method_key} is not supported by upstream"
                },
                meta={"extension_uri": ext.uri},
            )

        resp = await self._perform_jsonrpc_call(
            runtime=runtime,
            jsonrpc_url=jsonrpc_url,
            method_name=method_name,
            params=params,
        )

        meta = self._build_call_meta(
            ext=ext,
            page=page,
            size=size,
            meta_extra=meta_extra,
        )

        metric_key = f"{ext.uri}:{method_name}"
        if resp.ok:
            resolved_result: Optional[Dict[str, Any]]
            if normalize_envelope:
                resolved_result = self._normalize_envelope(
                    resp.result,
                    page=page,
                    size=size,
                )
            elif isinstance(resp.result, dict):
                resolved_result = dict(resp.result)
            else:
                resolved_result = {"raw": resp.result}

            self._record_extension_metric(metric_key, success=True, error_code=None)
            return ExtensionCallResult(success=True, result=resolved_result, meta=meta)

        error = resp.error or {}
        error_code = self._map_business_error_code(error, ext)
        self._record_extension_metric(metric_key, success=False, error_code=error_code)
        return ExtensionCallResult(
            success=False,
            error_code=error_code,
            upstream_error=error,
            meta=meta,
        )

    async def opencode_list_sessions(
        self,
        *,
        runtime: A2ARuntime,
        page: int,
        size: Optional[int],
        query: Optional[Dict[str, Any]],
    ) -> ExtensionCallResult:
        ext, jsonrpc_url = await self._resolve_opencode_extension(runtime)

        resolved_page, resolved_size = self._coerce_page_size(
            default_size=ext.pagination.default_size,
            max_size=ext.pagination.max_size,
            page=page,
            size=size,
        )
        if (
            ext.pagination.mode == "limit"
            and resolved_page > 1
            and not ext.pagination.supports_offset
        ):
            return ExtensionCallResult(
                success=True,
                result={
                    "raw": [],
                    "items": [],
                    "pagination": {"page": resolved_page, "size": resolved_size},
                },
                meta=self._build_call_meta(
                    ext=ext,
                    page=resolved_page,
                    size=resolved_size,
                    meta_extra={"short_circuit_reason": "limit_without_offset"},
                ),
            )

        params: Dict[str, Any] = self._build_pagination_params(
            mode=ext.pagination.mode,
            page=resolved_page,
            size=resolved_size,
            supports_offset=ext.pagination.supports_offset,
        )
        if query is not None:
            params["query"] = query

        return await self._invoke_opencode_method(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            method_key="list_sessions",
            params=params,
            page=resolved_page,
            size=resolved_size,
        )

    async def opencode_get_session_messages(
        self,
        *,
        runtime: A2ARuntime,
        session_id: str,
        page: int,
        size: Optional[int],
        query: Optional[Dict[str, Any]],
    ) -> ExtensionCallResult:
        resolved_session_id = (session_id or "").strip()
        if not resolved_session_id:
            raise ValueError("session_id is required")

        ext, jsonrpc_url = await self._resolve_opencode_extension(runtime)

        resolved_page, resolved_size = self._coerce_page_size(
            default_size=ext.pagination.default_size,
            max_size=ext.pagination.max_size,
            page=page,
            size=size,
        )
        if (
            ext.pagination.mode == "limit"
            and resolved_page > 1
            and not ext.pagination.supports_offset
        ):
            return ExtensionCallResult(
                success=True,
                result={
                    "raw": [],
                    "items": [],
                    "pagination": {"page": resolved_page, "size": resolved_size},
                },
                meta=self._build_call_meta(
                    ext=ext,
                    page=resolved_page,
                    size=resolved_size,
                    meta_extra={
                        "session_id": resolved_session_id,
                        "short_circuit_reason": "limit_without_offset",
                    },
                ),
            )

        params: Dict[str, Any] = {
            "session_id": resolved_session_id,
            **self._build_pagination_params(
                mode=ext.pagination.mode,
                page=resolved_page,
                size=resolved_size,
                supports_offset=ext.pagination.supports_offset,
            ),
        }
        if query is not None:
            params["query"] = query

        return await self._invoke_opencode_method(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            method_key="get_session_messages",
            params=params,
            page=resolved_page,
            size=resolved_size,
            meta_extra={"session_id": resolved_session_id},
        )

    async def opencode_continue_session(
        self,
        *,
        runtime: A2ARuntime,
        session_id: str,
    ) -> ExtensionCallResult:
        """Return a stable "continue" binding for an OpenCode session.

        This endpoint is intentionally conservative:
        - It validates the upstream session exists (best-effort) via the session
          query contract, returning stable error_code values on failure.
        - It returns `metadata.<metadata_key>` where `metadata_key` is discovered
          from `urn:opencode-a2a:opencode-session-binding/v1`.
        """

        resolved_session_id = (session_id or "").strip()
        if not resolved_session_id:
            raise ValueError("session_id is required")

        ext, jsonrpc_url = await self._resolve_opencode_extension(runtime)
        metadata_key = (ext.session_binding_metadata_key or "").strip()
        if not metadata_key:
            raise A2AExtensionContractError(
                "Extension contract missing/invalid session binding metadata_key"
            )

        validation = await self._invoke_opencode_method(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            method_key="get_session_messages",
            params={
                "session_id": resolved_session_id,
                **self._build_pagination_params(
                    mode=ext.pagination.mode,
                    page=1,
                    size=1,
                    supports_offset=ext.pagination.supports_offset,
                ),
            },
            page=1,
            size=1,
            meta_extra={"session_id": resolved_session_id},
        )
        if not validation.success:
            return validation

        meta = dict(validation.meta or {})
        meta.update(
            {
                "binding_mode": "contextId+metadata",
                "validated": True,
                "session_binding_metadata_key": metadata_key,
            }
        )
        return ExtensionCallResult(
            success=True,
            result={
                "contextId": resolved_session_id,
                "provider": "opencode",
                "metadata": {
                    metadata_key: resolved_session_id,
                },
            },
            meta=meta,
        )

    async def opencode_prompt_async(
        self,
        *,
        runtime: A2ARuntime,
        session_id: str,
        request_payload: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        resolved_session_id = (session_id or "").strip()
        if not resolved_session_id:
            raise ValueError("session_id is required")

        if not isinstance(request_payload, dict):
            raise ValueError("request must be an object")

        parts = request_payload.get("parts")
        if not isinstance(parts, list) or len(parts) == 0:
            raise ValueError("request.parts must be a non-empty array")

        params: Dict[str, Any] = {
            "session_id": resolved_session_id,
            "request": dict(request_payload),
        }
        normalized_metadata = self._normalize_extension_metadata(metadata)
        if normalized_metadata is not None:
            params["metadata"] = normalized_metadata

        ext, jsonrpc_url = await self._resolve_opencode_extension(runtime)
        return await self._invoke_opencode_method(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            method_key="prompt_async",
            params=params,
            page=1,
            size=1,
            normalize_envelope=False,
            meta_extra={
                "session_id": resolved_session_id,
                "control_method": "prompt_async",
            },
        )

    async def _resolve_opencode_interrupt_extension(
        self, runtime: A2ARuntime
    ) -> tuple[ResolvedInterruptCallbackExtension, str]:
        card = await self._fetch_card(runtime)
        ext = resolve_opencode_interrupt_callback(card)
        jsonrpc_url = self._ensure_outbound_allowed(
            ext.jsonrpc.url, purpose="JSON-RPC interface URL"
        )
        return ext, jsonrpc_url

    async def _invoke_opencode_interrupt_method(
        self,
        *,
        runtime: A2ARuntime,
        ext: ResolvedInterruptCallbackExtension,
        jsonrpc_url: str,
        method_key: str,
        params: Dict[str, Any],
        meta_extra: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        method_name = ext.methods.get(method_key)
        if not method_name:
            return ExtensionCallResult(
                success=False,
                error_code="method_not_supported",
                upstream_error={
                    "message": f"Method {method_key} is not supported by upstream"
                },
                meta={"extension_uri": ext.uri},
            )

        resp = await self._perform_jsonrpc_call(
            runtime=runtime,
            jsonrpc_url=jsonrpc_url,
            method_name=method_name,
            params=params,
        )

        meta: Dict[str, Any] = {
            "extension_uri": ext.uri,
            "jsonrpc_fallback_used": ext.jsonrpc.fallback_used,
        }
        if meta_extra:
            meta.update(meta_extra)

        metric_key = f"{ext.uri}:{method_name}"
        if resp.ok:
            self._record_extension_metric(metric_key, success=True, error_code=None)
            return ExtensionCallResult(success=True, result=resp.result, meta=meta)

        error = resp.error or {}
        error_code = self._map_interrupt_business_error_code(error, ext)
        self._record_extension_metric(metric_key, success=False, error_code=error_code)
        return ExtensionCallResult(
            success=False,
            error_code=error_code,
            upstream_error=error,
            meta=meta,
        )

    async def opencode_reply_permission(
        self,
        *,
        runtime: A2ARuntime,
        request_id: str,
        reply: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        resolved_request_id = (request_id or "").strip()
        if not resolved_request_id:
            raise ValueError("request_id is required")
        resolved_reply = (reply or "").strip().lower()
        if resolved_reply not in {"once", "always", "reject"}:
            raise ValueError("reply must be one of: once, always, reject")
        normalized_metadata = self._normalize_extension_metadata(metadata)

        ext, jsonrpc_url = await self._resolve_opencode_interrupt_extension(runtime)
        params: Dict[str, Any] = {
            "request_id": resolved_request_id,
            "reply": resolved_reply,
        }
        if normalized_metadata is not None:
            params["metadata"] = normalized_metadata
        return await self._invoke_opencode_interrupt_method(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            method_key="reply_permission",
            params=params,
            meta_extra={"request_id": resolved_request_id},
        )

    async def opencode_reply_question(
        self,
        *,
        runtime: A2ARuntime,
        request_id: str,
        answers: list[list[str]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        resolved_request_id = (request_id or "").strip()
        if not resolved_request_id:
            raise ValueError("request_id is required")
        normalized_metadata = self._normalize_extension_metadata(metadata)

        ext, jsonrpc_url = await self._resolve_opencode_interrupt_extension(runtime)
        params: Dict[str, Any] = {
            "request_id": resolved_request_id,
            "answers": answers,
        }
        if normalized_metadata is not None:
            params["metadata"] = normalized_metadata
        return await self._invoke_opencode_interrupt_method(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            method_key="reply_question",
            params=params,
            meta_extra={"request_id": resolved_request_id},
        )

    async def opencode_reject_question(
        self,
        *,
        runtime: A2ARuntime,
        request_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        resolved_request_id = (request_id or "").strip()
        if not resolved_request_id:
            raise ValueError("request_id is required")
        normalized_metadata = self._normalize_extension_metadata(metadata)

        ext, jsonrpc_url = await self._resolve_opencode_interrupt_extension(runtime)
        params: Dict[str, Any] = {"request_id": resolved_request_id}
        if normalized_metadata is not None:
            params["metadata"] = normalized_metadata
        return await self._invoke_opencode_interrupt_method(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            method_key="reject_question",
            params=params,
            meta_extra={"request_id": resolved_request_id},
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
