"""Runtime selection for shared session query capability handling."""

from __future__ import annotations

from dataclasses import dataclass

from a2a.types import AgentCard

from app.integrations.a2a_extensions.errors import (
    A2AExtensionContractError,
    A2AExtensionNotSupportedError,
)
from app.integrations.a2a_extensions.session_query import (
    resolve_canonical_session_query,
    resolve_codex_session_query,
    resolve_legacy_session_query,
    resolve_session_query_control_methods,
)
from app.integrations.a2a_extensions.session_query_diagnostics import (
    diagnose_session_query,
)
from app.integrations.a2a_extensions.types import (
    ResolvedExtension,
    ResolvedSessionControlMethodCapability,
)


@dataclass(frozen=True, slots=True)
class ResolvedSessionQueryRuntimeCapability:
    """Resolved runtime selection derived from shared diagnostics."""

    ext: ResolvedExtension
    contract_mode: str
    selection_mode: str
    control_methods: dict[str, ResolvedSessionControlMethodCapability]


def resolve_runtime_session_query(
    card: AgentCard,
) -> ResolvedSessionQueryRuntimeCapability:
    diagnostic = diagnose_session_query(card)

    if diagnostic.status == "canonical":
        ext = resolve_canonical_session_query(card)
        return ResolvedSessionQueryRuntimeCapability(
            ext=ext,
            contract_mode="canonical",
            selection_mode="canonical_parser",
            control_methods=resolve_session_query_control_methods(card, ext=ext),
        )

    if diagnostic.status == "legacy":
        ext = resolve_legacy_session_query(card)
        return ResolvedSessionQueryRuntimeCapability(
            ext=ext,
            contract_mode="legacy",
            selection_mode="legacy_compatibility",
            control_methods=resolve_session_query_control_methods(card, ext=ext),
        )

    if diagnostic.status == "codex":
        ext = resolve_codex_session_query(card)
        return ResolvedSessionQueryRuntimeCapability(
            ext=ext,
            contract_mode="codex",
            selection_mode="codex_compatibility",
            control_methods=resolve_session_query_control_methods(card, ext=ext),
        )

    if diagnostic.status == "invalid":
        raise A2AExtensionContractError(
            diagnostic.error or "Shared session query contract is invalid"
        )

    raise A2AExtensionNotSupportedError(
        diagnostic.error or "Shared session query extension not supported by Hub"
    )


__all__ = [
    "ResolvedSessionQueryRuntimeCapability",
    "resolve_runtime_session_query",
]
