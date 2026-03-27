from __future__ import annotations

from typing import Any, Dict

from app.features.personal_agents.runtime import A2ARuntime
from app.integrations.a2a_extensions.errors import A2AExtensionContractError
from app.integrations.a2a_extensions.service_common import ExtensionCallResult
from app.integrations.a2a_extensions.shared_support import A2AExtensionSupport
from app.integrations.a2a_extensions.types import ResolvedInterruptRecoveryExtension


class InterruptRecoveryService:
    def __init__(self, support: A2AExtensionSupport) -> None:
        self._support = support

    @staticmethod
    def prepare_recovery_query(
        *,
        session_id: str | None = None,
    ) -> str | None:
        resolved_session_id = (session_id or "").strip()
        return resolved_session_id or None

    @staticmethod
    def _normalize_item(item: Any) -> dict[str, Any]:
        if not isinstance(item, dict):
            raise A2AExtensionContractError(
                "Interrupt recovery result item must be an object"
            )

        request_id = item.get("request_id")
        if not isinstance(request_id, str) or not request_id.strip():
            raise A2AExtensionContractError(
                "Interrupt recovery item missing request_id"
            )

        session_id = item.get("session_id")
        if not isinstance(session_id, str) or not session_id.strip():
            raise A2AExtensionContractError(
                "Interrupt recovery item missing session_id"
            )

        interrupt_type = item.get("interrupt_type")
        if interrupt_type not in {
            "permission",
            "question",
            "permissions",
            "elicitation",
        }:
            raise A2AExtensionContractError(
                "Interrupt recovery item has invalid interrupt_type"
            )

        details = item.get("details")
        if details is not None and not isinstance(details, dict):
            raise A2AExtensionContractError(
                "Interrupt recovery item details must be an object when provided"
            )

        expires_at = item.get("expires_at")
        if expires_at is not None and not isinstance(expires_at, (int, float)):
            raise A2AExtensionContractError(
                "Interrupt recovery item expires_at must be numeric when provided"
            )

        normalized: dict[str, Any] = {
            "request_id": request_id.strip(),
            "session_id": session_id.strip(),
            "type": interrupt_type,
            "details": dict(details) if isinstance(details, dict) else {},
        }

        task_id = item.get("task_id")
        if isinstance(task_id, str) and task_id.strip():
            normalized["task_id"] = task_id.strip()

        context_id = item.get("context_id")
        if isinstance(context_id, str) and context_id.strip():
            normalized["context_id"] = context_id.strip()

        if isinstance(expires_at, (int, float)):
            normalized["expires_at"] = float(expires_at)

        return normalized

    def _normalize_result_items(self, result: Any) -> list[dict[str, Any]]:
        if not isinstance(result, dict):
            raise A2AExtensionContractError(
                "Interrupt recovery result envelope must be an object"
            )

        items = result.get("items")
        if not isinstance(items, list):
            raise A2AExtensionContractError(
                "Interrupt recovery result envelope missing items"
            )

        return [self._normalize_item(item) for item in items]

    async def invoke_method(
        self,
        *,
        runtime: A2ARuntime,
        ext: ResolvedInterruptRecoveryExtension,
        jsonrpc_url: str,
        method_key: str,
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
            params={},
        )

        meta: Dict[str, Any] = {
            "extension_uri": ext.uri,
            "jsonrpc_fallback_used": ext.jsonrpc.fallback_used,
            "method_key": method_key,
            "method_name": method_name,
        }
        metric_key = f"{ext.uri}:{method_name}"

        if resp.ok:
            items = self._normalize_result_items(resp.result or {})
            self._support.record_extension_metric(
                metric_key,
                success=True,
                error_code=None,
            )
            return ExtensionCallResult(
                success=True,
                result={"items": items},
                meta=meta,
            )

        error = resp.error or {}
        error_details = self._support.build_upstream_error_details(
            error=error,
            business_code_map=ext.business_code_map,
        )
        self._support.record_extension_metric(
            metric_key,
            success=False,
            error_code=error_details.error_code,
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

    async def recover_interrupts(
        self,
        *,
        runtime: A2ARuntime,
        ext: ResolvedInterruptRecoveryExtension,
        jsonrpc_url: str,
        session_id: str | None = None,
    ) -> ExtensionCallResult:
        resolved_session_id = self.prepare_recovery_query(session_id=session_id)
        permission_result = await self.invoke_method(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            method_key="list_permissions",
        )
        if not permission_result.success:
            return permission_result

        question_result = await self.invoke_method(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            method_key="list_questions",
        )
        if not question_result.success:
            return question_result

        items: list[dict[str, Any]] = []
        seen_request_ids: set[str] = set()

        for result in (permission_result, question_result):
            for item in list((result.result or {}).get("items") or []):
                if not isinstance(item, dict):
                    continue
                item_session_id = item.get("session_id")
                if (
                    resolved_session_id is not None
                    and item_session_id != resolved_session_id
                ):
                    continue
                request_id = item.get("request_id")
                if not isinstance(request_id, str) or request_id in seen_request_ids:
                    continue
                seen_request_ids.add(request_id)
                items.append(item)

        def _sort_key(item: dict[str, Any]) -> tuple[float, str]:
            raw_expires_at = item.get("expires_at")
            expires_at = (
                float(raw_expires_at)
                if isinstance(raw_expires_at, (int, float))
                else float("inf")
            )
            return expires_at, str(item.get("request_id") or "")

        items.sort(key=_sort_key)

        return ExtensionCallResult(
            success=True,
            result={"items": items},
            meta={
                "extension_uri": ext.uri,
                "jsonrpc_fallback_used": ext.jsonrpc.fallback_used,
                "session_id": resolved_session_id,
            },
        )
