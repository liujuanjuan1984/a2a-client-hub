from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import WebSocketException, status
from sqlalchemy.exc import DBAPIError

from app.api.deps import get_ws_ticket_user
from app.core.config import settings
from app.services.ws_ticket_service import (
    WsTicketConflictError,
    WsTicketNotFoundError,
    ws_ticket_service,
)


def _build_websocket(*, ticket: str) -> SimpleNamespace:
    return SimpleNamespace(
        headers={"sec-websocket-protocol": ticket},
        state=SimpleNamespace(),
    )


@pytest.mark.asyncio
async def test_get_ws_ticket_user_returns_try_again_later_on_ticket_conflict(
    monkeypatch,
) -> None:
    async def _raise_conflict(*_args, **_kwargs):
        raise WsTicketConflictError("Ticket is being consumed by another request")

    monkeypatch.setattr(settings, "ws_require_origin", False, raising=False)
    monkeypatch.setattr(ws_ticket_service, "consume_ticket", _raise_conflict)

    with pytest.raises(WebSocketException) as exc_info:
        await get_ws_ticket_user(
            websocket=_build_websocket(ticket="a" * settings.ws_ticket_length),
            scope_type="me_a2a_agent",
            scope_id=uuid4(),
            db=MagicMock(),
        )

    assert exc_info.value.code == status.WS_1013_TRY_AGAIN_LATER
    assert exc_info.value.reason == "Ticket is being consumed by another request"


@pytest.mark.asyncio
async def test_get_ws_ticket_user_keeps_policy_violation_for_invalid_ticket(
    monkeypatch,
) -> None:
    async def _raise_not_found(*_args, **_kwargs):
        raise WsTicketNotFoundError("Invalid or expired ticket")

    monkeypatch.setattr(settings, "ws_require_origin", False, raising=False)
    monkeypatch.setattr(ws_ticket_service, "consume_ticket", _raise_not_found)

    with pytest.raises(WebSocketException) as exc_info:
        await get_ws_ticket_user(
            websocket=_build_websocket(ticket="a" * settings.ws_ticket_length),
            scope_type="me_a2a_agent",
            scope_id=uuid4(),
            db=MagicMock(),
        )

    assert exc_info.value.code == status.WS_1008_POLICY_VIOLATION
    assert exc_info.value.reason == "Invalid or expired ticket"


@pytest.mark.asyncio
async def test_get_ws_ticket_user_returns_try_again_later_on_db_statement_timeout(
    monkeypatch,
) -> None:
    class _StatementTimeoutError(Exception):
        sqlstate = "57014"

    async def _raise_statement_timeout(*_args, **_kwargs):
        raise DBAPIError(
            statement="SELECT ... FOR UPDATE NOWAIT",
            params={},
            orig=_StatementTimeoutError("canceling statement due to statement timeout"),
        )

    monkeypatch.setattr(settings, "ws_require_origin", False, raising=False)
    monkeypatch.setattr(ws_ticket_service, "consume_ticket", _raise_statement_timeout)

    with pytest.raises(WebSocketException) as exc_info:
        await get_ws_ticket_user(
            websocket=_build_websocket(ticket="a" * settings.ws_ticket_length),
            scope_type="me_a2a_agent",
            scope_id=uuid4(),
            db=MagicMock(),
        )

    assert exc_info.value.code == status.WS_1013_TRY_AGAIN_LATER
    assert exc_info.value.reason == "Ticket verification timed out; retry shortly"
