"""Shared helpers for Hub-owned JSON-RPC adapters."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from a2a.client import ClientCallInterceptor

from app.integrations.a2a_client.errors import A2APeerProtocolError

JSONRPC_METHOD_NOT_FOUND_CODE = -32601


def build_jsonrpc_payload(*, method: str, params: dict[str, Any]) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": str(uuid4()),
        "method": method,
        "params": params,
    }


async def apply_jsonrpc_interceptors(
    *,
    interceptors: list[ClientCallInterceptor],
    method_name: str,
    request_payload: dict[str, Any],
    http_kwargs: dict[str, Any] | None,
    agent_card: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    final_payload = request_payload
    final_http_kwargs = dict(http_kwargs or {})
    for interceptor in interceptors:
        final_payload, final_http_kwargs = await interceptor.intercept(
            method_name,
            final_payload,
            final_http_kwargs,
            agent_card,
            None,
        )
    return final_payload, final_http_kwargs


def normalize_jsonrpc_error_code(*, code: Any, message: str) -> str:
    if code == JSONRPC_METHOD_NOT_FOUND_CODE:
        return "method_not_found"
    candidate = str(message).strip().replace("-", "_").replace(" ", "_").lower()
    return candidate or "peer_protocol_error"


def build_protocol_error_from_jsonrpc_error(
    error: dict[str, Any],
    *,
    fallback_message: str,
    http_status: int | None,
) -> A2APeerProtocolError:
    code = error.get("code")
    message = error.get("message") or fallback_message
    return A2APeerProtocolError(
        message=str(message),
        error_code=normalize_jsonrpc_error_code(code=code, message=str(message)),
        rpc_code=code if isinstance(code, int) else None,
        data=error.get("data"),
        http_status=http_status,
    )


def parse_jsonrpc_error_payload(
    payload: Any,
    *,
    fallback_message: str,
    http_status: int | None,
) -> A2APeerProtocolError | None:
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if not isinstance(error, dict):
        return None
    return build_protocol_error_from_jsonrpc_error(
        error,
        fallback_message=fallback_message,
        http_status=http_status,
    )


def parse_jsonrpc_error_bytes(
    raw_body: bytes,
    *,
    fallback_message: str,
    http_status: int | None,
) -> A2APeerProtocolError | None:
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return parse_jsonrpc_error_payload(
        payload,
        fallback_message=fallback_message,
        http_status=http_status,
    )
