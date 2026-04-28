"""Shared session query diagnostics for card validation and agent onboarding."""

from __future__ import annotations

from typing import Any, Literal

from a2a.types import AgentCard

from app.integrations.a2a_extensions.contract_utils import as_dict
from app.integrations.a2a_extensions.errors import A2AExtensionContractError
from app.integrations.a2a_extensions.session_query import (
    resolve_canonical_session_query,
    resolve_codex_session_query,
)
from app.integrations.a2a_extensions.shared_contract import (
    CODEX_SHARED_SESSION_QUERY_URI,
    LEGACY_SHARED_SESSION_QUERY_URI,
    SUPPORTED_SESSION_QUERY_URIS,
)
from app.schemas.a2a_agent_card import SharedSessionQueryDiagnostic

_HUB_PRIVATE_SESSION_QUERY_CONTRACT_FAMILY = "a2a_client_hub"


def _declared_contract_family(
    *,
    uses_legacy_uri: bool,
    uses_legacy_contract_fields: bool,
    uses_codex_uri: bool,
) -> Literal["opencode", "codex", "legacy"]:
    if uses_legacy_uri or uses_legacy_contract_fields:
        return "legacy"
    if uses_codex_uri:
        return "codex"
    return "opencode"


def _find_declared_extension(card: AgentCard) -> tuple[Any | None, str | None]:
    capabilities = getattr(card, "capabilities", None)
    extensions = getattr(capabilities, "extensions", None) if capabilities else None
    if not extensions:
        return None, None

    hinted = None
    for candidate in extensions:
        uri = str(getattr(candidate, "uri", "") or "").strip()
        if uri in SUPPORTED_SESSION_QUERY_URIS:
            return candidate, uri
        if hinted is None and ("session-query" in uri or "session-management" in uri):
            hinted = candidate, uri
    return hinted if hinted is not None else (None, None)


def diagnose_session_query(card: AgentCard) -> SharedSessionQueryDiagnostic:
    ext, uri = _find_declared_extension(card)
    if ext is None:
        return SharedSessionQueryDiagnostic(
            declared=False,
            status="unsupported",
            error="Shared session query extension not declared",
        )

    params = as_dict(getattr(ext, "params", None))
    methods = as_dict(params.get("methods"))
    raw_pagination = as_dict(params.get("pagination"))
    result_envelope = params.get("result_envelope")
    uses_legacy_uri = uri == LEGACY_SHARED_SESSION_QUERY_URI
    uses_codex_uri = uri == CODEX_SHARED_SESSION_QUERY_URI
    uses_legacy_contract_fields = bool(
        raw_pagination.get("mode") == "limit"
        and (
            "default_size" in raw_pagination
            or "max_size" in raw_pagination
            or "page" in raw_pagination.get("params", [])
        )
    )
    declared_contract_family = _declared_contract_family(
        uses_legacy_uri=uses_legacy_uri,
        uses_legacy_contract_fields=uses_legacy_contract_fields,
        uses_codex_uri=uses_codex_uri,
    )

    if uses_legacy_uri:
        return SharedSessionQueryDiagnostic(
            declared=True,
            status="unsupported",
            uri=uri,
            declaredContractFamily=declared_contract_family,
            provider=str(params.get("provider") or "").strip().lower() or None,
            methods=sorted(
                key
                for key, value in methods.items()
                if isinstance(value, str) and value.strip()
            ),
            pagination_mode=(
                str(raw_pagination.get("mode")).strip() if raw_pagination else None
            ),
            pagination_params=[
                item.strip()
                for item in raw_pagination.get("params", [])
                if isinstance(item, str) and item.strip()
            ],
            result_envelope_declared=result_envelope is not None,
            uses_legacy_uri=True,
            error=(
                "Shared session query legacy URI is no longer supported by Hub; "
                "migrate to a canonical or opencode session-query URI"
            ),
        )

    if uri not in SUPPORTED_SESSION_QUERY_URIS:
        return SharedSessionQueryDiagnostic(
            declared=True,
            status="unsupported",
            uri=uri,
            error="Shared session query extension URI is not supported by Hub",
        )

    if uses_legacy_contract_fields:
        return SharedSessionQueryDiagnostic(
            declared=True,
            status="unsupported",
            uri=uri,
            declaredContractFamily=declared_contract_family,
            provider=str(params.get("provider") or "").strip().lower() or None,
            methods=sorted(
                key
                for key, value in methods.items()
                if isinstance(value, str) and value.strip()
            ),
            pagination_mode=(
                str(raw_pagination.get("mode")).strip() if raw_pagination else None
            ),
            pagination_params=[
                item.strip()
                for item in raw_pagination.get("params", [])
                if isinstance(item, str) and item.strip()
            ],
            result_envelope_declared=result_envelope is not None,
            uses_legacy_contract_fields=True,
            error=(
                "Shared session query legacy pagination fields are no longer "
                "supported; use pagination.default_limit/max_limit for mode "
                "'limit'"
            ),
        )

    try:
        if uses_codex_uri:
            resolver = resolve_codex_session_query
        else:
            resolver = resolve_canonical_session_query
        resolved = resolver(card)
    except A2AExtensionContractError as exc:
        return SharedSessionQueryDiagnostic(
            declared=True,
            status="invalid",
            uri=uri,
            declaredContractFamily=declared_contract_family,
            normalizedContractFamily=_HUB_PRIVATE_SESSION_QUERY_CONTRACT_FAMILY,
            provider=str(params.get("provider") or "").strip().lower() or None,
            methods=sorted(
                key
                for key, value in methods.items()
                if isinstance(value, str) and value.strip()
            ),
            pagination_mode=(
                str(raw_pagination.get("mode")).strip() if raw_pagination else None
            ),
            pagination_params=[
                item.strip()
                for item in raw_pagination.get("params", [])
                if isinstance(item, str) and item.strip()
            ],
            result_envelope_declared=result_envelope is not None,
            uses_legacy_uri=uses_legacy_uri,
            uses_legacy_contract_fields=uses_legacy_contract_fields,
            error=str(exc),
        )

    return SharedSessionQueryDiagnostic(
        declared=True,
        status="supported",
        uri=resolved.uri,
        declaredContractFamily=declared_contract_family,
        normalizedContractFamily=_HUB_PRIVATE_SESSION_QUERY_CONTRACT_FAMILY,
        provider=resolved.provider,
        methods=sorted(key for key, value in resolved.methods.items() if value),
        pagination_mode=(
            str(raw_pagination.get("mode")).strip()
            if raw_pagination and raw_pagination.get("mode") is not None
            else resolved.pagination.mode
        ),
        pagination_params=list(resolved.pagination.params),
        result_envelope_declared=resolved.result_envelope is not None,
        jsonrpc_interface_fallback_used=resolved.jsonrpc.fallback_used,
        uses_legacy_uri=uses_legacy_uri,
        uses_legacy_contract_fields=uses_legacy_contract_fields,
    )
