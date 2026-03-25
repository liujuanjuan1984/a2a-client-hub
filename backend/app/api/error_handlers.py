"""Error normalization helpers and exception handlers."""

from __future__ import annotations

import traceback
from http import HTTPStatus
from typing import Any, Dict, Mapping

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.config import settings

_ALLOWED_DETAIL_KEYS = {
    "message",
    "error_code",
    "source",
    "jsonrpc_code",
    "missing_params",
    "upstream_error",
    "errors",
    "meta",
}
_LEGACY_DETAIL_KEYS = {"code"}


def _ensure_message(value: Any, default: str) -> str:
    if isinstance(value, str) and value.strip():
        return value
    return default


def _normalize_error_code(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def normalize_error_detail(detail: Any, *, default_message: str) -> Dict[str, Any]:
    """Normalize error detail into a structured payload."""
    if isinstance(detail, dict):
        message = detail.get("message")
        if isinstance(message, str):
            normalized: Dict[str, Any] = {"message": message}
            error_code = _normalize_error_code(
                detail.get("error_code")
            ) or _normalize_error_code(detail.get("code"))
            if error_code is not None:
                normalized["error_code"] = error_code
            for key in (
                "source",
                "jsonrpc_code",
                "missing_params",
                "upstream_error",
                "errors",
            ):
                if key in detail:
                    normalized[key] = detail.get(key)
            meta = detail.get("meta") if isinstance(detail.get("meta"), dict) else None
            extras = {
                k: v
                for k, v in detail.items()
                if k not in _ALLOWED_DETAIL_KEYS and k not in _LEGACY_DETAIL_KEYS
            }
            if extras:
                if meta is None:
                    meta = {}
                meta.update(extras)
            if meta:
                normalized["meta"] = meta
            return normalized
        return {"message": default_message, "meta": detail}
    if isinstance(detail, list):
        return {"message": default_message, "errors": detail}
    if detail is None:
        return {"message": default_message}
    return {"message": _ensure_message(str(detail), default_message)}


def _default_message_for_status(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "Request failed"


def build_error_detail(
    *,
    message: str,
    error_code: str | None = None,
    source: str | None = None,
    jsonrpc_code: int | None = None,
    missing_params: list[dict[str, Any]] | None = None,
    upstream_error: dict[str, Any] | None = None,
    errors: list[Any] | None = None,
    meta: dict[str, Any] | None = None,
) -> Dict[str, Any]:
    detail: Dict[str, Any] = {"message": message}
    normalized_error_code = _normalize_error_code(error_code)
    if normalized_error_code is not None:
        detail["error_code"] = normalized_error_code
    if source is not None:
        detail["source"] = source
    if jsonrpc_code is not None:
        detail["jsonrpc_code"] = jsonrpc_code
    if missing_params:
        detail["missing_params"] = missing_params
    if upstream_error:
        detail["upstream_error"] = upstream_error
    if errors:
        detail["errors"] = errors
    if meta:
        detail["meta"] = meta
    return detail


def build_error_response(
    *,
    status_code: int,
    detail: Any,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    normalized = normalize_error_detail(
        detail,
        default_message=_default_message_for_status(status_code),
    )
    return JSONResponse(
        status_code=status_code,
        content={"detail": normalized},
        headers=headers,
    )


async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    return build_error_response(
        status_code=exc.status_code,
        detail=exc.detail,
        headers=exc.headers,
    )


async def validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    return build_error_response(
        status_code=422,
        detail=exc.errors(),
    )


async def unhandled_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    if settings.debug:
        detail = {
            "message": str(exc),
            "meta": {
                "trace": traceback.format_exc(),
                "path": str(request.url.path),
                "method": request.method,
            },
        }
    else:
        detail = {"message": "An unexpected error occurred."}
    return build_error_response(status_code=500, detail=detail)
