from __future__ import annotations

from typing import Any, Dict, Optional

from app.features.agents.personal.runtime import A2ARuntime
from app.features.working_directory import adapt_working_directory_metadata_for_upstream
from app.integrations.a2a_extensions.service_common import ExtensionCallResult
from app.integrations.a2a_extensions.shared_support import A2AExtensionSupport
from app.integrations.a2a_extensions.types import ResolvedProviderDiscoveryExtension


def _extract_provider_private_metadata(
    session_metadata: Optional[Dict[str, Any]],
    provider_private_namespace: str,
) -> Optional[Dict[str, Any]]:
    if not session_metadata:
        return None
    section = session_metadata.get(provider_private_namespace)
    if not isinstance(section, dict):
        return None
    return {provider_private_namespace: dict(section)}


class ProviderDiscoveryService:
    def __init__(self, support: A2AExtensionSupport) -> None:
        self._support = support

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
            requested_extensions=[ext.uri],
        )

        meta: Dict[str, Any] = {
            "extension_uri": ext.uri,
            "jsonrpc_fallback_used": ext.jsonrpc.fallback_used,
            "provider": ext.provider_key,
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
        error_details = self._support.build_upstream_error_details(
            error=error,
            business_code_map=ext.business_code_map,
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

    async def list_model_providers(
        self,
        *,
        runtime: A2ARuntime,
        ext: ResolvedProviderDiscoveryExtension,
        jsonrpc_url: str,
        session_metadata: Optional[Dict[str, Any]] = None,
        working_directory: str | None = None,
    ) -> ExtensionCallResult:
        params: Dict[str, Any] = {}
        adapted_session_metadata = adapt_working_directory_metadata_for_upstream(
            session_metadata,
            working_directory,
            metadata_namespace=ext.provider_private_namespace,
        )
        normalized_metadata = self._support.normalize_extension_metadata(
            _extract_provider_private_metadata(
                adapted_session_metadata,
                ext.provider_private_namespace,
            )
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
        ext: ResolvedProviderDiscoveryExtension,
        jsonrpc_url: str,
        provider_id: str | None = None,
        session_metadata: Optional[Dict[str, Any]] = None,
        working_directory: str | None = None,
    ) -> ExtensionCallResult:
        resolved_provider_id = (provider_id or "").strip()
        params: Dict[str, Any] = {}
        if resolved_provider_id:
            params["provider_id"] = resolved_provider_id
        adapted_session_metadata = adapt_working_directory_metadata_for_upstream(
            session_metadata,
            working_directory,
            metadata_namespace=ext.provider_private_namespace,
        )
        normalized_metadata = self._support.normalize_extension_metadata(
            _extract_provider_private_metadata(
                adapted_session_metadata,
                ext.provider_private_namespace,
            )
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
