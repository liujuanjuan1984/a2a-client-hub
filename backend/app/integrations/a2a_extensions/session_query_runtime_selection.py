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
    resolve_legacy_session_query,
)
from app.integrations.a2a_extensions.session_query_diagnostics import (
    diagnose_session_query,
)
from app.integrations.a2a_extensions.types import ResolvedExtension


@dataclass(frozen=True, slots=True)
class ResolvedSessionQueryRuntimeCapability:
    """Resolved runtime selection derived from shared diagnostics."""

    ext: ResolvedExtension
    contract_mode: str
    selection_mode: str


def resolve_runtime_session_query(
    card: AgentCard,
) -> ResolvedSessionQueryRuntimeCapability:
    diagnostic = diagnose_session_query(card)

    if diagnostic.status == "canonical":
        return ResolvedSessionQueryRuntimeCapability(
            ext=resolve_canonical_session_query(card),
            contract_mode="canonical",
            selection_mode="canonical_parser",
        )

    if diagnostic.status == "legacy":
        return ResolvedSessionQueryRuntimeCapability(
            ext=resolve_legacy_session_query(card),
            contract_mode="legacy",
            selection_mode="legacy_compatibility",
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
