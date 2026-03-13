from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Mapping, Optional

from pydantic import ValidationError

from app.integrations.a2a_extensions.errors import A2AExtensionContractError
from app.integrations.a2a_extensions.service_common import ExtensionCallResult
from app.integrations.a2a_extensions.session_query import resolve_session_query
from app.integrations.a2a_extensions.types import (
    ResolvedExtension,
    ResultEnvelopeMapping,
)
from app.schemas.a2a_extension import A2AExtensionQueryResult
from app.services.a2a_runtime import A2ARuntime

if TYPE_CHECKING:
    from app.integrations.a2a_extensions.service import A2AExtensionsService

_MISSING = object()


class SessionExtensionService:
    def __init__(self, service: "A2AExtensionsService") -> None:
        self._service = service

    @staticmethod
    def _normalize_envelope(
        result: Any,
        *,
        page: int,
        size: int,
        result_envelope: ResultEnvelopeMapping | None = None,
        include_raw: bool = False,
    ) -> Optional[Dict[str, Any]]:
        if result is None:
            return None

        if isinstance(result, list):
            envelope = {
                "items": result,
                "pagination": {"page": page, "size": size},
            }
            if include_raw:
                envelope["raw"] = result
            return SessionExtensionService._validate_query_result(envelope)

        if not isinstance(result, dict):
            envelope = {
                "items": [],
                "pagination": {"page": page, "size": size},
            }
            if include_raw:
                envelope["raw"] = result
            return SessionExtensionService._validate_query_result(envelope)

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
                exclude_none=True
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
    def _build_call_meta(
        *,
        ext: ResolvedExtension,
        page: int,
        size: int,
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
        if meta_extra:
            meta.update(meta_extra)
        return meta

    async def resolve_extension(
        self, runtime: A2ARuntime
    ) -> tuple[ResolvedExtension, str]:
        card = await self._service._fetch_card(runtime)
        ext = resolve_session_query(card)
        jsonrpc_url = self._service._ensure_outbound_allowed(
            ext.jsonrpc.url, purpose="JSON-RPC interface URL"
        )
        return ext, jsonrpc_url

    async def invoke_method(
        self,
        *,
        runtime: A2ARuntime,
        ext: ResolvedExtension,
        jsonrpc_url: str,
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
            return ExtensionCallResult(
                success=False,
                error_code="method_not_supported",
                upstream_error={
                    "message": f"Method {method_key} is not supported by upstream"
                },
                meta={"extension_uri": ext.uri},
            )

        resp = await self._service._perform_jsonrpc_call(
            runtime=runtime,
            jsonrpc_url=jsonrpc_url,
            method_name=method_name,
            params=params,
        )

        meta = self._build_call_meta(
            ext=ext,
            page=page,
            size=size,
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

            self._service._record_extension_metric(
                metric_key, success=True, error_code=None
            )
            return ExtensionCallResult(success=True, result=resolved_result, meta=meta)

        error = resp.error or {}
        error_code = self._service._map_business_error_code(error, ext)
        self._service._record_extension_metric(
            metric_key, success=False, error_code=error_code
        )
        return ExtensionCallResult(
            success=False,
            error_code=error_code,
            upstream_error=error,
            meta=meta,
        )

    async def list_sessions(
        self,
        *,
        runtime: A2ARuntime,
        page: int,
        size: Optional[int],
        query: Optional[Dict[str, Any]],
        include_raw: bool = False,
    ) -> ExtensionCallResult:
        ext, jsonrpc_url = await self.resolve_extension(runtime)

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
        session_id: str,
        page: int,
        size: Optional[int],
        query: Optional[Dict[str, Any]],
        include_raw: bool = False,
    ) -> ExtensionCallResult:
        resolved_session_id = (session_id or "").strip()
        if not resolved_session_id:
            raise ValueError("session_id is required")

        ext, jsonrpc_url = await self.resolve_extension(runtime)

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

        return await self.invoke_method(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
            method_key="get_session_messages",
            params=params,
            page=resolved_page,
            size=resolved_size,
            include_raw=include_raw,
            meta_extra={"session_id": resolved_session_id},
        )

    async def continue_session(
        self,
        *,
        runtime: A2ARuntime,
        session_id: str,
    ) -> ExtensionCallResult:
        resolved_session_id = (session_id or "").strip()
        if not resolved_session_id:
            raise ValueError("session_id is required")

        ext, jsonrpc_url = await self.resolve_extension(runtime)

        validation = await self.invoke_method(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
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
        return ExtensionCallResult(
            success=True,
            result={
                "contextId": resolved_session_id,
                "provider": ext.provider,
                "metadata": {
                    "provider": ext.provider,
                    "externalSessionId": resolved_session_id,
                    "contextId": resolved_session_id,
                },
            },
            meta=meta,
        )

    async def prompt_session_async(
        self,
        *,
        runtime: A2ARuntime,
        session_id: str,
        request_payload: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionCallResult:
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
        normalized_metadata = self._service._normalize_extension_metadata(metadata)
        if normalized_metadata is not None:
            params["metadata"] = normalized_metadata

        ext, jsonrpc_url = await self.resolve_extension(runtime)
        return await self.invoke_method(
            runtime=runtime,
            ext=ext,
            jsonrpc_url=jsonrpc_url,
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
