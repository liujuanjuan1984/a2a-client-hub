"""Runtime selection for shared session query capability handling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from a2a.types import AgentCard

from app.integrations.a2a_extensions.errors import (
    A2AExtensionContractError,
    A2AExtensionNotSupportedError,
)
from app.integrations.a2a_extensions.session_query import (
    resolve_session_query,
    resolve_session_query_control_methods,
)
from app.integrations.a2a_extensions.session_query_diagnostics import (
    diagnose_session_query,
)
from app.integrations.a2a_extensions.shared_contract import (
    CODEX_SHARED_SESSION_QUERY_URI,
)
from app.integrations.a2a_extensions.types import (
    ResolvedExtension,
    ResolvedSessionControlMethodCapability,
)


@dataclass(frozen=True, slots=True)
class ResolvedSessionQueryRuntimeCapability:
    """Resolved runtime selection derived from shared diagnostics."""

    ext: ResolvedExtension
    negotiation_mode: Literal["declared_contract"]
    compatibility_hints_applied: bool
    control_methods: dict[str, ResolvedSessionControlMethodCapability]


def resolve_runtime_session_query(
    card: AgentCard,
) -> ResolvedSessionQueryRuntimeCapability:
    diagnostic = diagnose_session_query(card)

    if diagnostic.status == "supported":
        ext = resolve_session_query(card)
        return ResolvedSessionQueryRuntimeCapability(
            ext=ext,
            negotiation_mode="declared_contract",
            compatibility_hints_applied=ext.uri == CODEX_SHARED_SESSION_QUERY_URI,
            control_methods=resolve_session_query_control_methods(card, ext=ext),
        )

    if diagnostic.status == "invalid":
        raise A2AExtensionContractError(
            diagnostic.error or "Shared session query contract is invalid"
        )

    raise A2AExtensionNotSupportedError(
        diagnostic.error or "Shared session query extension not supported by Hub"
    )
