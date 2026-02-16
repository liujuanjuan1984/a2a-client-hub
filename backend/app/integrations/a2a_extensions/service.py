"""Service facade for A2A Agent Card extensions."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx
from a2a.types import AgentCard

from app.core.config import settings
from app.core.logging import get_logger
from app.integrations.a2a_client import get_a2a_service
from app.integrations.a2a_client.errors import (
    A2AAgentUnavailableError,
    A2AClientResetRequiredError,
)
from app.integrations.a2a_extensions.errors import A2AExtensionUpstreamError
from app.integrations.a2a_extensions.jsonrpc import JsonRpcClient
from app.integrations.a2a_extensions.metrics import a2a_extension_metrics
from app.integrations.a2a_extensions.opencode_session_query import (
    resolve_opencode_session_query,
)
from app.integrations.a2a_extensions.types import ResolvedExtension
from app.services.a2a_runtime import A2ARuntime
from app.utils.outbound_url import (
    OutboundURLNotAllowedError,
    validate_outbound_http_url,
)

logger = get_logger(__name__)


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
        self._http: Optional[httpx.AsyncClient] = None
        self._jsonrpc: Optional[JsonRpcClient] = None

    async def _get_http(self) -> httpx.AsyncClient:
        async with self._lock:
            if self._http and not self._http.is_closed:
                return self._http
            timeout = httpx.Timeout(
                max(settings.a2a_default_timeout, 1.0),
                connect=10.0,
            )
            limits = httpx.Limits(
                max_connections=max(settings.a2a_max_connections, 1),
                max_keepalive_connections=max(1, settings.a2a_max_connections // 2),
            )
            self._http = httpx.AsyncClient(timeout=timeout, limits=limits)
            self._jsonrpc = JsonRpcClient(self._http)
            return self._http

    async def shutdown(self) -> None:
        async with self._lock:
            http = self._http
            self._http = None
            self._jsonrpc = None
        if http and not http.is_closed:
            await http.aclose()

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
                allowed_hosts=settings.a2a_proxy_allowed_hosts,
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
    ) -> Dict[str, int]:
        if mode == "page_size":
            return {"page": page, "size": size}
        if mode == "limit":
            return {"offset": (page - 1) * size, "limit": size}
        raise ValueError(f"unsupported pagination mode: {mode}")

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
        code = error.get("code")
        mapped = None
        if isinstance(code, int):
            mapped = ext.business_code_map.get(code)
        elif isinstance(code, str) and code.strip().lstrip("-").isdigit():
            mapped = ext.business_code_map.get(int(code.strip()))
        return mapped or "upstream_error"

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
        meta_extra: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        method_name = ext.methods[method_key]
        metric_key = f"{ext.uri}:{method_name}"
        await self._get_http()
        assert self._jsonrpc is not None  # constructed alongside _http
        try:
            resp = await self._call_with_retry(
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
                    "status_code": exc.response.status_code if exc.response else None,
                },
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise A2AExtensionUpstreamError(
                message=str(exc),
                error_code="upstream_error",
                upstream_error={"message": str(exc), "type": type(exc).__name__},
            ) from exc

        meta = {
            "extension_uri": ext.uri,
            "jsonrpc_fallback_used": ext.jsonrpc.fallback_used,
            "pagination_mode": ext.pagination.mode,
            "page": page,
            "size": size,
            "max_size": ext.pagination.max_size,
            "default_size": ext.pagination.default_size,
        }
        if meta_extra:
            meta.update(meta_extra)

        if resp.ok:
            normalized = self._normalize_envelope(
                resp.result,
                page=page,
                size=size,
            )
            a2a_extension_metrics.record_call(
                metric_key,
                success=True,
                error_code=None,
            )
            return ExtensionCallResult(success=True, result=normalized, meta=meta)

        error = resp.error or {}
        error_code = self._map_business_error_code(error, ext)
        a2a_extension_metrics.record_call(
            metric_key,
            success=False,
            error_code=error_code,
        )
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

        params: Dict[str, Any] = self._build_pagination_params(
            mode=ext.pagination.mode,
            page=resolved_page,
            size=resolved_size,
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

        params: Dict[str, Any] = {
            "session_id": resolved_session_id,
            **self._build_pagination_params(
                mode=ext.pagination.mode,
                page=resolved_page,
                size=resolved_size,
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
        - It returns `metadata.opencode_session_id` as the strict invoke-time
          binding key expected by opencode-a2a-serve.
        """

        resolved_session_id = (session_id or "").strip()
        if not resolved_session_id:
            raise ValueError("session_id is required")

        validation = await self.opencode_get_session_messages(
            runtime=runtime,
            session_id=resolved_session_id,
            page=1,
            size=1,
            query=None,
        )
        if not validation.success:
            return validation

        meta = dict(validation.meta or {})
        meta.update(
            {
                "binding_mode": "contextId+metadata",
                "validated": True,
            }
        )
        return ExtensionCallResult(
            success=True,
            result={
                "contextId": resolved_session_id,
                "provider": "opencode",
                "metadata": {
                    "opencode_session_id": resolved_session_id,
                },
            },
            meta=meta,
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
