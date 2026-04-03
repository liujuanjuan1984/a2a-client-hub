from __future__ import annotations

from typing import Any, Dict

from app.features.personal_agents.runtime import A2ARuntime
from app.integrations.a2a_extensions.service_common import ExtensionCallResult
from app.integrations.a2a_extensions.shared_support import A2AExtensionSupport


def _extract_string(value: Any, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Upstream payload contains invalid '{field}'")
    normalized = value.strip()
    return normalized or None


def _extract_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Upstream payload contains invalid 'tags'")
    tags: list[str] = []
    for item in value:
        tag = _extract_string(item, field="tags.*")
        if tag:
            tags.append(tag)
    return tags


def _extract_metadata(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("Upstream payload contains invalid 'metadata'")
    return dict(value)


def _first_string(payload: Dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        resolved = _extract_string(payload.get(key), field=key)
        if resolved:
            return resolved
    return None


def _normalize_summary_item(
    payload: Dict[str, Any],
    *,
    kind: str,
) -> Dict[str, Any]:
    item_id = _first_string(payload, "id", "slug", "name", "key")
    if item_id is None:
        raise ValueError(f"Upstream payload missing identifier for {kind}")

    return {
        "id": item_id,
        "kind": kind,
        "name": _first_string(payload, "name", "slug", "key"),
        "title": _first_string(payload, "title", "displayName", "display_name"),
        "summary": _first_string(payload, "summary", "shortDescription"),
        "description": _first_string(payload, "description", "details"),
        "tags": _extract_string_list(payload.get("tags")),
        "metadata": _extract_metadata(payload.get("metadata")),
    }


def _extract_list_payload(
    result: Any,
    *,
    kind: str,
    list_key: str,
) -> Dict[str, Any]:
    if isinstance(result, dict):
        if isinstance(result.get("items"), list):
            items = result.get("items")
        elif isinstance(result.get(list_key), list):
            items = result.get(list_key)
        else:
            raise ValueError(f"Upstream payload missing list for {kind}")
        next_cursor = _first_string(result, "nextCursor", "next_cursor", "cursor")
        return {"items": items, "next_cursor": next_cursor}
    if isinstance(result, list):
        return {"items": result, "next_cursor": None}
    raise ValueError(f"Upstream payload missing list for {kind}")


def _normalize_list_result(
    result: Any,
    *,
    kind: str,
    list_key: str,
) -> Dict[str, Any]:
    payload = _extract_list_payload(result, kind=kind, list_key=list_key)
    items = payload["items"]
    assert isinstance(items, list)
    normalized_items = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError(f"Upstream payload contains invalid {kind} item")
        normalized_items.append(_normalize_summary_item(item, kind=kind))
    normalized = {"items": normalized_items}
    if payload["next_cursor"] is not None:
        normalized["nextCursor"] = payload["next_cursor"]
    return normalized


def _normalize_plugin_read_result(result: Any) -> Dict[str, Any]:
    if isinstance(result, dict) and isinstance(result.get("plugin"), dict):
        payload = dict(result["plugin"])
    elif isinstance(result, dict):
        payload = dict(result)
    else:
        raise ValueError("Upstream payload missing plugin object")

    normalized = _normalize_summary_item(payload, kind="plugin")
    normalized["content"] = payload.get("content", payload.get("details"))
    return {"plugin": normalized}


class CodexDiscoveryService:
    def __init__(self, support: A2AExtensionSupport) -> None:
        self._support = support

    async def invoke_method(
        self,
        *,
        runtime: A2ARuntime,
        jsonrpc_url: str,
        method_name: str,
        params: Dict[str, Any],
        meta: Dict[str, Any],
    ) -> ExtensionCallResult:
        resp = await self._support.perform_jsonrpc_call(
            runtime=runtime,
            jsonrpc_url=jsonrpc_url,
            method_name=method_name,
            params=params,
        )

        metric_key = f"codex_discovery:{method_name}"
        if resp.ok:
            self._support.record_extension_metric(
                metric_key, success=True, error_code=None
            )
            return ExtensionCallResult(
                success=True,
                result=(
                    dict(resp.result)
                    if isinstance(resp.result, dict)
                    else (
                        {"items": list(resp.result)}
                        if isinstance(resp.result, list)
                        else {"raw": resp.result}
                    )
                ),
                meta=meta,
            )

        error = resp.error or {}
        error_details = self._support.build_upstream_error_details(
            error=error,
            business_code_map={},
        )
        self._support.record_extension_metric(
            metric_key, success=False, error_code=error_details.error_code
        )
        return ExtensionCallResult(
            success=False,
            error_code=error_details.error_code,
            source=error_details.source,
            jsonrpc_code=error_details.jsonrpc_code,
            missing_params=list(error_details.missing_params or []) or None,
            upstream_error=error_details.upstream_error,
            meta=meta,
        )

    @staticmethod
    def _payload_error(
        *,
        message: str,
        meta: Dict[str, Any],
    ) -> ExtensionCallResult:
        return ExtensionCallResult(
            success=False,
            error_code="upstream_payload_error",
            source="codex_discovery",
            upstream_error={"message": message, "type": "UPSTREAM_PAYLOAD_ERROR"},
            meta=meta,
        )

    async def list_items(
        self,
        *,
        runtime: A2ARuntime,
        jsonrpc_url: str,
        method_name: str,
        kind: str,
        list_key: str,
        meta: Dict[str, Any],
    ) -> ExtensionCallResult:
        result = await self.invoke_method(
            runtime=runtime,
            jsonrpc_url=jsonrpc_url,
            method_name=method_name,
            params={},
            meta=meta,
        )
        if not result.success:
            return result
        try:
            normalized = _normalize_list_result(
                result.result, kind=kind, list_key=list_key
            )
        except ValueError as exc:
            return self._payload_error(message=str(exc), meta=meta)
        return ExtensionCallResult(success=True, result=normalized, meta=meta)

    async def read_plugin(
        self,
        *,
        runtime: A2ARuntime,
        jsonrpc_url: str,
        method_name: str,
        plugin_id: str,
        meta: Dict[str, Any],
    ) -> ExtensionCallResult:
        result = await self.invoke_method(
            runtime=runtime,
            jsonrpc_url=jsonrpc_url,
            method_name=method_name,
            params={"id": plugin_id},
            meta=meta,
        )
        if not result.success:
            return result
        try:
            normalized = _normalize_plugin_read_result(result.result)
        except ValueError as exc:
            return self._payload_error(message=str(exc), meta=meta)
        return ExtensionCallResult(success=True, result=normalized, meta=meta)


__all__ = ["CodexDiscoveryService"]
