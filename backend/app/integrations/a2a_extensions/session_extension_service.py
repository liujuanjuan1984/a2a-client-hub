from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from pydantic import ValidationError

from app.features.invoke.shared_metadata import merge_preferred_session_binding_metadata
from app.features.personal_agents.runtime import A2ARuntime
from app.integrations.a2a_extensions.errors import A2AExtensionContractError
from app.integrations.a2a_extensions.service_common import ExtensionCallResult
from app.integrations.a2a_extensions.shared_support import A2AExtensionSupport
from app.integrations.a2a_extensions.types import (
    ResolvedExtension,
    ResultEnvelopeMapping,
)
from app.schemas.a2a_extension import A2AExtensionQueryResult

_MISSING = object()


class SessionExtensionService:
    def __init__(self, support: A2AExtensionSupport) -> None:
        self._support = support

    def prepare_prompt_session_async(
        self,
        *,
        session_id: str,
        request_payload: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> tuple[str, Dict[str, Any]]:
        resolved_session_id = (session_id or "").strip()
        if not resolved_session_id:
            raise ValueError("session_id is required")

        if not isinstance(request_payload, dict):
            raise ValueError("request must be an object")

        parts = request_payload.get("parts")
        if not isinstance(parts, list) or len(parts) == 0:
            raise ValueError("request.parts must be a non-empty array")

        params: Dict[str, Any] = {
            "session_id": resolved_session_id,
            "request": dict(request_payload),
        }
        normalized_metadata = self._support.normalize_extension_metadata(metadata)
        if normalized_metadata is not None:
            params["metadata"] = normalized_metadata
        return resolved_session_id, params

    def prepare_session_command(
        self,
        *,
        session_id: str,
        request_payload: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> tuple[str, Dict[str, Any]]:
        resolved_session_id = (session_id or "").strip()
        if not resolved_session_id:
            raise ValueError("session_id is required")

        if not isinstance(request_payload, dict):
            raise ValueError("request must be an object")

        command = request_payload.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("request.command must be a non-empty string")

        arguments = request_payload.get("arguments")
        if not isinstance(arguments, str):
            raise ValueError("request.arguments must be a string")

        parts = request_payload.get("parts")
        if parts is not None and not isinstance(parts, list):
            raise ValueError("request.parts must be an array")

        for key in ("agent", "variant", "messageID"):
            value = request_payload.get(key)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"request.{key} must be a string")

        params: Dict[str, Any] = {
            "session_id": resolved_session_id,
            "request": dict(request_payload),
        }
        normalized_metadata = self._support.normalize_extension_metadata(metadata)
        if normalized_metadata is not None:
            params["metadata"] = normalized_metadata
        return resolved_session_id, params

    @staticmethod
    def _normalize_envelope(
        result: Any,
        *,
        page: int,
        size: int,
        result_envelope: ResultEnvelopeMapping | None = None,
        page_info: Dict[str, Any] | None = None,
        include_raw: bool = False,
    ) -> Optional[Dict[str, Any]]:
        if result is None:
            return None

        if isinstance(result, list):
            normalized_envelope = {
                "items": result,
                "pagination": {"page": page, "size": size},
            }
            if page_info is not None:
                normalized_envelope["pageInfo"] = page_info
            if include_raw:
                normalized_envelope["raw"] = result
            return SessionExtensionService._validate_query_result(normalized_envelope)

        if not isinstance(result, dict):
            normalized_envelope = {
                "items": [],
                "pagination": {"page": page, "size": size},
            }
            if page_info is not None:
                normalized_envelope["pageInfo"] = page_info
            if include_raw:
                normalized_envelope["raw"] = result
            return SessionExtensionService._validate_query_result(normalized_envelope)

        strict_result_envelope = result_envelope is not None
        mapping = result_envelope or ResultEnvelopeMapping()
        raw: Any = _MISSING

        items, items_found = SessionExtensionService._resolve_result_field(
            result,
            path=mapping.items,
            fallback_path=None if strict_result_envelope else "items",
        )
        if items_found:
            if not isinstance(items, list):
                raise A2AExtensionContractError(
                    "Extension result envelope resolved invalid 'items'"
                )
        elif strict_result_envelope:
            raise A2AExtensionContractError(
                "Extension result envelope missing declared 'items'"
            )
        else:
            raw, _ = SessionExtensionService._resolve_result_field(
                result,
                path=mapping.raw,
                fallback_path="raw",
            )
            if raw is _MISSING:
                raw = result
            if isinstance(raw, list):
                items = raw
            else:
                items = []

        if strict_result_envelope and include_raw:
            raw, raw_found = SessionExtensionService._resolve_result_field(
                result,
                path=mapping.raw,
                fallback_path=None,
            )
            if not raw_found:
                raise A2AExtensionContractError(
                    "Extension result envelope missing declared 'raw'"
                )
        elif strict_result_envelope:
            raw = _MISSING
        elif isinstance(raw, list):
            pass

        pagination, pagination_found = SessionExtensionService._resolve_result_field(
            result,
            path=mapping.pagination,
            fallback_path=None if strict_result_envelope else "pagination",
        )
        if pagination_found:
            if not isinstance(pagination, dict):
                raise A2AExtensionContractError(
                    "Extension result envelope resolved invalid 'pagination'"
                )
        elif strict_result_envelope:
            raise A2AExtensionContractError(
                "Extension result envelope missing declared 'pagination'"
            )
        else:
            pagination = {"page": page, "size": size}

        if include_raw and raw is _MISSING:
            raw, _ = SessionExtensionService._resolve_result_field(
                result,
                path=mapping.raw,
                fallback_path=None if strict_result_envelope else "raw",
            )
            if raw is _MISSING:
                raw = result

        envelope: Dict[str, Any] = {
            "items": items,
            "pagination": pagination,
        }
        if page_info is not None:
            envelope["pageInfo"] = page_info
        if include_raw:
            envelope["raw"] = raw
        return SessionExtensionService._validate_query_result(envelope)

    @staticmethod
    def _resolve_result_field(
        result: Mapping[str, Any],
        *,
        path: str,
        fallback_path: str | None = None,
    ) -> tuple[Any, bool]:
        candidates = [path]
        if fallback_path and fallback_path not in candidates:
            candidates.append(fallback_path)

        for candidate in candidates:
            current: Any = result
            found = True
            for part in candidate.split("."):
                token = part.strip()
                if not token:
                    found = False
                    break
                if not isinstance(current, Mapping) or token not in current:
                    found = False
                    break
                current = current[token]
            if found:
                return current, True
        return _MISSING, False

    @staticmethod
    def _validate_query_result(envelope: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return A2AExtensionQueryResult.model_validate(envelope).model_dump(
                by_alias=True,
                exclude_none=True,
            )
        except ValidationError as exc:
            raise A2AExtensionContractError(
                "Extension result envelope is invalid"
            ) from exc

    @staticmethod
    def _coerce_page_size(
        *,
        default_size: int,
        max_size: int,
        page: int,
        size: Optional[int],
    ) -> tuple[int, int]:
        resolved_page = int(page)
        if resolved_page < 1:
            raise ValueError("page must be >= 1")
        resolved_size = default_size if size is None else int(size)
        if resolved_size < 1:
            raise ValueError("size must be >= 1")
        if resolved_size > max_size:
            raise ValueError(f"size must be <= {max_size}")
        return resolved_page, resolved_size

    @staticmethod
    def _build_pagination_params(
        *,
        mode: str,
        page: int,
        size: int,
        supports_offset: bool,
    ) -> Dict[str, int]:
        if mode == "page_size":
            return {"page": page, "size": size}
        if mode == "limit":
            if supports_offset:
                return {"offset": (page - 1) * size, "limit": size}
            if page > 1:
                raise ValueError(
                    "limit pagination without offset does not support page > 1"
                )
            return {"limit": size}
        raise ValueError(f"unsupported pagination mode: {mode}")

    @staticmethod
    def _resolve_message_next_before(
        *,
        result: Any,
        ext: ResolvedExtension,
    ) -> str | None:
        field = ext.message_cursor_pagination.result_cursor_field
        if not field or not isinstance(result, Mapping):
            return None
        value, found = SessionExtensionService._resolve_result_field(
            result,
            path=field,
            fallback_path=None,
        )
        if not found or value is None:
            return None
        if not isinstance(value, str):
            raise A2AExtensionContractError(
                "Extension result cursor field must resolve to a string or null"
            )
        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _build_call_meta(
        *,
        ext: ResolvedExtension,
        page: int,
        size: int,
        selection_meta: Optional[Dict[str, Any]] = None,
        meta_extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        meta = {
            "extension_uri": ext.uri,
            "jsonrpc_fallback_used": ext.jsonrpc.fallback_used,
            "pagination_mode": ext.pagination.mode,
            "pagination_params": list(ext.pagination.params),
            "pagination_supports_offset": ext.pagination.supports_offset,
            "page": page,
            "size": size,
            "max_size": ext.pagination.max_size,
            "default_size": ext.pagination.default_size,
        }
        if selection_meta:
            meta.update(selection_meta)
        if meta_extra:
            meta.update(meta_extra)
        return meta

    async def invoke_method(
        self,
        *,
        runtime: A2ARuntime,
        ext: ResolvedExtension,
        jsonrpc_url: str,
        selection_meta: Optional[Dict[str, Any]],
        method_key: str,
        params: Dict[str, Any],
        page: int,
        size: int,
        include_raw: bool = False,
        normalize_envelope: bool = True,
        meta_extra: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        method_name = ext.methods.get(method_key)
        if not method_name:
            meta = {"extension_uri": ext.uri}
            if selection_meta:
                meta.update(selection_meta)
            return ExtensionCallResult(
                success=False,
                error_code="method_not_supported",
                upstream_error={
                    "message": f"Method {method_key} is not supported by upstream"
                },
                meta=meta,
            )

        resp = await self._support.perform_jsonrpc_call(
            runtime=runtime,
            jsonrpc_url=jsonrpc_url,
            method_name=method_name,
            params=params,
        )

        meta = self._build_call_meta(
            ext=ext,
            page=page,
            size=size,
            selection_meta=selection_meta,
            meta_extra=meta_extra,
        )

        metric_key = f"{ext.uri}:{method_name}"
        if resp.ok:
            resolved_result: Optional[Dict[str, Any]]
            if normalize_envelope:
                resolved_result = self._normalize_envelope(
                    resp.result,
                    page=page,
                    size=size,
                    result_envelope=ext.result_envelope,
                    include_raw=include_raw,
                )
            elif isinstance(resp.result, dict):
                resolved_result = dict(resp.result)
            else:
                resolved_result = {"raw": resp.result}

            self._support.record_extension_metric(
                metric_key, success=True, error_code=None
            )
            return ExtensionCallResult(success=True, result=resolved_result, meta=meta)

        error = resp.error or {}
        error_details = self._support.build_business_error_details(error, ext)
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

    async def list_sessions(
        self,
        *,
        runtime: A2ARuntime,
        ext: ResolvedExtension,
        selection_meta: Optional[Dict[str, Any]],
        page: int,
        size: Optional[int],
        query: Optional[Dict[str, Any]],
        include_raw: bool = False,
    ) -> ExtensionCallResult:
        jsonrpc_url = self._support.ensure_outbound_allowed(
            ext.jsonrpc.url, purpose="JSON-RPC interface URL"
        )

        resolved_page, resolved_size = self._coerce_page_size(
            default_size=ext.pagination.default_size,
            max_size=ext.pagination.max_size,
            page=page,
            size=size,
        )
        if (
            ext.pagination.mode == "limit"
            and resolved_page > 1
            and not ext.pagination.supports_offset
        ):
            return ExtensionCallResult(
                success=True,
                result=self._normalize_envelope(
                    [],
                    page=resolved_page,
                    size=resolved_size,
                    include_raw=include_raw,
                ),
                meta=self._build_call_meta(
                    ext=ext,
                    page=resolved_page,
                    size=resolved_size,
                    selection_meta=selection_meta,
                    meta_extra={"short_circuit_reason": "limit_without_offset"},
                ),
            )

        params: Dict[str, Any] = self._build_pagination_params(
            mode=ext.pagination.mode,
            page=resolved_page,
            size=resolved_size,
            supports_offset=ext.pagination.supports_offset,
        )
        if query is not None:
            params["query"] = query

        return await self.invoke_method(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            selection_meta=selection_meta,
            method_key="list_sessions",
            params=params,
            page=resolved_page,
            size=resolved_size,
            include_raw=include_raw,
        )

    async def get_session_messages(
        self,
        *,
        runtime: A2ARuntime,
        ext: ResolvedExtension,
        selection_meta: Optional[Dict[str, Any]],
        session_id: str,
        page: int,
        size: Optional[int],
        before: str | None,
        query: Optional[Dict[str, Any]],
        include_raw: bool = False,
    ) -> ExtensionCallResult:
        resolved_session_id = (session_id or "").strip()
        if not resolved_session_id:
            raise ValueError("session_id is required")
        resolved_before = (before or "").strip() or None
        if resolved_before is not None and int(page) > 1:
            raise ValueError("before cannot be combined with page > 1")
        if (
            resolved_before is not None
            and not ext.message_cursor_pagination.cursor_param
        ):
            raise ValueError("before is not supported by this runtime")

        jsonrpc_url = self._support.ensure_outbound_allowed(
            ext.jsonrpc.url, purpose="JSON-RPC interface URL"
        )

        resolved_page, resolved_size = self._coerce_page_size(
            default_size=ext.pagination.default_size,
            max_size=ext.pagination.max_size,
            page=1 if resolved_before is not None else page,
            size=size,
        )
        if (
            ext.pagination.mode == "limit"
            and resolved_page > 1
            and not ext.pagination.supports_offset
            and resolved_before is None
        ):
            return ExtensionCallResult(
                success=True,
                result=self._normalize_envelope(
                    [],
                    page=resolved_page,
                    size=resolved_size,
                    include_raw=include_raw,
                ),
                meta=self._build_call_meta(
                    ext=ext,
                    page=resolved_page,
                    size=resolved_size,
                    selection_meta=selection_meta,
                    meta_extra={
                        "session_id": resolved_session_id,
                        "short_circuit_reason": "limit_without_offset",
                    },
                ),
            )

        params: Dict[str, Any] = {
            "session_id": resolved_session_id,
            **self._build_pagination_params(
                mode=ext.pagination.mode,
                page=resolved_page,
                size=resolved_size,
                supports_offset=ext.pagination.supports_offset,
            ),
        }
        if query is not None:
            params["query"] = query
        if resolved_before is not None:
            cursor_param = ext.message_cursor_pagination.cursor_param
            assert cursor_param is not None
            params[cursor_param] = resolved_before

        result = await self.invoke_method(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            selection_meta=selection_meta,
            method_key="get_session_messages",
            params=params,
            page=resolved_page,
            size=resolved_size,
            include_raw=include_raw,
            normalize_envelope=False,
            meta_extra={"session_id": resolved_session_id},
        )
        if not result.success:
            return result

        next_before = self._resolve_message_next_before(result=result.result, ext=ext)
        normalized_result = self._normalize_envelope(
            result.result,
            page=resolved_page,
            size=resolved_size,
            result_envelope=ext.result_envelope,
            page_info={
                "hasMoreBefore": next_before is not None,
                "nextBefore": next_before,
            },
            include_raw=include_raw,
        )
        return ExtensionCallResult(
            success=True,
            result=normalized_result,
            error_code=result.error_code,
            source=result.source,
            jsonrpc_code=result.jsonrpc_code,
            missing_params=result.missing_params,
            upstream_error=result.upstream_error,
            meta=result.meta,
        )

    async def continue_session(
        self,
        *,
        runtime: A2ARuntime,
        ext: ResolvedExtension,
        selection_meta: Optional[Dict[str, Any]],
        binding_meta: Dict[str, Any],
        session_id: str,
    ) -> ExtensionCallResult:
        resolved_session_id = (session_id or "").strip()
        if not resolved_session_id:
            raise ValueError("session_id is required")

        jsonrpc_url = self._support.ensure_outbound_allowed(
            ext.jsonrpc.url, purpose="JSON-RPC interface URL"
        )

        validation = await self.invoke_method(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            selection_meta=selection_meta,
            method_key="get_session_messages",
            params={
                "session_id": resolved_session_id,
                **self._build_pagination_params(
                    mode=ext.pagination.mode,
                    page=1,
                    size=1,
                    supports_offset=ext.pagination.supports_offset,
                ),
            },
            page=1,
            size=1,
            meta_extra={"session_id": resolved_session_id},
        )
        if not validation.success:
            return validation

        meta = dict(validation.meta or {})
        meta.update(
            {
                "binding_mode": "contextId+metadata",
                "validated": True,
                "provider": ext.provider,
            }
        )
        meta.update(binding_meta)
        binding_metadata = merge_preferred_session_binding_metadata(
            {"contextId": resolved_session_id},
            provider=ext.provider,
            external_session_id=resolved_session_id,
            include_legacy_root=(
                binding_meta.get("session_binding_mode") != "declared_contract"
            ),
        )
        return ExtensionCallResult(
            success=True,
            result={
                "contextId": resolved_session_id,
                "provider": ext.provider,
                "metadata": binding_metadata,
            },
            meta=meta,
        )

    async def prompt_session_async(
        self,
        *,
        runtime: A2ARuntime,
        ext: ResolvedExtension,
        selection_meta: Optional[Dict[str, Any]],
        session_id: str,
        request_payload: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        resolved_session_id, params = self.prepare_prompt_session_async(
            session_id=session_id,
            request_payload=request_payload,
            metadata=metadata,
        )

        jsonrpc_url = self._support.ensure_outbound_allowed(
            ext.jsonrpc.url, purpose="JSON-RPC interface URL"
        )
        return await self.invoke_method(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            selection_meta=selection_meta,
            method_key="prompt_async",
            params=params,
            page=1,
            size=1,
            normalize_envelope=False,
            meta_extra={
                "session_id": resolved_session_id,
                "control_method": "prompt_async",
            },
        )

    async def command_session(
        self,
        *,
        runtime: A2ARuntime,
        ext: ResolvedExtension,
        selection_meta: Optional[Dict[str, Any]],
        session_id: str,
        request_payload: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
        resolved_session_id, params = self.prepare_session_command(
            session_id=session_id,
            request_payload=request_payload,
            metadata=metadata,
        )

        jsonrpc_url = self._support.ensure_outbound_allowed(
            ext.jsonrpc.url, purpose="JSON-RPC interface URL"
        )
        return await self.invoke_method(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            selection_meta=selection_meta,
            method_key="command",
            params=params,
            page=1,
            size=1,
            normalize_envelope=False,
            meta_extra={
                "session_id": resolved_session_id,
                "control_method": "command",
            },
        )
