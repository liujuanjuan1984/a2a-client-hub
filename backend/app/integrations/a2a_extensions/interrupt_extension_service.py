from __future__ import annotations

from typing import Any, Dict, Optional

from app.integrations.a2a_extensions.service_common import ExtensionCallResult
from app.integrations.a2a_extensions.shared_support import A2AExtensionSupport
from app.integrations.a2a_extensions.types import ResolvedInterruptCallbackExtension
from app.services.a2a_runtime import A2ARuntime


class InterruptExtensionService:
    def __init__(self, support: A2AExtensionSupport) -> None:
        self._support = support

    def prepare_reply_permission_interrupt(
        self,
        *,
        request_id: str,
        reply: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> tuple[str, str, Optional[Dict[str, Any]]]:
        resolved_request_id = (request_id or "").strip()
        if not resolved_request_id:
            raise ValueError("request_id is required")
        resolved_reply = (reply or "").strip().lower()
        if resolved_reply not in {"once", "always", "reject"}:
            raise ValueError("reply must be one of: once, always, reject")
        normalized_metadata = self._support.normalize_extension_metadata(metadata)
        return resolved_request_id, resolved_reply, normalized_metadata

    def prepare_reply_question_interrupt(
        self,
        *,
        request_id: str,
        answers: list[list[str]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> tuple[str, list[list[str]], Optional[Dict[str, Any]]]:
        resolved_request_id = (request_id or "").strip()
        if not resolved_request_id:
            raise ValueError("request_id is required")
        normalized_metadata = self._support.normalize_extension_metadata(metadata)
        return resolved_request_id, answers, normalized_metadata

    def prepare_reject_question_interrupt(
        self,
        *,
        request_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> tuple[str, Optional[Dict[str, Any]]]:
        resolved_request_id = (request_id or "").strip()
        if not resolved_request_id:
            raise ValueError("request_id is required")
        normalized_metadata = self._support.normalize_extension_metadata(metadata)
        return resolved_request_id, normalized_metadata

    async def invoke_method(
        self,
        *,
        runtime: A2ARuntime,
        ext: ResolvedInterruptCallbackExtension,
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
        }
        if meta_extra:
            meta.update(meta_extra)

        metric_key = f"{ext.uri}:{method_name}"
        if resp.ok:
            self._support.record_extension_metric(
                metric_key, success=True, error_code=None
            )
            return ExtensionCallResult(success=True, result=resp.result, meta=meta)

        error = resp.error or {}
        error_details = self._support.build_interrupt_business_error_details(error, ext)
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

    async def reply_permission_interrupt(
        self,
        *,
        runtime: A2ARuntime,
        ext: ResolvedInterruptCallbackExtension,
        jsonrpc_url: str,
        request_id: str,
        reply: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        (
            resolved_request_id,
            resolved_reply,
            normalized_metadata,
        ) = self.prepare_reply_permission_interrupt(
            request_id=request_id,
            reply=reply,
            metadata=metadata,
        )

        params: Dict[str, Any] = {
            "request_id": resolved_request_id,
            "reply": resolved_reply,
        }
        if normalized_metadata is not None:
            params["metadata"] = normalized_metadata
        return await self.invoke_method(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            method_key="reply_permission",
            params=params,
            meta_extra={"request_id": resolved_request_id},
        )

    async def reply_question_interrupt(
        self,
        *,
        runtime: A2ARuntime,
        ext: ResolvedInterruptCallbackExtension,
        jsonrpc_url: str,
        request_id: str,
        answers: list[list[str]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        (
            resolved_request_id,
            resolved_answers,
            normalized_metadata,
        ) = self.prepare_reply_question_interrupt(
            request_id=request_id,
            answers=answers,
            metadata=metadata,
        )

        params: Dict[str, Any] = {
            "request_id": resolved_request_id,
            "answers": resolved_answers,
        }
        if normalized_metadata is not None:
            params["metadata"] = normalized_metadata
        return await self.invoke_method(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            method_key="reply_question",
            params=params,
            meta_extra={"request_id": resolved_request_id},
        )

    async def reject_question_interrupt(
        self,
        *,
        runtime: A2ARuntime,
        ext: ResolvedInterruptCallbackExtension,
        jsonrpc_url: str,
        request_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        (
            resolved_request_id,
            normalized_metadata,
        ) = self.prepare_reject_question_interrupt(
            request_id=request_id,
            metadata=metadata,
        )

        params: Dict[str, Any] = {"request_id": resolved_request_id}
        if normalized_metadata is not None:
            params["metadata"] = normalized_metadata
        return await self.invoke_method(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            method_key="reject_question",
            params=params,
            meta_extra={"request_id": resolved_request_id},
        )
