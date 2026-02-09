"""Lightweight JSON-RPC 2.0 client.

This client intentionally avoids logging request/response bodies because some
extension methods may carry sensitive user data (e.g., message history).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Optional
from uuid import uuid4

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class JsonRpcResponse:
    ok: bool
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None


class JsonRpcClient:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    async def call(
        self,
        *,
        url: str,
        method: str,
        params: Optional[Dict[str, Any]],
        headers: Dict[str, str],
        timeout_seconds: float,
    ) -> JsonRpcResponse:
        request_id = uuid4().hex
        payload: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params is not None:
            payload["params"] = params

        start = time.monotonic()
        try:
            resp = await self._http.post(
                url,
                json=payload,
                headers=headers,
                timeout=timeout_seconds,
            )
        except httpx.TransportError as exc:
            elapsed = time.monotonic() - start
            logger.warning(
                "JSON-RPC transport error",
                extra={
                    "jsonrpc_url": url,
                    "method": method,
                    "elapsed_seconds": round(elapsed, 3),
                    "error_type": type(exc).__name__,
                },
            )
            raise

        elapsed = time.monotonic() - start
        logger.info(
            "JSON-RPC call finished",
            extra={
                "jsonrpc_url": url,
                "method": method,
                "status_code": resp.status_code,
                "elapsed_seconds": round(elapsed, 3),
            },
        )

        if resp.status_code < 200 or resp.status_code >= 300:
            raise httpx.HTTPStatusError(
                f"Unexpected JSON-RPC HTTP status: {resp.status_code}",
                request=resp.request,
                response=resp,
            )

        try:
            data = resp.json()
        except ValueError as exc:  # noqa: PERF203 - explicit JSON parse path
            raise ValueError("Invalid JSON-RPC response (not JSON)") from exc

        if not isinstance(data, dict):
            raise ValueError("Invalid JSON-RPC response (not an object)")

        if data.get("jsonrpc") != "2.0":
            raise ValueError("Invalid JSON-RPC response (jsonrpc must be '2.0')")
        if str(data.get("id", "")) != request_id:
            raise ValueError("Invalid JSON-RPC response (id mismatch)")

        # JSON-RPC 2.0 response must contain either "result" or "error".
        if "error" in data:
            err = data.get("error")
            if isinstance(err, dict):
                return JsonRpcResponse(ok=False, error=dict(err))
            return JsonRpcResponse(ok=False, error={"message": "Invalid error payload"})
        if "result" in data:
            result = data.get("result")
            if isinstance(result, dict):
                return JsonRpcResponse(ok=True, result=dict(result))
            # Extension contract expects a structured envelope; still preserve raw.
            return JsonRpcResponse(ok=True, result={"raw": result})

        raise ValueError("Invalid JSON-RPC response (missing result/error)")


__all__ = ["JsonRpcClient", "JsonRpcResponse"]
