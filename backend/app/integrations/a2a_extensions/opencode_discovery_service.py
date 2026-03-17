from __future__ import annotations

from typing import Any, Dict, Optional

from app.integrations.a2a_extensions.opencode_provider_discovery import (
    resolve_opencode_provider_discovery,
)
from app.integrations.a2a_extensions.service_common import ExtensionCallResult
from app.integrations.a2a_extensions.shared_support import A2AExtensionSupport
from app.integrations.a2a_extensions.types import ResolvedProviderDiscoveryExtension
from app.services.a2a_runtime import A2ARuntime


def _extract_provider_private_metadata(
    session_metadata: Optional[Dict[str, Any]],
    metadata_namespace: str,
) -> Optional[Dict[str, Any]]:
    if not session_metadata:
        return None
    section = session_metadata.get(metadata_namespace)
    if not isinstance(section, dict):
        return None
    return {metadata_namespace: dict(section)}


class OpencodeDiscoveryService:
    def __init__(self, support: A2AExtensionSupport) -> None:
        self._support = support

    async def resolve_extension(
        self, runtime: A2ARuntime
    ) -> tuple[ResolvedProviderDiscoveryExtension, str]:
        card = await self._support.fetch_card(runtime)
        ext = resolve_opencode_provider_discovery(card)
        jsonrpc_url = self._support.ensure_outbound_allowed(
            ext.jsonrpc.url, purpose="JSON-RPC interface URL"
        )
        return ext, jsonrpc_url

    async def invoke_method(
        self,
        *,
        runtime: A2ARuntime,
        ext: ResolvedProviderDiscoveryExtension,
        jsonrpc_url: str,
        method_key: str,
        params: Dict[str, Any],
        meta_extra: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        method_name = ext.methods.get(method_key)
        if not method_name:
            return ExtensionCallResult(
                success=False,
                error_code="method_not_supported",
                upstream_error={
                    "message": f"Method {method_key} is not supported by upstream"
                },
                meta={"extension_uri": ext.uri},
            )

        resp = await self._support.perform_jsonrpc_call(
            runtime=runtime,
            jsonrpc_url=jsonrpc_url,
            method_name=method_name,
            params=params,
        )

        meta: Dict[str, Any] = {
            "extension_uri": ext.uri,
            "jsonrpc_fallback_used": ext.jsonrpc.fallback_used,
            "provider": ext.provider,
        }
        if meta_extra:
            meta.update(meta_extra)

        metric_key = f"{ext.uri}:{method_name}"
        if resp.ok:
            resolved_result = (
                dict(resp.result)
                if isinstance(resp.result, dict)
                else {"raw": resp.result}
            )
            self._support.record_extension_metric(
                metric_key, success=True, error_code=None
            )
            return ExtensionCallResult(
                success=True,
                result=resolved_result,
                meta=meta,
            )

        error = resp.error or {}
        error_code = self._support.map_business_error_code(error, ext)
        self._support.record_extension_metric(
            metric_key, success=False, error_code=error_code
        )
        return ExtensionCallResult(
            success=False,
            error_code=error_code,
            upstream_error=error,
            meta=meta,
        )

    async def list_model_providers(
        self,
        *,
        runtime: A2ARuntime,
        session_metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        ext, jsonrpc_url = await self.resolve_extension(runtime)
        params: Dict[str, Any] = {}
        normalized_metadata = self._support.normalize_extension_metadata(
            _extract_provider_private_metadata(session_metadata, ext.metadata_namespace)
        )
        if normalized_metadata is not None:
            params["metadata"] = normalized_metadata
        return await self.invoke_method(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            method_key="list_providers",
            params=params,
        )

    async def list_models(
        self,
        *,
        runtime: A2ARuntime,
        provider_id: str | None = None,
        session_metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        resolved_provider_id = (provider_id or "").strip()
        ext, jsonrpc_url = await self.resolve_extension(runtime)
        params: Dict[str, Any] = {}
        if resolved_provider_id:
            params["provider_id"] = resolved_provider_id
        normalized_metadata = self._support.normalize_extension_metadata(
            _extract_provider_private_metadata(session_metadata, ext.metadata_namespace)
        )
        if normalized_metadata is not None:
            params["metadata"] = normalized_metadata
        return await self.invoke_method(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            method_key="list_models",
            params=params,
            meta_extra=(
                {"provider_id": resolved_provider_id} if resolved_provider_id else None
            ),
        )
