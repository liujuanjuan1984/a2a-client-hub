from __future__ import annotations

from typing import Any, Dict

from app.features.agents.personal.runtime import A2ARuntime
from app.integrations.a2a_extensions.service_common import ExtensionCallResult
from app.integrations.a2a_extensions.shared_support import A2AExtensionSupport


def _require_dict(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"Upstream payload contains invalid '{field}'")
    return dict(value)


def _require_list(value: Any, *, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"Upstream payload contains invalid '{field}'")
    return list(value)


def _extract_string(value: Any, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Upstream payload contains invalid '{field}'")
    normalized = value.strip()
    return normalized or None


def _require_string(value: Any, *, field: str) -> str:
    normalized = _extract_string(value, field=field)
    if normalized is None:
        raise ValueError(f"Upstream payload missing '{field}'")
    return normalized


def _extract_bool(value: Any, *, field: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"Upstream payload contains invalid '{field}'")
    return value


def _extract_dict(value: Any, *, field: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"Upstream payload contains invalid '{field}'")
    return dict(value)


def _extract_dict_list(value: Any, *, field: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    items = _require_list(value, field=field)
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"Upstream payload contains invalid '{field}[{index}]'")
        normalized.append(dict(item))
    return normalized


def _extract_string_list(value: Any, *, field: str) -> list[str]:
    if value is None:
        return []
    items = _require_list(value, field=field)
    normalized: list[str] = []
    for index, item in enumerate(items):
        resolved = _extract_string(item, field=f"{field}[{index}]")
        if resolved is not None:
            normalized.append(resolved)
    return normalized


def _normalize_provider_private_payload(
    payload: dict[str, Any], *, field: str
) -> dict[str, Any]:
    provider_private = _extract_dict(
        payload.get("providerPrivate", payload.get("codex")),
        field=field,
    )
    return provider_private or {}


def _normalize_skill_item(payload: Any) -> dict[str, Any]:
    item = _require_dict(payload, field="items[].skills[]")
    return {
        "name": _require_string(item.get("name"), field="items[].skills[].name"),
        "path": _require_string(item.get("path"), field="items[].skills[].path"),
        "description": _require_string(
            item.get("description"), field="items[].skills[].description"
        ),
        "enabled": bool(
            _extract_bool(item.get("enabled"), field="items[].skills[].enabled")
        ),
        "scope": _require_string(item.get("scope"), field="items[].skills[].scope"),
        "interface": _extract_dict(
            item.get("interface"), field="items[].skills[].interface"
        ),
        "providerPrivate": _normalize_provider_private_payload(
            item, field="items[].skills[].codex"
        ),
    }


def _normalize_skill_scope(payload: Any) -> dict[str, Any]:
    scope = _require_dict(payload, field="items[]")
    skills = _require_list(scope.get("skills"), field="items[].skills")
    return {
        "cwd": _require_string(scope.get("cwd"), field="items[].cwd"),
        "skills": [_normalize_skill_item(item) for item in skills],
        "errors": _extract_dict_list(scope.get("errors"), field="items[].errors"),
        "providerPrivate": _normalize_provider_private_payload(
            scope,
            field="items[].codex",
        ),
    }


def _normalize_app_item(payload: Any) -> dict[str, Any]:
    item = _require_dict(payload, field="items[]")
    app_id = _require_string(item.get("id"), field="items[].id")
    mention_path = _extract_string(
        item.get("mention_path"), field="items[].mention_path"
    )
    return {
        "id": app_id,
        "name": _require_string(item.get("name"), field="items[].name"),
        "description": _extract_string(
            item.get("description"), field="items[].description"
        ),
        "isAccessible": bool(
            _extract_bool(item.get("is_accessible"), field="items[].is_accessible")
            if "is_accessible" in item
            else _extract_bool(item.get("isAccessible"), field="items[].isAccessible")
        ),
        "isEnabled": bool(
            _extract_bool(item.get("is_enabled"), field="items[].is_enabled")
            if "is_enabled" in item
            else _extract_bool(item.get("isEnabled"), field="items[].isEnabled")
        ),
        "installUrl": (
            _extract_string(item.get("install_url"), field="items[].install_url")
            if "install_url" in item
            else _extract_string(item.get("installUrl"), field="items[].installUrl")
        ),
        "mentionPath": mention_path or f"app://{app_id}",
        "branding": _extract_dict(item.get("branding"), field="items[].branding"),
        "labels": _extract_dict_list(item.get("labels"), field="items[].labels"),
        "providerPrivate": _normalize_provider_private_payload(
            item,
            field="items[].codex",
        ),
    }


def _normalize_plugin_summary(payload: Any, *, marketplace_name: str) -> dict[str, Any]:
    item = _require_dict(payload, field="items[].plugins[]")
    name = _require_string(item.get("name"), field="items[].plugins[].name")
    mention_path = _extract_string(
        item.get("mention_path"),
        field="items[].plugins[].mention_path",
    )
    return {
        "name": name,
        "description": _extract_string(
            item.get("description"), field="items[].plugins[].description"
        ),
        "enabled": _extract_bool(
            item.get("enabled"), field="items[].plugins[].enabled"
        ),
        "interface": _extract_dict(
            item.get("interface"), field="items[].plugins[].interface"
        ),
        "mentionPath": mention_path or f"plugin://{name}@{marketplace_name}",
        "providerPrivate": _normalize_provider_private_payload(
            item, field="items[].plugins[].codex"
        ),
    }


def _normalize_plugin_marketplace(payload: Any) -> dict[str, Any]:
    item = _require_dict(payload, field="items[]")
    marketplace_name = _require_string(
        item.get("marketplace_name"), field="items[].marketplace_name"
    )
    marketplace_path = _require_string(
        item.get("marketplace_path"), field="items[].marketplace_path"
    )
    plugins = _require_list(item.get("plugins"), field="items[].plugins")
    return {
        "marketplaceName": marketplace_name,
        "marketplacePath": marketplace_path,
        "interface": _extract_dict(item.get("interface"), field="items[].interface"),
        "plugins": [
            _normalize_plugin_summary(plugin, marketplace_name=marketplace_name)
            for plugin in plugins
        ],
        "providerPrivate": _normalize_provider_private_payload(
            item,
            field="items[].codex",
        ),
    }


def _normalize_plugin_detail(payload: Any) -> dict[str, Any]:
    item = _require_dict(payload, field="item")
    name = _require_string(item.get("name"), field="item.name")
    marketplace_name = _require_string(
        item.get("marketplace_name"), field="item.marketplace_name"
    )
    marketplace_path = _require_string(
        item.get("marketplace_path"), field="item.marketplace_path"
    )
    mention_path = _extract_string(item.get("mention_path"), field="item.mention_path")
    return {
        "name": name,
        "marketplaceName": marketplace_name,
        "marketplacePath": marketplace_path,
        "mentionPath": mention_path or f"plugin://{name}@{marketplace_name}",
        "summary": _extract_string_list(item.get("summary"), field="item.summary"),
        "skills": _extract_dict_list(item.get("skills"), field="item.skills"),
        "apps": _extract_dict_list(item.get("apps"), field="item.apps"),
        "mcpServers": _extract_string_list(
            (
                item.get("mcp_servers")
                if "mcp_servers" in item
                else item.get("mcpServers")
            ),
            field="item.mcpServers",
        ),
        "interface": _extract_dict(item.get("interface"), field="item.interface"),
        "providerPrivate": _normalize_provider_private_payload(
            item,
            field="item.codex",
        ),
    }


class UpstreamDiscoveryService:
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

        metric_key = f"upstream_discovery:{method_name}"
        if resp.ok:
            self._support.record_extension_metric(
                metric_key, success=True, error_code=None
            )
            return ExtensionCallResult(success=True, result=resp.result, meta=meta)

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
    def _payload_error(*, message: str, meta: Dict[str, Any]) -> ExtensionCallResult:
        return ExtensionCallResult(
            success=False,
            error_code="upstream_payload_error",
            source="upstream_discovery",
            upstream_error={"message": message, "type": "UPSTREAM_PAYLOAD_ERROR"},
            meta=meta,
        )

    async def list_skills(
        self,
        *,
        runtime: A2ARuntime,
        jsonrpc_url: str,
        method_name: str,
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
            payload = _require_dict(result.result, field="result")
            items = _require_list(payload.get("items"), field="result.items")
            normalized = {"items": [_normalize_skill_scope(item) for item in items]}
        except ValueError as exc:
            return self._payload_error(message=str(exc), meta=meta)
        return ExtensionCallResult(success=True, result=normalized, meta=meta)

    async def list_apps(
        self,
        *,
        runtime: A2ARuntime,
        jsonrpc_url: str,
        method_name: str,
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
            payload = _require_dict(result.result, field="result")
            items = _require_list(payload.get("items"), field="result.items")
            normalized = {
                "items": [_normalize_app_item(item) for item in items],
                "nextCursor": _extract_string(
                    (
                        payload.get("next_cursor")
                        if "next_cursor" in payload
                        else payload.get("nextCursor")
                    ),
                    field="result.nextCursor",
                ),
            }
        except ValueError as exc:
            return self._payload_error(message=str(exc), meta=meta)
        return ExtensionCallResult(success=True, result=normalized, meta=meta)

    async def list_plugins(
        self,
        *,
        runtime: A2ARuntime,
        jsonrpc_url: str,
        method_name: str,
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
            payload = _require_dict(result.result, field="result")
            items = _require_list(payload.get("items"), field="result.items")
            normalized = {
                "items": [_normalize_plugin_marketplace(item) for item in items],
                "featuredPluginIds": _extract_string_list(
                    (
                        payload.get("featured_plugin_ids")
                        if "featured_plugin_ids" in payload
                        else payload.get("featuredPluginIds")
                    ),
                    field="result.featuredPluginIds",
                ),
                "marketplaceLoadErrors": _extract_dict_list(
                    (
                        payload.get("marketplace_load_errors")
                        if "marketplace_load_errors" in payload
                        else payload.get("marketplaceLoadErrors")
                    ),
                    field="result.marketplaceLoadErrors",
                ),
                "remoteSyncError": _extract_string(
                    (
                        payload.get("remote_sync_error")
                        if "remote_sync_error" in payload
                        else payload.get("remoteSyncError")
                    ),
                    field="result.remoteSyncError",
                ),
            }
        except ValueError as exc:
            return self._payload_error(message=str(exc), meta=meta)
        return ExtensionCallResult(success=True, result=normalized, meta=meta)

    async def read_plugin(
        self,
        *,
        runtime: A2ARuntime,
        jsonrpc_url: str,
        method_name: str,
        marketplace_path: str,
        plugin_name: str,
        meta: Dict[str, Any],
    ) -> ExtensionCallResult:
        result = await self.invoke_method(
            runtime=runtime,
            jsonrpc_url=jsonrpc_url,
            method_name=method_name,
            params={
                "marketplacePath": marketplace_path,
                "pluginName": plugin_name,
            },
            meta=meta,
        )
        if not result.success:
            return result
        try:
            payload = _require_dict(result.result, field="result")
            item = payload.get("item")
            if item is None and isinstance(payload.get("plugin"), dict):
                plugin_payload = dict(payload["plugin"])
                item = {
                    "name": plugin_payload.get("name"),
                    "marketplace_name": plugin_payload.get("marketplaceName"),
                    "marketplace_path": plugin_payload.get("marketplacePath"),
                    "mention_path": plugin_payload.get("mentionPath"),
                    "summary": plugin_payload.get("summary"),
                    "skills": plugin_payload.get("skills"),
                    "apps": plugin_payload.get("apps"),
                    "mcp_servers": plugin_payload.get("mcpServers"),
                    "interface": plugin_payload.get("interface"),
                    "providerPrivate": plugin_payload.get(
                        "providerPrivate",
                        plugin_payload.get("codex"),
                    ),
                }
            normalized = {"item": _normalize_plugin_detail(item)}
        except ValueError as exc:
            return self._payload_error(message=str(exc), meta=meta)
        return ExtensionCallResult(success=True, result=normalized, meta=meta)
