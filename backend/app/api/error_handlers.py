"""Error normalization helpers and exception handlers."""

from __future__ import annotations

import traceback
from http import HTTPStatus
from typing import Any, Dict

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.config import settings

_ALLOWED_DETAIL_KEYS = {"message", "code", "errors", "meta"}


def _ensure_message(value: Any, default: str) -> str:
    if isinstance(value, str) and value.strip():
        return value
    return default


def normalize_error_detail(detail: Any, *, default_message: str) -> Dict[str, Any]:
    """Normalize error detail into a structured payload."""
    if isinstance(detail, dict):
        message = detail.get("message")
        if isinstance(message, str):
            if set(detail.keys()).issubset(_ALLOWED_DETAIL_KEYS):
                return detail
            normalized: Dict[str, Any] = {"message": message}
            if "code" in detail:
                normalized["code"] = detail.get("code")
            if "errors" in detail:
                normalized["errors"] = detail.get("errors")
            meta = detail.get("meta") if isinstance(detail.get("meta"), dict) else None
            extras = {k: v for k, v in detail.items() if k not in _ALLOWED_DETAIL_KEYS}
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


async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    detail = normalize_error_detail(
        exc.detail,
        default_message=_default_message_for_status(exc.status_code),
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": detail},
        headers=exc.headers,
    )


async def validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    detail = normalize_error_detail(exc.errors(), default_message="Validation error")
    return JSONResponse(
        status_code=422,
        content={"detail": detail},
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
    return JSONResponse(status_code=500, content={"detail": detail})
