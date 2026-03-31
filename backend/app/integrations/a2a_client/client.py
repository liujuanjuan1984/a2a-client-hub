"""A2A client facade with binding-aware adapter selection."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional, cast
from urllib.parse import urlsplit, urlunsplit

import httpx
from a2a.client import (
    A2ACardResolver,
    ClientCallInterceptor,
    Consumer,
)
from a2a.client.errors import A2AClientHTTPError
from a2a.types import AgentCard, Message, TextPart, TransportProtocol
from a2a.utils.constants import (
    AGENT_CARD_WELL_KNOWN_PATH,
    EXTENDED_AGENT_CARD_PATH,
    PREV_AGENT_CARD_WELL_KNOWN_PATH,
)

from app.core.http_client import get_global_http_client
from app.core.logging import get_logger
from app.integrations.a2a_client.adapters import (
    JSONRPC_PASCAL_DIALECT,
    JSONRPC_SLASH_DIALECT,
    SDK_DIALECT,
    JsonRpcPascalAdapter,
    JsonRpcSlashAdapter,
    SDKA2AAdapter,
)
from app.integrations.a2a_client.adapters.base import A2AAdapter
from app.integrations.a2a_client.adapters.sdk import SDKA2AAdapterRetiredError
from app.integrations.a2a_client.controls import summarize_query
from app.integrations.a2a_client.dialect_cache import global_dialect_cache
from app.integrations.a2a_client.errors import (
    A2AAgentUnavailableError,
    A2AClientResetRequiredError,
    A2AOutboundNotAllowedError,
    A2APeerProtocolError,
    A2AUnsupportedBindingError,
    A2AUnsupportedOperationError,
    A2AUpstreamTimeoutError,
)
from app.integrations.a2a_client.http_clients import (
    SharedSDKTransportInvalidatedError,
    borrow_shared_sdk_transport_http_client,
    get_shared_sdk_transport_bucket_snapshot,
)
from app.integrations.a2a_client.lifecycle import (
    A2AClientLifecycleSnapshot,
    AdapterLifecycleSnapshot,
)
from app.integrations.a2a_client.models import A2AMessageRequest, A2APeerDescriptor
from app.integrations.a2a_client.selection import (
    build_peer_descriptor,
    normalize_transport_label,
)
from app.integrations.a2a_error_contract import (
    build_upstream_error_details_from_protocol_error,
)
from app.runtime.a2a_proxy_service import a2a_proxy_service
from app.utils.async_cleanup import await_cancel_safe
from app.utils.logging_redaction import redact_url_for_logging
from app.utils.outbound_url import (
    OutboundURLNotAllowedError,
    validate_outbound_http_url,
)

logger = get_logger(__name__)

AUTHENTICATED_EXTENDED_AGENT_CARD_HTTP_PATH = "/v1/card"


class StaticHeaderInterceptor(ClientCallInterceptor):
    """Interceptor that injects static HTTP headers into every outbound request."""

    def __init__(self, headers: Dict[str, str]) -> None:
        self._headers = {k: v for k, v in headers.items() if v is not None}

    async def intercept(
        self,
        _method_name: str,
        request_payload: Dict[str, Any],
        http_kwargs: Dict[str, Any],
        _agent_card: AgentCard | None,
        _context: Any,
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        headers = dict(http_kwargs.get("headers") or {})
        headers.update(self._headers)
        http_kwargs["headers"] = headers
        return request_payload, http_kwargs


@dataclass(slots=True)
class ClientCacheEntry:
    """Backward-compatible adapter cache entry used by tests and cleanup."""

    client: A2AAdapter


class A2AClient:
    """High-level facade that encapsulates peer discovery and adapter selection."""

    def __init__(
        self,
        agent_url: str,
        *,
        timeout: Optional[httpx.Timeout] = None,
        timeout_seconds: Optional[float] = None,
        borrowed_http_client: Optional[httpx.AsyncClient] = None,
        owned_http_client: Optional[httpx.AsyncClient] = None,
        interceptors: Optional[List[ClientCallInterceptor]] = None,
        consumers: Optional[List[Consumer]] = None,
        use_client_preference: bool = False,
        default_headers: Optional[Dict[str, str]] = None,
        card_fetch_timeout: Optional[float] = None,
        supported_transports: Optional[List[TransportProtocol | str]] = None,
    ) -> None:
        self.agent_url = agent_url.rstrip("/")
        self._agent_card: Optional[AgentCard] = None
        self._authenticated_extended_agent_card: Optional[AgentCard] = None
        self._peer_descriptor: A2APeerDescriptor | None = None
        self._timeout = timeout or self._build_timeout(timeout_seconds)
        self._http_client, self._owns_http_client = (
            self._resolve_http_client_dependency(
                borrowed_http_client=borrowed_http_client,
                owned_http_client=owned_http_client,
            )
        )

        self._interceptors = list(interceptors or [])
        self._consumers = list(consumers or [])
        self._use_client_preference = use_client_preference
        self._default_headers = dict(default_headers or {})
        if self._default_headers and not any(
            isinstance(interceptor, StaticHeaderInterceptor)
            for interceptor in self._interceptors
        ):
            self._interceptors.append(StaticHeaderInterceptor(self._default_headers))

        self._card_fetch_timeout = card_fetch_timeout
        self._supported_transports = list(
            supported_transports
            if supported_transports is not None
            else [
                TransportProtocol.jsonrpc,
                TransportProtocol.http_json,
            ]
        )

        self._adapter_lock = asyncio.Lock()
        self._clients: Dict[str, ClientCacheEntry] = {}
        self._request_lock = asyncio.Lock()
        self._active_requests = 0

        logger.debug(
            "A2A client facade created for %s", redact_url_for_logging(self.agent_url)
        )

    def is_busy(self) -> bool:
        """Report whether this facade currently has in-flight work."""

        return self._active_requests > 0

    def get_lifecycle_snapshot(self) -> A2AClientLifecycleSnapshot:
        adapter_snapshots: list[AdapterLifecycleSnapshot] = []
        for entry in self._clients.values():
            snapshot_fn = getattr(entry.client, "get_lifecycle_snapshot", None)
            if callable(snapshot_fn):
                adapter_snapshots.append(snapshot_fn())
                continue
            dialect = getattr(entry.client, "dialect", type(entry.client).__name__)
            adapter_snapshots.append(
                AdapterLifecycleSnapshot(
                    dialect=str(dialect),
                    active_operations=0,
                    retired=False,
                    closed=False,
                )
            )
        shared_transport = None
        if self._http_client is None or not self._owns_http_client:
            shared_transport = get_shared_sdk_transport_bucket_snapshot(
                timeout=self._timeout
            )
        return A2AClientLifecycleSnapshot(
            active_requests=self._active_requests,
            busy=self.is_busy(),
            cached_adapter_count=len(self._clients),
            adapter_snapshots=tuple(adapter_snapshots),
            shared_transport=shared_transport,
        )

    async def call_agent(
        self,
        query: str,
        *,
        context_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute a blocking request against the downstream agent."""

        async with self._request_usage():
            logger.info(
                "Calling A2A agent %s (blocking)",
                redact_url_for_logging(self.agent_url),
                extra={
                    "query_meta": summarize_query(query),
                },
            )

            try:
                request = A2AMessageRequest(
                    query=query,
                    context_id=context_id,
                    metadata=metadata,
                )
                final_payload = await self._send_with_fallback(request)

                if final_payload is None:
                    logger.error(
                        "No response returned from %s",
                        redact_url_for_logging(self.agent_url),
                    )
                    return {
                        "success": False,
                        "agent_url": self.agent_url,
                        "error": "No response received from agent.",
                    }

                content = self._extract_text_from_payload(final_payload)
                if content is None:
                    fallback_payload = _as_plain_serializable(final_payload)
                    if isinstance(fallback_payload, str):
                        content = fallback_payload.strip()
                    else:
                        content = json.dumps(
                            fallback_payload,
                            ensure_ascii=False,
                            indent=2,
                            default=_json_fallback,
                        ).strip()
                    if not content:
                        content = str(final_payload).strip()

                logger.info("A2A agent call succeeded (chars=%s)", len(content))
                return {
                    "success": True,
                    "agent_url": self.agent_url,
                    "content": content,
                    "raw": final_payload,
                }
            except Exception as exc:  # noqa: BLE001
                translated_error = _translate_httpx_error(exc, agent_url=self.agent_url)
                if isinstance(translated_error, A2AClientResetRequiredError):
                    logger.warning(
                        "Detected unrecoverable HTTP error, scheduling client reset",
                        extra={
                            "agent_url": redact_url_for_logging(self.agent_url),
                            "error_type": type(translated_error).__name__,
                        },
                    )
                    raise translated_error from exc
                if translated_error is not None:
                    exc = translated_error
                logger.exception(
                    "Blocking invocation to %s failed",
                    redact_url_for_logging(self.agent_url),
                )
                error_details = (
                    build_upstream_error_details_from_protocol_error(exc)
                    if isinstance(exc, A2APeerProtocolError)
                    else None
                )
                return {
                    "success": False,
                    "agent_url": self.agent_url,
                    "error": str(exc),
                    "error_code": (
                        error_details.error_code
                        if error_details is not None
                        else getattr(exc, "error_code", None)
                    ),
                    "source": (
                        error_details.source if error_details is not None else None
                    ),
                    "jsonrpc_code": (
                        error_details.jsonrpc_code
                        if error_details is not None
                        else None
                    ),
                    "missing_params": (
                        list(error_details.missing_params or [])
                        if error_details is not None
                        else None
                    ),
                    "upstream_error": (
                        error_details.upstream_error
                        if error_details is not None
                        else None
                    ),
                }

    async def stream_agent(
        self,
        query: str,
        *,
        context_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[Any]:
        """Stream responses from the downstream agent."""

        try:
            async with self._request_usage():
                logger.info(
                    "Calling A2A agent %s (streaming)",
                    redact_url_for_logging(self.agent_url),
                    extra={
                        "query_meta": summarize_query(query),
                    },
                )

                request = A2AMessageRequest(
                    query=query,
                    context_id=context_id,
                    metadata=metadata,
                )
                async for payload in self._stream_with_fallback(request):
                    yield payload
        except Exception as exc:  # noqa: BLE001
            translated_error = _translate_httpx_error(exc, agent_url=self.agent_url)
            if translated_error is not None:
                raise translated_error from exc
            raise

    async def cancel_task(
        self,
        task_id: str,
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Cancel one upstream A2A task by task id."""

        async with self._request_usage():
            normalized_task_id = task_id.strip() if isinstance(task_id, str) else ""
            if not normalized_task_id:
                return {
                    "success": False,
                    "agent_url": self.agent_url,
                    "task_id": normalized_task_id,
                    "error": "Task id is required.",
                    "error_code": "invalid_task_id",
                }

            try:
                task = await self._cancel_with_fallback(
                    normalized_task_id,
                    metadata=metadata,
                )
                logger.info(
                    "Cancelled A2A task %s for %s",
                    normalized_task_id,
                    redact_url_for_logging(self.agent_url),
                )
                return {
                    "success": True,
                    "agent_url": self.agent_url,
                    "task_id": normalized_task_id,
                    "task": task,
                }
            except A2AClientHTTPError as exc:
                status_code = getattr(exc, "status_code", None)
                error_code = "cancel_failed"
                if status_code == 404:
                    error_code = "task_not_found"
                elif status_code == 409:
                    error_code = "task_not_cancelable"
                logger.warning(
                    "Failed to cancel A2A task %s for %s",
                    normalized_task_id,
                    redact_url_for_logging(self.agent_url),
                    extra={"status_code": status_code},
                )
                return {
                    "success": False,
                    "agent_url": self.agent_url,
                    "task_id": normalized_task_id,
                    "error": str(exc),
                    "error_code": error_code,
                }
            except A2APeerProtocolError as exc:
                return {
                    "success": False,
                    "agent_url": self.agent_url,
                    "task_id": normalized_task_id,
                    "error": str(exc),
                    "error_code": getattr(exc, "error_code", "cancel_failed"),
                }
            except A2AUnsupportedOperationError as exc:
                return {
                    "success": False,
                    "agent_url": self.agent_url,
                    "task_id": normalized_task_id,
                    "error": str(exc),
                    "error_code": getattr(exc, "error_code", "unsupported_operation"),
                }
            except Exception as exc:  # noqa: BLE001
                translated_error = _translate_httpx_error(exc, agent_url=self.agent_url)
                if isinstance(translated_error, A2AClientResetRequiredError):
                    raise translated_error from exc
                resolved_error = translated_error or exc
                logger.exception(
                    "Failed to cancel A2A task %s for %s",
                    normalized_task_id,
                    redact_url_for_logging(self.agent_url),
                )
                return {
                    "success": False,
                    "agent_url": self.agent_url,
                    "task_id": normalized_task_id,
                    "error": str(resolved_error),
                    "error_code": getattr(
                        resolved_error,
                        "error_code",
                        "cancel_failed",
                    ),
                }

    async def get_task(
        self,
        task_id: str,
        *,
        history_length: int | None = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Fetch one upstream A2A task by task id."""

        async with self._request_usage():
            normalized_task_id = task_id.strip() if isinstance(task_id, str) else ""
            if not normalized_task_id:
                return {
                    "success": False,
                    "agent_url": self.agent_url,
                    "task_id": normalized_task_id,
                    "error": "Task id is required.",
                    "error_code": "invalid_task_id",
                }

            try:
                task = await self._get_task_with_fallback(
                    normalized_task_id,
                    history_length=history_length,
                    metadata=metadata,
                )
                logger.info(
                    "Fetched A2A task %s for %s",
                    normalized_task_id,
                    redact_url_for_logging(self.agent_url),
                )
                return {
                    "success": True,
                    "agent_url": self.agent_url,
                    "task_id": normalized_task_id,
                    "task": task,
                }
            except A2AClientHTTPError as exc:
                status_code = getattr(exc, "status_code", None)
                error_code = "task_query_failed"
                if status_code == 404:
                    error_code = "task_not_found"
                elif status_code in {400, 405, 409, 501}:
                    error_code = "unsupported_operation"
                logger.warning(
                    "Failed to fetch A2A task %s for %s",
                    normalized_task_id,
                    redact_url_for_logging(self.agent_url),
                    extra={"status_code": status_code},
                )
                return {
                    "success": False,
                    "agent_url": self.agent_url,
                    "task_id": normalized_task_id,
                    "error": str(exc),
                    "error_code": error_code,
                }
            except A2APeerProtocolError as exc:
                return {
                    "success": False,
                    "agent_url": self.agent_url,
                    "task_id": normalized_task_id,
                    "error": str(exc),
                    "error_code": getattr(exc, "error_code", "task_query_failed"),
                }
            except A2AUnsupportedOperationError as exc:
                return {
                    "success": False,
                    "agent_url": self.agent_url,
                    "task_id": normalized_task_id,
                    "error": str(exc),
                    "error_code": getattr(exc, "error_code", "unsupported_operation"),
                }
            except Exception as exc:  # noqa: BLE001
                translated_error = _translate_httpx_error(exc, agent_url=self.agent_url)
                if isinstance(translated_error, A2AClientResetRequiredError):
                    raise translated_error from exc
                resolved_error = translated_error or exc
                logger.exception(
                    "Failed to fetch A2A task %s for %s",
                    normalized_task_id,
                    redact_url_for_logging(self.agent_url),
                )
                return {
                    "success": False,
                    "agent_url": self.agent_url,
                    "task_id": normalized_task_id,
                    "error": str(resolved_error),
                    "error_code": getattr(
                        resolved_error,
                        "error_code",
                        "task_query_failed",
                    ),
                }

    async def get_agent_card(self) -> AgentCard:
        """Fetch (and cache) the agent card."""

        async with self._request_usage():
            if self._agent_card is not None:
                return self._agent_card
            card = await self._fetch_card(
                agent_card_path_override=None,
                log_label="A2A agent card",
            )

            selected_transport, selected_url, supported_labels = (
                self._resolve_negotiated_transport_target(card)
            )
            if not selected_transport or not selected_url:
                supported = ", ".join(supported_labels)
                raise A2AAgentUnavailableError(
                    f"A2A agent '{redact_url_for_logging(self.agent_url)}' has no "
                    f"compatible transports (client supports: {supported})"
                )

            selected_transport_label = (
                selected_transport.value
                if isinstance(selected_transport, TransportProtocol)
                else str(selected_transport)
            )
            try:
                validate_outbound_http_url(
                    selected_url,
                    allowed_hosts=a2a_proxy_service.get_effective_allowed_hosts_sync(),
                    purpose=f"Agent interface URL ({selected_transport_label})",
                )
            except OutboundURLNotAllowedError as exc:
                raise A2AOutboundNotAllowedError(str(exc)) from exc

            self._agent_card = card
            self._peer_descriptor = build_peer_descriptor(
                agent_url=self.agent_url,
                card=card,
                selected_transport=selected_transport_label,
                selected_url=selected_url,
            )
            logger.info(
                "Fetched agent card for %s (name=%s)",
                redact_url_for_logging(self.agent_url),
                getattr(card, "name", "unknown"),
            )
            return card

    async def get_authenticated_extended_agent_card(self) -> AgentCard:
        """Fetch and cache the authenticated extended agent card when supported."""

        public_card = await self.get_agent_card()
        if not getattr(public_card, "supports_authenticated_extended_card", False):
            raise A2AAgentUnavailableError(
                f"A2A agent '{redact_url_for_logging(self.agent_url)}' does not "
                "advertise an authenticated extended agent card"
            )

        async with self._request_usage():
            if self._authenticated_extended_agent_card is not None:
                return self._authenticated_extended_agent_card

            descriptor = await self._get_peer_descriptor()
            card = await self._fetch_authenticated_extended_agent_card(
                descriptor.selected_transport
            )
            self._authenticated_extended_agent_card = card
            return card

    async def get_agent_resolution(self) -> tuple[AgentCard, Any]:
        """Return the current Agent Card and resolved peer descriptor."""

        card = await self.get_agent_card()
        if self._peer_descriptor is None:
            raise A2AAgentUnavailableError(
                f"A2A agent '{redact_url_for_logging(self.agent_url)}' has no "
                "resolved peer descriptor"
            )
        return card, self._peer_descriptor

    def _resolve_negotiated_transport_target(
        self, card: AgentCard
    ) -> tuple[TransportProtocol | str | None, str | None, list[str]]:
        def _as_display_label(value: TransportProtocol | str | None) -> str:
            if value is None:
                return ""
            if isinstance(value, TransportProtocol):
                return value.value
            return str(value).strip()

        client_set: list[TransportProtocol | str] = list(
            self._supported_transports or [TransportProtocol.jsonrpc]
        )
        if not client_set:
            client_set = [TransportProtocol.jsonrpc]

        supported_labels: list[str] = [
            label
            for label in (_as_display_label(value) for value in client_set)
            if label
        ]
        if not supported_labels:
            supported_labels = [TransportProtocol.jsonrpc.value]

        preferred_transport = (
            getattr(card, "preferred_transport", None) or TransportProtocol.jsonrpc
        )
        preferred_url = getattr(card, "url", "") or ""

        server_set: dict[TransportProtocol | str, str] = {}
        if preferred_transport and preferred_url:
            server_set[preferred_transport] = preferred_url

        for iface in getattr(card, "additional_interfaces", None) or []:
            transport = getattr(iface, "transport", None)
            interface_url = getattr(iface, "url", "") or ""
            if transport and interface_url:
                server_set[transport] = interface_url

        if self._use_client_preference:
            for transport in client_set:
                url = server_set.get(transport)
                if url:
                    return transport, url, supported_labels
            return None, None, supported_labels

        for transport, url in server_set.items():
            if transport in client_set:
                return transport, url, supported_labels
        return None, None, supported_labels

    async def close(self) -> None:
        """Dispose cached transport wrappers."""

        async with self._adapter_lock:
            entries = list(self._clients.values())
            self._clients.clear()
            self._agent_card = None
            self._authenticated_extended_agent_card = None
            self._peer_descriptor = None
            owns_http_client = self._owns_http_client
            http_client = self._http_client if owns_http_client else None

        for entry in entries:
            try:
                await await_cancel_safe(entry.client.close())
            except Exception:  # pragma: no cover
                logger.debug("Failed to close A2A adapter", exc_info=True)

        if not owns_http_client:
            return

        if http_client is None:
            return

        try:
            await await_cancel_safe(http_client.aclose())
        except Exception:  # pragma: no cover
            logger.debug("Failed to close dedicated A2A HTTP client", exc_info=True)

    async def _get_http_client(self) -> httpx.AsyncClient:
        return (
            self._http_client
            if self._http_client is not None
            else get_global_http_client()
        )

    async def _send_with_fallback(self, request: A2AMessageRequest) -> Any:
        return await self._invoke_with_jsonrpc_fallback(
            callback=lambda adapter: adapter.send_message(request)
        )

    async def _get_authenticated_extended_agent_card_with_jsonrpc_fallback(
        self,
    ) -> AgentCard:
        return cast(
            AgentCard,
            await self._invoke_with_jsonrpc_fallback(
                callback=lambda adapter: adapter.get_authenticated_extended_agent_card()
            ),
        )

    async def _stream_with_fallback(
        self, request: A2AMessageRequest
    ) -> AsyncIterator[Any]:
        descriptor = await self._get_peer_descriptor()
        last_error: Exception | None = None
        for dialect in await self._get_preferred_dialects(descriptor):
            adapter = await self._get_adapter(dialect)
            did_reset_adapter = False
            yielded_payload = False
            try:
                async for payload in adapter.stream_message(request):
                    yielded_payload = True
                    global_dialect_cache.set(
                        agent_url=descriptor.agent_url,
                        card_fingerprint=descriptor.card_fingerprint,
                        dialect=dialect,
                    )
                    yield payload
                return
            except Exception as exc:  # noqa: BLE001
                if (
                    not yielded_payload
                    and not did_reset_adapter
                    and self._should_reset_adapter_after_error(
                        dialect=dialect,
                        adapter=adapter,
                        exc=exc,
                    )
                ):
                    did_reset_adapter = True
                    await self._reset_adapter_with_policy(
                        dialect=dialect,
                        adapter=adapter,
                        invalidate_transport=(
                            self._should_invalidate_transport_after_error(
                                dialect=dialect,
                                adapter=adapter,
                                exc=exc,
                            )
                        ),
                    )
                    adapter = await self._get_adapter(dialect)
                    logger.info(
                        "Retrying A2A stream after adapter reset",
                        extra={
                            "agent_url": redact_url_for_logging(self.agent_url),
                            "failed_dialect": dialect,
                        },
                    )
                    try:
                        async for payload in adapter.stream_message(request):
                            global_dialect_cache.set(
                                agent_url=descriptor.agent_url,
                                card_fingerprint=descriptor.card_fingerprint,
                                dialect=dialect,
                            )
                            yield payload
                        return
                    except Exception as retry_exc:  # noqa: BLE001
                        exc = retry_exc
                last_error = exc
                if not self._should_try_alternate_dialect(
                    descriptor=descriptor,
                    dialect=dialect,
                    exc=exc,
                ):
                    raise
                await self._discard_adapter(dialect, expected_adapter=adapter)
                logger.info(
                    "Retrying A2A stream with alternate JSON-RPC dialect",
                    extra={
                        "agent_url": redact_url_for_logging(self.agent_url),
                        "failed_dialect": dialect,
                    },
                )
                continue
        if last_error is not None:
            raise last_error

    async def _cancel_with_fallback(
        self,
        task_id: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        return await self._invoke_with_jsonrpc_fallback(
            callback=lambda adapter: adapter.cancel_task(task_id, metadata=metadata)
        )

    async def _get_task_with_fallback(
        self,
        task_id: str,
        *,
        history_length: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        return await self._invoke_with_jsonrpc_fallback(
            callback=lambda adapter: adapter.get_task(
                task_id,
                history_length=history_length,
                metadata=metadata,
            )
        )

    async def _invoke_with_jsonrpc_fallback(
        self, *, callback: Callable[[A2AAdapter], Awaitable[Any]]
    ) -> Any:
        descriptor = await self._get_peer_descriptor()
        last_error: Exception | None = None
        for dialect in await self._get_preferred_dialects(descriptor):
            adapter = await self._get_adapter(dialect)
            did_reset_adapter = False
            try:
                result = await callback(adapter)
                global_dialect_cache.set(
                    agent_url=descriptor.agent_url,
                    card_fingerprint=descriptor.card_fingerprint,
                    dialect=dialect,
                )
                return result
            except Exception as exc:  # noqa: BLE001
                if not did_reset_adapter and self._should_reset_adapter_after_error(
                    dialect=dialect,
                    adapter=adapter,
                    exc=exc,
                ):
                    did_reset_adapter = True
                    await self._reset_adapter_with_policy(
                        dialect=dialect,
                        adapter=adapter,
                        invalidate_transport=(
                            self._should_invalidate_transport_after_error(
                                dialect=dialect,
                                adapter=adapter,
                                exc=exc,
                            )
                        ),
                    )
                    adapter = await self._get_adapter(dialect)
                    logger.info(
                        "Retrying A2A invoke after adapter reset",
                        extra={
                            "agent_url": redact_url_for_logging(self.agent_url),
                            "failed_dialect": dialect,
                        },
                    )
                    try:
                        result = await callback(adapter)
                        global_dialect_cache.set(
                            agent_url=descriptor.agent_url,
                            card_fingerprint=descriptor.card_fingerprint,
                            dialect=dialect,
                        )
                        return result
                    except Exception as retry_exc:  # noqa: BLE001
                        exc = retry_exc
                last_error = exc
                if not self._should_try_alternate_dialect(
                    descriptor=descriptor,
                    dialect=dialect,
                    exc=exc,
                ):
                    raise
                await self._discard_adapter(dialect, expected_adapter=adapter)
                logger.info(
                    "Retrying A2A invoke with alternate JSON-RPC dialect",
                    extra={
                        "agent_url": redact_url_for_logging(self.agent_url),
                        "failed_dialect": dialect,
                    },
                )
                continue
        if last_error is not None:
            raise last_error
        raise A2AAgentUnavailableError("No adapter attempt executed")

    async def _get_peer_descriptor(self) -> A2APeerDescriptor:
        if self._peer_descriptor is not None:
            return self._peer_descriptor
        await self.get_agent_card()
        descriptor = cast(A2APeerDescriptor | None, getattr(self, "_peer_descriptor"))
        if descriptor is None:
            raise A2AAgentUnavailableError(
                f"A2A agent '{redact_url_for_logging(self.agent_url)}' has no "
                "resolved peer descriptor"
            )
        return descriptor

    async def _get_adapter(self, dialect: str) -> A2AAdapter:
        stale_adapter: A2AAdapter | None = None
        async with self._adapter_lock:
            entry = self._clients.get(dialect)
            if entry:
                if (
                    dialect == SDK_DIALECT
                    and isinstance(entry.client, SDKA2AAdapter)
                    and entry.client.is_transport_stale()
                ):
                    stale_adapter = self._clients.pop(dialect).client
                else:
                    return entry.client

        if stale_adapter is not None:
            await self._retire_adapter(stale_adapter)

        async with self._adapter_lock:
            entry = self._clients.get(dialect)
            if entry:
                return entry.client
            descriptor = await self._get_peer_descriptor()
            httpx_client = await self._get_http_client()

            if dialect == SDK_DIALECT:
                shared_transport_lease = None
                sdk_transport_http_client = (
                    self._http_client
                    if self._http_client is not None and self._owns_http_client
                    else None
                )
                if sdk_transport_http_client is None:
                    shared_transport_lease = borrow_shared_sdk_transport_http_client(
                        timeout=self._timeout
                    )
                    sdk_transport_http_client = shared_transport_lease.client
                adapter: A2AAdapter = SDKA2AAdapter(
                    descriptor,
                    transport_http_client=sdk_transport_http_client,
                    shared_transport_lease=shared_transport_lease,
                    interceptors=list(self._interceptors),
                    consumers=list(self._consumers),
                    use_client_preference=self._use_client_preference,
                    supported_transports=list(self._supported_transports),
                )
            elif dialect == JSONRPC_SLASH_DIALECT:
                adapter = JsonRpcSlashAdapter(
                    descriptor,
                    http_client=httpx_client,
                    timeout=self._timeout,
                    interceptors=list(self._interceptors),
                )
            elif dialect == JSONRPC_PASCAL_DIALECT:
                adapter = JsonRpcPascalAdapter(
                    descriptor,
                    http_client=httpx_client,
                    timeout=self._timeout,
                    interceptors=list(self._interceptors),
                )
            else:
                raise A2AUnsupportedBindingError(
                    f"Unsupported A2A adapter dialect: {dialect}"
                )

            self._clients[dialect] = ClientCacheEntry(client=adapter)
            return adapter

    async def _discard_adapter(
        self,
        dialect: str,
        *,
        expected_adapter: Any | None = None,
    ) -> None:
        async with self._adapter_lock:
            entry = self._clients.get(dialect)
            if entry is None:
                return
            if expected_adapter is not None and entry.client is not expected_adapter:
                return
            self._clients.pop(dialect, None)
        try:
            await self._retire_adapter(entry.client)
        except Exception:  # pragma: no cover - defensive cleanup
            logger.debug(
                "Failed to discard failed A2A adapter",
                exc_info=True,
                extra={"dialect": dialect},
            )

    @staticmethod
    async def _retire_adapter(adapter: Any) -> None:
        retire = getattr(adapter, "retire", None)
        if callable(retire):
            await await_cancel_safe(retire())
            return
        await await_cancel_safe(adapter.close())

    async def _reset_adapter_with_policy(
        self,
        *,
        dialect: str,
        adapter: Any,
        invalidate_transport: bool,
    ) -> None:
        if invalidate_transport and isinstance(adapter, SDKA2AAdapter):
            try:
                await adapter.invalidate_borrowed_transport()
            except Exception:  # pragma: no cover - defensive cleanup
                logger.debug(
                    "Failed to invalidate shared SDK transport",
                    exc_info=True,
                    extra={"dialect": dialect},
                )
        await self._discard_adapter(dialect, expected_adapter=adapter)

    async def _get_preferred_dialects(self, descriptor: A2APeerDescriptor) -> list[str]:
        if normalize_transport_label(descriptor.selected_transport) != "JSONRPC":
            return [SDK_DIALECT]
        choices = [JSONRPC_SLASH_DIALECT, JSONRPC_PASCAL_DIALECT]
        cached = global_dialect_cache.get(
            agent_url=descriptor.agent_url,
            card_fingerprint=descriptor.card_fingerprint,
        )
        if cached in choices:
            return [cached, *[dialect for dialect in choices if dialect != cached]]
        return choices

    @staticmethod
    def _should_try_alternate_dialect(
        *,
        descriptor: A2APeerDescriptor,
        dialect: str,
        exc: Exception,
    ) -> bool:
        if normalize_transport_label(descriptor.selected_transport) != "JSONRPC":
            return False
        if dialect != JSONRPC_SLASH_DIALECT:
            return False
        if isinstance(exc, A2APeerProtocolError):
            return exc.error_code == "method_not_found" or exc.code == -32601
        return False

    async def _fetch_authenticated_extended_agent_card(
        self,
        selected_transport: TransportProtocol | str | None,
    ) -> AgentCard:
        fallback_errors: list[Exception] = []
        if normalize_transport_label(selected_transport) == "JSONRPC":
            try:
                return (
                    await self._get_authenticated_extended_agent_card_with_jsonrpc_fallback()
                )
            except (
                A2AAgentUnavailableError,
                A2AClientResetRequiredError,
                A2APeerProtocolError,
                A2AUnsupportedOperationError,
            ) as exc:
                fallback_errors.append(exc)
                logger.info(
                    "Falling back to HTTP authenticated extended A2A agent card fetch",
                    extra={
                        "agent_url": redact_url_for_logging(self.agent_url),
                        "selected_transport": normalize_transport_label(
                            selected_transport
                        ),
                        "error": str(exc),
                    },
                )

        for card_path, log_label in (
            (
                AUTHENTICATED_EXTENDED_AGENT_CARD_HTTP_PATH,
                "authenticated extended A2A agent card",
            ),
            (
                EXTENDED_AGENT_CARD_PATH,
                "authenticated extended A2A agent card compatibility route",
            ),
        ):
            try:
                return await self._fetch_card(
                    agent_card_path_override=card_path,
                    log_label=log_label,
                )
            except A2AAgentUnavailableError as exc:
                fallback_errors.append(exc)
                logger.info(
                    "Authenticated extended A2A agent card fetch failed",
                    extra={
                        "agent_url": redact_url_for_logging(self.agent_url),
                        "card_path": card_path,
                        "error": str(exc),
                    },
                )

        if fallback_errors:
            raise A2AAgentUnavailableError(
                str(fallback_errors[-1])
            ) from fallback_errors[-1]
        raise A2AAgentUnavailableError(
            f"Failed to fetch metadata for A2A agent "
            f"'{redact_url_for_logging(self.agent_url)}'"
        )

    async def _fetch_card(
        self,
        *,
        agent_card_path_override: str | None,
        log_label: str,
    ) -> AgentCard:
        try:
            validate_outbound_http_url(
                self.agent_url,
                allowed_hosts=a2a_proxy_service.get_effective_allowed_hosts_sync(),
                purpose="Agent card URL",
            )
        except OutboundURLNotAllowedError as exc:
            raise A2AOutboundNotAllowedError(str(exc)) from exc

        httpx_client = await self._get_http_client()
        request_http_kwargs: Dict[str, Any] = {}
        if self._default_headers:
            request_http_kwargs["headers"] = dict(self._default_headers)
        request_http_kwargs["timeout"] = self._timeout
        resolver = self._build_card_resolver(
            httpx_client,
            agent_card_path_override=agent_card_path_override,
        )
        logger.info(
            "Requesting %s",
            log_label,
            extra={
                "agent_url": redact_url_for_logging(self.agent_url),
                "resolver_base": redact_url_for_logging(resolver.base_url),
                "card_path": resolver.agent_card_path.split("?", 1)[0].split("#", 1)[0],
            },
        )
        fetch_timeout = self._card_fetch_timeout
        try:
            if fetch_timeout and fetch_timeout > 0:
                return await asyncio.wait_for(
                    resolver.get_agent_card(http_kwargs=request_http_kwargs),
                    timeout=fetch_timeout,
                )
            return await resolver.get_agent_card(http_kwargs=request_http_kwargs)
        except asyncio.TimeoutError as exc:
            logger.warning(
                "Timed out requesting %s",
                log_label,
                extra={
                    "agent_url": redact_url_for_logging(self.agent_url),
                    "timeout_seconds": fetch_timeout,
                },
            )
            raise A2AAgentUnavailableError(
                f"A2A agent '{redact_url_for_logging(self.agent_url)}' timed out while "
                "fetching metadata"
            ) from exc
        except Exception as exc:
            logger.warning(
                "Failed to retrieve %s",
                log_label,
                exc_info=True,
                extra={"agent_url": redact_url_for_logging(self.agent_url)},
            )
            raise A2AAgentUnavailableError(
                f"Failed to fetch metadata for A2A agent "
                f"'{redact_url_for_logging(self.agent_url)}'"
            ) from exc

    def _build_card_resolver(
        self,
        httpx_client: httpx.AsyncClient,
        *,
        agent_card_path_override: str | None = None,
    ) -> A2ACardResolver:
        """Create a resolver that avoids duplicating well-known paths."""

        parsed_url = urlsplit(self.agent_url)
        path = parsed_url.path or ""
        normalized_path = path.rstrip("/")
        normalized_no_leading = normalized_path.lstrip("/")

        candidate_paths = (
            AGENT_CARD_WELL_KNOWN_PATH,
            PREV_AGENT_CARD_WELL_KNOWN_PATH,
            EXTENDED_AGENT_CARD_PATH,
        )

        for candidate_path in candidate_paths:
            card_suffix = candidate_path.lstrip("/")
            if not normalized_no_leading.endswith(card_suffix):
                continue

            base_path = normalized_no_leading[: -len(card_suffix)].rstrip("/")
            base_url = urlunsplit(
                (
                    parsed_url.scheme,
                    parsed_url.netloc,
                    f"/{base_path}" if base_path else "",
                    "",
                    "",
                )
            ).rstrip("/")

            card_path = agent_card_path_override or candidate_path
            if parsed_url.query:
                card_path = f"{card_path}?{parsed_url.query}"
            if parsed_url.fragment:
                card_path = f"{card_path}#{parsed_url.fragment}"

            base_url = base_url or f"{parsed_url.scheme}://{parsed_url.netloc}"
            return A2ACardResolver(
                httpx_client=httpx_client,
                base_url=base_url,
                agent_card_path=card_path,
            )

        if agent_card_path_override is not None:
            return A2ACardResolver(
                httpx_client=httpx_client,
                base_url=self.agent_url,
                agent_card_path=agent_card_path_override,
            )
        return A2ACardResolver(httpx_client=httpx_client, base_url=self.agent_url)

    @staticmethod
    def _build_timeout(timeout_seconds: Optional[float]) -> httpx.Timeout:
        if timeout_seconds and timeout_seconds > 0:
            return httpx.Timeout(timeout_seconds)
        return httpx.Timeout(10.0, connect=10.0)

    @staticmethod
    def _resolve_http_client_dependency(
        *,
        borrowed_http_client: httpx.AsyncClient | None,
        owned_http_client: httpx.AsyncClient | None,
    ) -> tuple[httpx.AsyncClient | None, bool]:
        if borrowed_http_client is not None and owned_http_client is not None:
            raise ValueError(
                "Use only one of borrowed_http_client or owned_http_client."
            )
        if borrowed_http_client is not None:
            return borrowed_http_client, False
        if owned_http_client is not None:
            return owned_http_client, True
        return None, False

    @staticmethod
    def _should_reset_adapter_after_error(
        *,
        dialect: str,
        adapter: Any,
        exc: Exception,
    ) -> bool:
        if dialect != SDK_DIALECT or not isinstance(adapter, SDKA2AAdapter):
            return False
        if isinstance(exc, SharedSDKTransportInvalidatedError):
            return True
        if isinstance(exc, SDKA2AAdapterRetiredError):
            return True
        if _is_closed_http_client_error(exc):
            return True
        translated_error = _translate_httpx_error(
            exc,
            agent_url=(
                getattr(getattr(adapter, "descriptor", None), "agent_url", None)
                or getattr(getattr(adapter, "descriptor", None), "selected_url", None)
                or ""
            ),
        )
        if isinstance(
            translated_error,
            (A2AAgentUnavailableError, A2AUpstreamTimeoutError),
        ):
            return False
        http_error = _unwrap_httpx_error(exc)
        return bool(http_error and isinstance(http_error, httpx.TransportError))

    @staticmethod
    def _should_invalidate_transport_after_error(
        *,
        dialect: str,
        adapter: Any,
        exc: Exception,
    ) -> bool:
        if dialect != SDK_DIALECT or not isinstance(adapter, SDKA2AAdapter):
            return False
        if isinstance(
            exc,
            (SharedSDKTransportInvalidatedError, SDKA2AAdapterRetiredError),
        ):
            return False
        if _is_closed_http_client_error(exc):
            return True
        translated_error = _translate_httpx_error(
            exc,
            agent_url=(
                getattr(getattr(adapter, "descriptor", None), "agent_url", None)
                or getattr(getattr(adapter, "descriptor", None), "selected_url", None)
                or ""
            ),
        )
        if isinstance(
            translated_error,
            (A2AAgentUnavailableError, A2AUpstreamTimeoutError),
        ):
            return False
        http_error = _unwrap_httpx_error(exc)
        return bool(http_error and isinstance(http_error, httpx.TransportError))

    @asynccontextmanager
    async def _request_usage(self) -> AsyncIterator[None]:
        async with self._request_lock:
            self._active_requests += 1
        try:
            yield
        finally:
            async with self._request_lock:
                if self._active_requests > 0:
                    self._active_requests -= 1

    @staticmethod
    def _extract_text_from_payload(payload: Any) -> Optional[str]:
        """Extract readable text from A2A events or message-like payloads."""

        def extract_from_iterable(items: Any) -> Optional[str]:
            if not isinstance(items, (list, tuple)):
                return None
            for item in items:
                extracted = A2AClient._extract_text_from_payload(item)
                if extracted:
                    return extracted
            return None

        def extract_from_parts(parts: Any) -> Optional[str]:
            if not isinstance(parts, (list, tuple)):
                return None
            collected: list[str] = []
            for part in parts:
                text_part = None
                if isinstance(part, TextPart):
                    text_part = part
                else:
                    root = getattr(part, "root", None)
                    if isinstance(root, TextPart):
                        text_part = root
                    elif isinstance(part, Mapping):
                        text_value = part.get("text")
                        if isinstance(text_value, str) and text_value.strip():
                            collected.append(text_value)
                            continue
                        mapped_root = part.get("root")
                        if isinstance(mapped_root, TextPart):
                            text_part = mapped_root
                        elif isinstance(part.get("role"), str):
                            nested = A2AClient._extract_text_from_payload(part)
                            if nested:
                                collected.append(nested)
                                continue
                if text_part and getattr(text_part, "text", None):
                    collected.append(text_part.text)
            if collected:
                return "\n".join(collected)
            return None

        def extract_from_mapping(payload_map: Mapping) -> Optional[str]:
            for key in (
                "content",
                "message",
                "messages",
                "result",
                "status",
                "text",
                "parts",
                "artifacts",
                "history",
                "events",
                "root",
            ):
                if key not in payload_map:
                    continue
                value = payload_map[key]
                if value in (None, ""):
                    continue
                if key == "text" and isinstance(value, (str, int, float, bool)):
                    text: str | None = str(value).strip()
                    if text:
                        return text
                if key in ("parts",):
                    text = extract_from_parts(value)
                    if text:
                        return text
                if isinstance(value, (list, tuple)) and key in (
                    "messages",
                    "artifacts",
                    "history",
                    "events",
                ):
                    text = extract_from_iterable(value)
                    if text:
                        return text
                text = A2AClient._extract_text_from_payload(value)
                if text:
                    return text
            return None

        if isinstance(payload, Message):
            return extract_from_parts(payload.parts)

        if isinstance(payload, str):
            return payload.strip() or None

        status_payload = getattr(payload, "status", None)
        if status_payload is not None:
            text = A2AClient._extract_text_from_payload(status_payload)
            if text:
                return text

        message_payload = getattr(payload, "message", None)
        if message_payload is not None:
            text = A2AClient._extract_text_from_payload(message_payload)
            if text:
                return text

        result_payload = getattr(payload, "result", None)
        if result_payload is not None:
            text = A2AClient._extract_text_from_payload(result_payload)
            if text:
                return text

        history = getattr(payload, "history", None)
        if isinstance(history, (list, tuple)) and history:
            for item in reversed(history):
                text = A2AClient._extract_text_from_payload(item)
                if text:
                    return text

        artifacts = getattr(payload, "artifacts", None)
        if isinstance(artifacts, (list, tuple)):
            for artifact in artifacts:
                artifact_parts = getattr(artifact, "parts", None)
                if isinstance(artifact_parts, (list, tuple)):
                    text = extract_from_parts(artifact_parts)
                    if text:
                        return text

        text = extract_from_parts(getattr(payload, "parts", None))
        if text:
            return text

        event_text = extract_from_iterable(getattr(payload, "events", None))
        if event_text:
            return event_text

        if isinstance(payload, Mapping):
            mapped_text = extract_from_mapping(payload)
            if mapped_text:
                return mapped_text

        mapping_payload = None
        if hasattr(payload, "dict") and callable(getattr(payload, "dict")):
            payload_dict = payload.dict()
            if isinstance(payload_dict, Mapping):
                mapping_payload = payload_dict
        elif hasattr(payload, "model_dump") and callable(
            getattr(payload, "model_dump")
        ):
            payload_dict = payload.model_dump()
            if isinstance(payload_dict, Mapping):
                mapping_payload = payload_dict
        elif isinstance(getattr(payload, "__dict__", None), Mapping):
            mapping_payload = dict(payload.__dict__)

        if mapping_payload is not None:
            mapped_text = extract_from_mapping(mapping_payload)
            if mapped_text:
                return mapped_text
            event_text = extract_from_iterable(mapping_payload.get("events"))
            if event_text:
                return event_text
            content_text = extract_from_iterable(mapping_payload.get("parts"))
            if content_text:
                return content_text
        return None


def _as_plain_serializable(payload: Any) -> Any:
    if payload is None:
        return None
    if isinstance(payload, (str, int, float, bool)):
        return payload
    if isinstance(payload, list):
        return [_as_plain_serializable(item) for item in payload]
    if isinstance(payload, dict):
        return {
            str(key): _as_plain_serializable(value) for key, value in payload.items()
        }
    for candidate in ("content", "status", "artifacts", "history", "parts", "text"):
        value = getattr(payload, candidate, None)
        if value is not None:
            return {
                "_type": type(payload).__name__,
                candidate: _as_plain_serializable(value),
            }
    return str(payload)


def _json_fallback(value: Any) -> Any:
    if isinstance(value, Message):
        return {
            "message_id": value.message_id,
            "parts": _as_plain_serializable(value.parts),
            "role": getattr(value.role, "value", None),
            "context_id": value.context_id,
            "metadata": value.metadata,
        }
    if isinstance(value, TextPart):
        return {"text": value.text}
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    if hasattr(value, "dict"):
        return _as_plain_serializable(value.dict())
    return str(value)


def _unwrap_httpx_error(exc: Exception) -> Optional[httpx.HTTPError]:
    current: BaseException | None = exc
    visited: set[int] = set()
    while current and id(current) not in visited:
        visited.add(id(current))
        if isinstance(current, httpx.HTTPError):
            return current
        current = getattr(current, "__cause__", None) or getattr(
            current, "__context__", None
        )
    return None


def _is_closed_http_client_error(exc: Exception) -> bool:
    current: Exception | None = exc
    visited: set[int] = set()
    while current and id(current) not in visited:
        visited.add(id(current))
        if isinstance(current, RuntimeError):
            message = str(current).lower()
            if "client has been closed" in message:
                return True
        current = getattr(current, "__cause__", None) or getattr(
            current, "__context__", None
        )
    return False


def _format_upstream_agent_label(agent_url: str) -> str:
    redacted = redact_url_for_logging(agent_url or "")
    return redacted or "<unknown>"


def _translate_httpx_error(
    exc: Exception,
    *,
    agent_url: str,
) -> A2AAgentUnavailableError | A2AClientResetRequiredError | None:
    if _is_closed_http_client_error(exc):
        return A2AClientResetRequiredError("A2A transport client has been closed")

    http_error = _unwrap_httpx_error(exc)
    if http_error is None:
        return None

    agent_label = _format_upstream_agent_label(agent_url)

    if isinstance(http_error, httpx.ConnectTimeout):
        return A2AUpstreamTimeoutError(
            f"A2A agent '{agent_label}' timed out while establishing a connection"
        )

    if isinstance(http_error, httpx.TimeoutException):
        return A2AUpstreamTimeoutError(
            f"A2A agent '{agent_label}' timed out before completing the request"
        )

    if isinstance(http_error, (httpx.ConnectError, httpx.NetworkError)):
        return A2AAgentUnavailableError(f"Unable to reach A2A agent '{agent_label}'")

    if _should_reset_http_error(http_error):
        return A2AClientResetRequiredError(str(http_error))

    return None


def _should_reset_http_error(error: httpx.HTTPError) -> bool:
    if isinstance(error, httpx.TransportError):
        return True
    if isinstance(error, httpx.HTTPStatusError) and error.response is not None:
        return error.response.status_code in {401, 403}
    return False


__all__ = ["A2AClient", "ClientCacheEntry"]
