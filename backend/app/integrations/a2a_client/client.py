"""A2A client facade with binding-aware adapter selection."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List, Optional
from urllib.parse import urlsplit, urlunsplit

import httpx
from a2a.client import (
    A2ACardResolver,
    ClientCallInterceptor,
    ClientEvent,
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
    SDK_DIALECT,
    JsonRpcPascalAdapter,
    SDKA2AAdapter,
)
from app.integrations.a2a_client.controls import summarize_query
from app.integrations.a2a_client.dialect_cache import global_dialect_cache
from app.integrations.a2a_client.errors import (
    A2AAgentUnavailableError,
    A2AClientResetRequiredError,
    A2AOutboundNotAllowedError,
    A2APeerProtocolError,
    A2AUnsupportedBindingError,
)
from app.integrations.a2a_client.http_clients import (
    borrow_shared_sdk_transport_http_client,
)
from app.integrations.a2a_client.models import A2AMessageRequest
from app.integrations.a2a_client.selection import (
    build_peer_descriptor,
    normalize_transport_label,
)
from app.services.a2a_proxy_service import a2a_proxy_service
from app.utils.async_cleanup import await_cancel_safe
from app.utils.logging_redaction import redact_url_for_logging
from app.utils.outbound_url import (
    OutboundURLNotAllowedError,
    validate_outbound_http_url,
)

logger = get_logger(__name__)


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

    client: Any


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
        self._peer_descriptor = None
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

        logger.debug(
            "A2A client facade created for %s", redact_url_for_logging(self.agent_url)
        )

    async def call_agent(
        self,
        query: str,
        *,
        context_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute a blocking request against the downstream agent."""

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
            http_error = _unwrap_httpx_error(exc)
            if http_error and _should_reset_http_error(http_error):
                logger.warning(
                    "Detected unrecoverable HTTP error, scheduling client reset",
                    extra={
                        "agent_url": redact_url_for_logging(self.agent_url),
                        "error_type": type(http_error).__name__,
                    },
                )
                raise A2AClientResetRequiredError(str(http_error)) from exc
            logger.exception(
                "Blocking invocation to %s failed",
                redact_url_for_logging(self.agent_url),
            )
            return {
                "success": False,
                "agent_url": self.agent_url,
                "error": str(exc),
            }

    async def stream_agent(
        self,
        query: str,
        *,
        context_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[Any]:
        """Stream responses from the downstream agent."""

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

    async def cancel_task(
        self,
        task_id: str,
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Cancel one upstream A2A task by task id."""

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
        except Exception as exc:  # noqa: BLE001
            http_error = _unwrap_httpx_error(exc)
            if http_error and _should_reset_http_error(http_error):
                raise A2AClientResetRequiredError(str(http_error)) from exc
            logger.exception(
                "Failed to cancel A2A task %s for %s",
                normalized_task_id,
                redact_url_for_logging(self.agent_url),
            )
            return {
                "success": False,
                "agent_url": self.agent_url,
                "task_id": normalized_task_id,
                "error": str(exc),
                "error_code": "cancel_failed",
            }

    async def get_agent_card(self) -> AgentCard:
        """Fetch (and cache) the agent card."""

        if self._agent_card is not None:
            return self._agent_card

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
        resolver = self._build_card_resolver(httpx_client)
        logger.info(
            "Requesting A2A agent card",
            extra={
                "agent_url": redact_url_for_logging(self.agent_url),
                "resolver_base": redact_url_for_logging(resolver.base_url),
                "card_path": resolver.agent_card_path.split("?", 1)[0].split("#", 1)[0],
            },
        )
        fetch_timeout = self._card_fetch_timeout
        try:
            if fetch_timeout and fetch_timeout > 0:
                card = await asyncio.wait_for(
                    resolver.get_agent_card(http_kwargs=request_http_kwargs),
                    timeout=fetch_timeout,
                )
            else:
                card = await resolver.get_agent_card(http_kwargs=request_http_kwargs)
        except asyncio.TimeoutError as exc:
            logger.warning(
                "Timed out requesting A2A agent card",
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
                "Failed to retrieve A2A agent card",
                exc_info=True,
                extra={"agent_url": redact_url_for_logging(self.agent_url)},
            )
            raise A2AAgentUnavailableError(
                f"Failed to fetch metadata for A2A agent "
                f"'{redact_url_for_logging(self.agent_url)}'"
            ) from exc

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
                    await self._reset_adapter(dialect=dialect, adapter=adapter)
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

    async def _invoke_with_jsonrpc_fallback(self, *, callback) -> Any:
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
                    await self._reset_adapter(dialect=dialect, adapter=adapter)
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

    async def _get_peer_descriptor(self):
        if self._peer_descriptor is not None:
            return self._peer_descriptor
        await self.get_agent_card()
        if self._peer_descriptor is None:
            raise A2AAgentUnavailableError(
                f"A2A agent '{redact_url_for_logging(self.agent_url)}' has no "
                "resolved peer descriptor"
            )
        return self._peer_descriptor

    async def _get_adapter(self, dialect: str):
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
                adapter = SDKA2AAdapter(
                    descriptor,
                    transport_http_client=sdk_transport_http_client,
                    shared_transport_lease=shared_transport_lease,
                    interceptors=list(self._interceptors),
                    consumers=list(self._consumers),
                    use_client_preference=self._use_client_preference,
                    supported_transports=list(self._supported_transports),
                )
            elif dialect == JSONRPC_PASCAL_DIALECT:
                adapter = JsonRpcPascalAdapter(
                    descriptor,
                    http_client=httpx_client,
                    headers=self._default_headers,
                    timeout=self._timeout,
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
            await await_cancel_safe(entry.client.close())
        except Exception:  # pragma: no cover - defensive cleanup
            logger.debug(
                "Failed to discard failed A2A adapter",
                exc_info=True,
                extra={"dialect": dialect},
            )

    async def _reset_adapter(self, *, dialect: str, adapter: Any) -> None:
        if isinstance(adapter, SDKA2AAdapter):
            try:
                await adapter.invalidate_borrowed_transport()
            except Exception:  # pragma: no cover - defensive cleanup
                logger.debug(
                    "Failed to invalidate shared SDK transport",
                    exc_info=True,
                    extra={"dialect": dialect},
                )
        await self._discard_adapter(dialect, expected_adapter=adapter)

    async def _get_preferred_dialects(self, descriptor) -> list[str]:
        if normalize_transport_label(descriptor.selected_transport) != "JSONRPC":
            return [SDK_DIALECT]
        cached = global_dialect_cache.get(
            agent_url=descriptor.agent_url,
            card_fingerprint=descriptor.card_fingerprint,
        )
        if cached:
            return [cached]
        return [SDK_DIALECT, JSONRPC_PASCAL_DIALECT]

    @staticmethod
    def _should_try_alternate_dialect(
        *,
        descriptor,
        dialect: str,
        exc: Exception,
    ) -> bool:
        if normalize_transport_label(descriptor.selected_transport) != "JSONRPC":
            return False
        if dialect != SDK_DIALECT:
            return False
        if isinstance(exc, A2APeerProtocolError):
            return exc.error_code == "method_not_found" or exc.code == -32601
        return False

    def _build_card_resolver(self, httpx_client: httpx.AsyncClient) -> A2ACardResolver:
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

            card_path = candidate_path
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
        if _is_closed_http_client_error(exc):
            return True
        http_error = _unwrap_httpx_error(exc)
        return bool(http_error and isinstance(http_error, httpx.TransportError))

    @staticmethod
    def _extract_text_from_payload(payload: ClientEvent | Message) -> Optional[str]:
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
                    text = str(value).strip()
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
    current = exc
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


def _should_reset_http_error(error: httpx.HTTPError) -> bool:
    if isinstance(error, httpx.TransportError):
        return True
    if isinstance(error, httpx.HTTPStatusError) and error.response is not None:
        return error.response.status_code in {401, 403}
    return False


__all__ = ["A2AClient", "ClientCacheEntry"]
