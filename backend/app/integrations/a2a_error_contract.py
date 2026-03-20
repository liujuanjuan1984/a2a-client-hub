"""Shared helpers for canonicalizing upstream A2A error details."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.integrations.a2a_client.errors import A2APeerProtocolError

JSONRPC_STANDARD_ERROR_CODE_MAP: dict[int, str] = {
    -32600: "invalid_request",
    -32601: "method_not_supported",
    -32602: "invalid_params",
}

ERROR_DATA_TYPE_TO_ERROR_CODE: dict[str, str] = {
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

_MISSING_PARAM_MESSAGE_PATTERNS = (
    re.compile(
        r"(?P<names>[A-Za-z][A-Za-z0-9_]*(?:\s*[/,]\s*[A-Za-z][A-Za-z0-9_]*)*)\s+required\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bmissing\s+(?P<names>[A-Za-z][A-Za-z0-9_]*(?:\s*[/,]\s*[A-Za-z][A-Za-z0-9_]*)*)\b",
        re.IGNORECASE,
    ),
)

_SAFE_UPSTREAM_DATA_KEYS = frozenset(
    {
        "type",
        "field",
        "fields",
        "param",
        "params",
        "name",
        "names",
        "missing",
        "missing_fields",
        "missing_params",
        "missingParams",
        "required",
        "required_fields",
        "reason",
        "hint",
        "details",
    }
)


@dataclass(frozen=True, slots=True)
class A2AUpstreamErrorDetails:
    error_code: str
    source: str | None = None
    jsonrpc_code: int | None = None
    missing_params: tuple[dict[str, Any], ...] | None = None
    upstream_error: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"error_code": self.error_code}
        if self.source:
            payload["source"] = self.source
        if self.jsonrpc_code is not None:
            payload["jsonrpc_code"] = self.jsonrpc_code
        if self.missing_params:
            payload["missing_params"] = [dict(item) for item in self.missing_params]
        if self.upstream_error:
            payload["upstream_error"] = dict(self.upstream_error)
        return payload


def coerce_jsonrpc_error_code(value: Any) -> int | None:
    code = value.get("code") if isinstance(value, Mapping) else value
    if isinstance(code, bool):
        return None
    if isinstance(code, int):
        return code
    if isinstance(code, str):
        normalized = code.strip()
        if normalized.lstrip("-").isdigit():
            return int(normalized)
    return None


def normalize_error_token(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized: list[str] = []
    pending_sep = False
    for ch in value.strip().lower():
        if ch.isalnum():
            if pending_sep and normalized:
                normalized.append("_")
            normalized.append(ch)
            pending_sep = False
            continue
        pending_sep = True
    token = "".join(normalized).strip("_")
    return token or None


def normalize_error_data_type(error: Mapping[str, Any] | Any) -> str | None:
    data = (
        error.get("data") if isinstance(error, Mapping) and "data" in error else error
    )
    if not isinstance(data, Mapping):
        return None
    return normalize_error_token(data.get("type"))


def map_upstream_error_code(
    *,
    jsonrpc_code: Any = None,
    data: Any = None,
    message: str | None = None,
    declared_error_code: str | None = None,
    business_code_map: Mapping[int, str] | None = None,
    default_error_code: str = "upstream_error",
) -> str:
    normalized_data_type = normalize_error_data_type(data)
    if normalized_data_type:
        mapped_by_type = ERROR_DATA_TYPE_TO_ERROR_CODE.get(normalized_data_type)
        if mapped_by_type:
            return mapped_by_type
        if normalized_data_type.startswith("invalid_"):
            return "invalid_params"

    numeric_code = coerce_jsonrpc_error_code(jsonrpc_code)
    if numeric_code is not None:
        if business_code_map:
            mapped = business_code_map.get(numeric_code)
            if mapped:
                return mapped
        mapped_standard = JSONRPC_STANDARD_ERROR_CODE_MAP.get(numeric_code)
        if mapped_standard:
            return mapped_standard

    normalized_declared = normalize_error_token(declared_error_code)
    if normalized_declared and normalized_declared not in {
        "peer_protocol_error",
        "upstream_error",
        "upstream_stream_error",
    }:
        return normalized_declared

    normalized_message = normalize_error_token(message)
    if normalized_message:
        return normalized_message

    return default_error_code


def build_protocol_error_from_jsonrpc_error(
    error: Mapping[str, Any],
    *,
    fallback_message: str,
    http_status: int | None,
    business_code_map: Mapping[int, str] | None = None,
) -> A2APeerProtocolError:
    code = coerce_jsonrpc_error_code(error)
    data = error.get("data")
    message = str(error.get("message") or fallback_message)
    return A2APeerProtocolError(
        message=message,
        error_code=map_upstream_error_code(
            jsonrpc_code=code,
            data=data,
            message=message,
            business_code_map=business_code_map,
            default_error_code="peer_protocol_error",
        ),
        rpc_code=code,
        data=data,
        http_status=http_status,
    )


def _coerce_missing_params(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        parts = [
            segment.strip()
            for segment in re.split(r"[/,]", value)
            if isinstance(segment, str) and segment.strip()
        ]
        return [{"name": name, "required": True} for name in parts]

    if isinstance(value, Mapping):
        name = value.get("name")
        if not isinstance(name, str) or not name.strip():
            return []
        required = value.get("required")
        return [
            {
                "name": name.strip(),
                "required": required if isinstance(required, bool) else True,
            }
        ]

    if not isinstance(value, list):
        return []

    items: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for item in value:
        for resolved in _coerce_missing_params(item):
            name = resolved.get("name")
            if not isinstance(name, str) or name in seen_names:
                continue
            seen_names.add(name)
            items.append(resolved)
    return items


def extract_missing_params(*, data: Any, message: str | None) -> list[dict[str, Any]]:
    if isinstance(data, Mapping):
        for key in (
            "missing_params",
            "missingParams",
            "missing_fields",
            "required_fields",
            "fields",
            "params",
            "missing",
            "field",
            "param",
            "name",
        ):
            resolved = _coerce_missing_params(data.get(key))
            if resolved:
                return resolved

    if not message:
        return []

    for pattern in _MISSING_PARAM_MESSAGE_PATTERNS:
        match = pattern.search(message)
        if match:
            return _coerce_missing_params(match.group("names"))
    return []


def sanitize_upstream_error_data(value: Any, *, depth: int = 0) -> Any:
    if depth >= 3:
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        sanitized_items = [
            sanitize_upstream_error_data(item, depth=depth + 1) for item in value
        ]
        return [item for item in sanitized_items if item is not None] or None
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if key not in _SAFE_UPSTREAM_DATA_KEYS:
                continue
            resolved = sanitize_upstream_error_data(item, depth=depth + 1)
            if resolved is not None:
                sanitized[str(key)] = resolved
        return sanitized or None
    return None


def build_upstream_error_details(
    *,
    message: str | None,
    jsonrpc_code: Any = None,
    data: Any = None,
    declared_error_code: str | None = None,
    business_code_map: Mapping[int, str] | None = None,
    default_error_code: str = "upstream_error",
    source: str | None = "upstream_a2a",
) -> A2AUpstreamErrorDetails:
    normalized_message = message.strip() if isinstance(message, str) else ""
    resolved_error_code = map_upstream_error_code(
        jsonrpc_code=jsonrpc_code,
        data=data,
        message=normalized_message or None,
        declared_error_code=declared_error_code,
        business_code_map=business_code_map,
        default_error_code=default_error_code,
    )
    upstream_error: dict[str, Any] = {}
    if normalized_message:
        upstream_error["message"] = normalized_message
    sanitized_data = sanitize_upstream_error_data(data)
    if sanitized_data is not None:
        upstream_error["data"] = sanitized_data

    missing_params = extract_missing_params(
        data=data,
        message=normalized_message or None,
    )
    return A2AUpstreamErrorDetails(
        error_code=resolved_error_code,
        source=source,
        jsonrpc_code=coerce_jsonrpc_error_code(jsonrpc_code),
        missing_params=tuple(missing_params) or None,
        upstream_error=upstream_error or None,
    )


def build_upstream_error_details_from_protocol_error(
    exc: A2APeerProtocolError,
    *,
    default_error_code: str = "upstream_error",
    source: str | None = "upstream_a2a",
) -> A2AUpstreamErrorDetails:
    return build_upstream_error_details(
        message=str(exc),
        jsonrpc_code=exc.code,
        data=exc.data,
        declared_error_code=getattr(exc, "error_code", None),
        default_error_code=default_error_code,
        source=source,
    )


__all__ = [
    "A2AUpstreamErrorDetails",
    "ERROR_DATA_TYPE_TO_ERROR_CODE",
    "JSONRPC_STANDARD_ERROR_CODE_MAP",
    "build_protocol_error_from_jsonrpc_error",
    "build_upstream_error_details",
    "build_upstream_error_details_from_protocol_error",
    "coerce_jsonrpc_error_code",
    "extract_missing_params",
    "map_upstream_error_code",
    "normalize_error_data_type",
    "normalize_error_token",
    "sanitize_upstream_error_data",
]
