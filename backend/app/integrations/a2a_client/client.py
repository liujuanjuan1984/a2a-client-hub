"""Async client wrapper around the ``a2a-sdk`` for Compass."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List, Optional
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import httpx
from a2a.client import (
    A2ACardResolver,
    Client,
    ClientCallInterceptor,
    ClientConfig,
    ClientEvent,
    ClientFactory,
    Consumer,
)
from a2a.types import AgentCard, Message, Part, Role, TextPart, TransportProtocol
from a2a.utils.constants import (
    AGENT_CARD_WELL_KNOWN_PATH,
    EXTENDED_AGENT_CARD_PATH,
    PREV_AGENT_CARD_WELL_KNOWN_PATH,
)

from app.core.config import settings
from app.core.logging import get_logger
from app.integrations.a2a_client.controls import summarize_query
from app.integrations.a2a_client.errors import (
    A2AAgentUnavailableError,
    A2AClientResetRequiredError,
    A2AOutboundNotAllowedError,
)
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
    """Cache entry storing resolved configuration and instantiated client."""

    config: ClientConfig
    client: Client


class A2AClient:
    """High-level helper that encapsulates transport negotiation and caching."""

    def __init__(
        self,
        agent_url: str,
        *,
        timeout: Optional[httpx.Timeout] = None,
        timeout_seconds: Optional[float] = None,
        max_connections: int = 20,
        interceptors: Optional[List[ClientCallInterceptor]] = None,
        consumers: Optional[List[Consumer]] = None,
        use_client_preference: bool = False,
        default_headers: Optional[Dict[str, str]] = None,
        card_fetch_timeout: Optional[float] = None,
        supported_transports: Optional[List[TransportProtocol | str]] = None,
    ) -> None:
        self.agent_url = agent_url.rstrip("/")
        self._timeout = timeout or self._build_timeout(timeout_seconds)
        self._limits = httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max(1, max_connections // 2),
        )

        self._httpx_client: Optional[httpx.AsyncClient] = None
        self._agent_card: Optional[AgentCard] = None

        self._interceptors = interceptors or []
        self._consumers = consumers or []
        self._use_client_preference = use_client_preference
        self._default_headers = dict(default_headers or {})
        self._card_fetch_timeout = card_fetch_timeout
        self._supported_transports = supported_transports or [
            TransportProtocol.jsonrpc,
            TransportProtocol.http_json,
        ]

        self._client_lock = asyncio.Lock()
        self._clients: Dict[bool, ClientCacheEntry] = {}

        logger.debug(
            "A2A client wrapper created for %s", redact_url_for_logging(self.agent_url)
        )

    async def call_agent(
        self,
        query: str,
        *,
        context_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Any | None = None,
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
            client = await self._get_client(streaming=False)
            request_metadata = None
            if tools is not None or tool_choice is not None:
                request_metadata = {
                    "tools": tools,
                    "toolChoice": tool_choice,
                }
            message = self._build_message(
                query,
                context_id=context_id,
                metadata=metadata,
            )

            final_payload: Optional[ClientEvent | Message] = None
            async for payload in client.send_message(
                message,
                request_metadata=request_metadata,
            ):
                final_payload = payload

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
                content = str(final_payload)

            logger.info(
                "A2A agent call succeeded (chars=%s)",
                len(content),
            )
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
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Any | None = None,
    ) -> AsyncIterator[Any]:
        """Stream responses from the downstream agent."""

        logger.info(
            "Calling A2A agent %s (streaming)",
            redact_url_for_logging(self.agent_url),
            extra={
                "query_meta": summarize_query(query),
            },
        )

        client = await self._get_client(streaming=True)
        request_metadata = None
        if tools is not None or tool_choice is not None:
            request_metadata = {
                "tools": tools,
                "toolChoice": tool_choice,
            }
        message = self._build_message(
            query,
            context_id=context_id,
            metadata=metadata,
        )
        async for payload in client.send_message(
            message,
            request_metadata=request_metadata,
        ):
            yield payload

    async def get_agent_card(self) -> AgentCard:
        """Fetch (and cache) the agent card."""

        if self._agent_card is not None:
            return self._agent_card

        try:
            validate_outbound_http_url(
                self.agent_url,
                allowed_hosts=settings.a2a_proxy_allowed_hosts,
                purpose="Agent card URL",
            )
        except OutboundURLNotAllowedError as exc:
            raise A2AOutboundNotAllowedError(str(exc)) from exc

        httpx_client = await self._get_http_client()
        resolver = self._build_card_resolver(httpx_client)
        logger.info(
            "Requesting A2A agent card",
            extra={
                "agent_url": redact_url_for_logging(self.agent_url),
                "resolver_base": redact_url_for_logging(resolver.base_url),
                # Drop query/fragment to avoid leaking accidental tokens.
                "card_path": resolver.agent_card_path.split("?", 1)[0].split("#", 1)[0],
            },
        )
        fetch_timeout = self._card_fetch_timeout
        try:
            if fetch_timeout and fetch_timeout > 0:
                card = await asyncio.wait_for(
                    resolver.get_agent_card(), timeout=fetch_timeout
                )
            else:
                card = await resolver.get_agent_card()
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

        # Validate downstream card-declared endpoints before caching. This prevents the
        # SDK transport negotiation from selecting a disallowed interface later.
        try:
            validate_outbound_http_url(
                getattr(card, "url", "") or "",
                allowed_hosts=settings.a2a_proxy_allowed_hosts,
                purpose="Agent URL",
            )
            for iface in getattr(card, "additional_interfaces", None) or []:
                url = (getattr(iface, "url", "") or "").strip()
                if not url:
                    continue
                validate_outbound_http_url(
                    url,
                    allowed_hosts=settings.a2a_proxy_allowed_hosts,
                    purpose="Agent interface URL",
                )
        except OutboundURLNotAllowedError as exc:
            raise A2AOutboundNotAllowedError(str(exc)) from exc

        self._agent_card = card
        logger.info(
            "Fetched agent card for %s (name=%s)",
            redact_url_for_logging(self.agent_url),
            getattr(card, "name", "unknown"),
        )
        return card

    async def close(self) -> None:
        """Dispose httpx client and cached transports."""

        async with self._client_lock:
            for entry in self._clients.values():
                try:
                    await entry.client.close()
                except Exception:  # pragma: no cover - defensive cleanup
                    logger.debug("Failed to close A2A client transport", exc_info=True)
            self._clients.clear()

            if self._httpx_client and not self._httpx_client.is_closed:
                await self._httpx_client.aclose()
            self._httpx_client = None
            self._agent_card = None

    async def _get_client(self, *, streaming: bool) -> Client:
        async with self._client_lock:
            entry = self._clients.get(streaming)
            if entry:
                logger.debug(
                    "Reusing cached transport",
                    extra={
                        "agent_url": redact_url_for_logging(self.agent_url),
                        "streaming": streaming,
                    },
                )
                return entry.client

            httpx_client = await self._get_http_client()
            agent_card = await self.get_agent_card()

            config = ClientConfig(
                streaming=streaming,
                polling=False,
                httpx_client=httpx_client,
                use_client_preference=self._use_client_preference,
                supported_transports=list(self._supported_transports),
            )
            factory = ClientFactory(config=config, consumers=list(self._consumers))
            client = factory.create(
                agent_card,
                consumers=None,
                interceptors=list(self._interceptors),
            )
            self._clients[streaming] = ClientCacheEntry(config=config, client=client)
            logger.info(
                "Created new transport client",
                extra={
                    "agent_url": redact_url_for_logging(self.agent_url),
                    "streaming": streaming,
                },
            )
            return client

    async def _get_http_client(self) -> httpx.AsyncClient:
        if self._httpx_client and not self._httpx_client.is_closed:
            logger.debug(
                "Reusing shared httpx client",
                extra={"agent_url": redact_url_for_logging(self.agent_url)},
            )
            return self._httpx_client

        self._httpx_client = httpx.AsyncClient(
            timeout=self._timeout, limits=self._limits, headers=self._default_headers
        )
        logger.info(
            "Instantiated new httpx client for A2A agent",
            extra={
                "agent_url": redact_url_for_logging(self.agent_url),
                "timeout": getattr(self._timeout, "read", None),
                "default_headers": list(self._default_headers.keys()),
            },
        )
        return self._httpx_client

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
            logger.debug(
                "Detected pre-resolved agent JSON endpoint",
                extra={
                    "agent_url": redact_url_for_logging(self.agent_url),
                    "base_url": redact_url_for_logging(base_url),
                    "original_path": "<redacted>",
                },
            )

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

    def _build_message(
        self,
        query: str,
        *,
        context_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Message:
        """Construct an ``a2a`` message payload."""

        raw_role = getattr(Role, "USER", None)
        if raw_role is None:
            raw_role = getattr(Role, "user", None)
        if raw_role is None:
            raw_role = Role("user")

        message_id = str(uuid4())
        resolved_context_id = context_id
        if isinstance(resolved_context_id, str) and not resolved_context_id.strip():
            resolved_context_id = None
        if resolved_context_id is None:
            resolved_context_id = str(uuid4())

        logger.debug(
            "Resolved A2A message role",
            extra={
                "agent_url": redact_url_for_logging(self.agent_url),
                "role_value": getattr(raw_role, "value", str(raw_role)),
                "role_repr": repr(raw_role),
                "message_id": message_id,
            },
        )

        parts: List[Part] = [
            TextPart(text=query),
        ]
        resolved_metadata = metadata or None
        return Message(
            message_id=message_id,
            role=raw_role,
            parts=parts,
            context_id=resolved_context_id,
            metadata=resolved_metadata,
        )

    @staticmethod
    def _build_timeout(timeout_seconds: Optional[float]) -> httpx.Timeout:
        if timeout_seconds and timeout_seconds > 0:
            return httpx.Timeout(timeout_seconds)
        return httpx.Timeout(10.0, connect=10.0)

    @staticmethod
    def _extract_text_from_payload(payload: ClientEvent | Message) -> Optional[str]:
        if isinstance(payload, Message):
            collected: list[str] = []
            for part in payload.parts:
                text_part = None
                if isinstance(part, TextPart):
                    text_part = part
                else:
                    root = getattr(part, "root", None)
                    if isinstance(root, TextPart):
                        text_part = root

                if text_part and getattr(text_part, "text", None):
                    collected.append(text_part.text)

            if collected:
                return "\n".join(collected)
        return None


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


def _should_reset_http_error(error: httpx.HTTPError) -> bool:
    if isinstance(error, httpx.TransportError):
        return True
    if isinstance(error, httpx.HTTPStatusError) and error.response is not None:
        return error.response.status_code in {401, 403}
    return False


__all__ = ["A2AClient", "ClientCacheEntry"]
