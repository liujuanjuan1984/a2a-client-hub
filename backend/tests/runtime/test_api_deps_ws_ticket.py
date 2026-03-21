from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import WebSocketException, status

from app.api import deps as api_deps
from app.api.deps import get_ws_ticket_user
from app.api.retry_after import DB_BUSY_RETRY_AFTER_SECONDS
from app.core.config import settings
from app.db.locking import (
    DbLockFailureKind,
    RetryableDbLockError,
    RetryableDbQueryTimeoutError,
)
from app.runtime.ws_ticket import (
    WsTicketNotFoundError,
    ws_ticket_service,
)


def _build_websocket(*, ticket: str) -> SimpleNamespace:
    return SimpleNamespace(
        headers={"sec-websocket-protocol": ticket},
        state=SimpleNamespace(),
    )


def test_parse_ws_protocol_selection_extracts_ticket_without_subprotocol() -> None:
    ticket = "a" * settings.ws_ticket_length

    selection = api_deps._parse_ws_protocol_selection(
        subprotocol_header=ticket,
    )

    assert selection.ticket == ticket
    assert selection.accepted_subprotocol is None


def test_parse_ws_protocol_selection_accepts_only_allowlisted_subprotocol() -> None:
    ticket = "a" * settings.ws_ticket_length

    selection = api_deps._parse_ws_protocol_selection(
        subprotocol_header=f"chat.v2, {ticket}, ignored.v1",
        allowed_subprotocols=("chat.v2",),
    )

    assert selection.ticket == ticket
    assert selection.accepted_subprotocol == "chat.v2"


@pytest.mark.asyncio
async def test_get_ws_ticket_user_echoes_valid_subprotocol(
    monkeypatch,
) -> None:
    ticket = "a" * settings.ws_ticket_length
    consumed = SimpleNamespace(user_id=uuid4())
    active_user = SimpleNamespace(id=consumed.user_id)

    async def _consume_ticket(*_args, **_kwargs):
        return consumed

    async def _get_active_user(*_args, **_kwargs):
        return active_user

    monkeypatch.setattr(settings, "ws_require_origin", False, raising=False)
    monkeypatch.setattr(ws_ticket_service, "consume_ticket", _consume_ticket)
    monkeypatch.setattr(api_deps.auth_service, "get_active_user", _get_active_user)

    websocket = _build_websocket(ticket=f"a2a-invoke-v1, {ticket}")
    user = await get_ws_ticket_user(
        websocket=websocket,
        scope_type="me_a2a_agent",
        scope_id=uuid4(),
    )

    assert user is active_user
    assert getattr(websocket.state, "selected_subprotocol", None) == "a2a-invoke-v1"


@pytest.mark.asyncio
async def test_get_ws_ticket_user_returns_try_again_later_on_ticket_conflict(
    monkeypatch,
) -> None:
    async def _raise_conflict(*_args, **_kwargs):
        raise RetryableDbLockError(
            "Ticket is being consumed by another request",
            kind=DbLockFailureKind.LOCK_NOT_AVAILABLE,
        )

    monkeypatch.setattr(settings, "ws_require_origin", False, raising=False)
    monkeypatch.setattr(ws_ticket_service, "consume_ticket", _raise_conflict)

    with pytest.raises(WebSocketException) as exc_info:
        await get_ws_ticket_user(
            websocket=_build_websocket(ticket="a" * settings.ws_ticket_length),
            scope_type="me_a2a_agent",
            scope_id=uuid4(),
        )

    assert exc_info.value.code == status.WS_1013_TRY_AGAIN_LATER
    assert exc_info.value.reason == (
        "Ticket is being consumed by another request"
        f" Retry in {DB_BUSY_RETRY_AFTER_SECONDS} seconds."
    )


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
        )

    assert exc_info.value.code == status.WS_1008_POLICY_VIOLATION
    assert exc_info.value.reason == "Invalid or expired ticket"


@pytest.mark.asyncio
async def test_get_ws_ticket_user_returns_try_again_later_on_db_statement_timeout(
    monkeypatch,
) -> None:
    async def _raise_statement_timeout(*_args, **_kwargs):
        raise RetryableDbQueryTimeoutError(
            "Ticket verification timed out; service busy, retry shortly.",
        )

    monkeypatch.setattr(settings, "ws_require_origin", False, raising=False)
    monkeypatch.setattr(ws_ticket_service, "consume_ticket", _raise_statement_timeout)

    with pytest.raises(WebSocketException) as exc_info:
        await get_ws_ticket_user(
            websocket=_build_websocket(ticket="a" * settings.ws_ticket_length),
            scope_type="me_a2a_agent",
            scope_id=uuid4(),
        )

    assert exc_info.value.code == status.WS_1013_TRY_AGAIN_LATER
    assert exc_info.value.reason == (
        "Ticket verification timed out; service busy, retry shortly."
        f" Retry in {DB_BUSY_RETRY_AFTER_SECONDS} seconds."
    )


@pytest.mark.asyncio
async def test_get_async_db_closes_session_even_if_dependency_cleanup_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    close_started = asyncio.Event()
    close_released = asyncio.Event()
    close_finished = asyncio.Event()

    class _FakeSession:
        async def close(self) -> None:
            close_started.set()
            await close_released.wait()
            close_finished.set()

    session = _FakeSession()
    monkeypatch.setattr(api_deps, "AsyncSessionLocal", lambda: session)

    dependency = api_deps.get_async_db()
    yielded = await dependency.__anext__()

    assert yielded is session

    close_task = asyncio.create_task(dependency.aclose())
    await asyncio.wait_for(close_started.wait(), timeout=1.0)
    close_task.cancel()

    close_released.set()
    with pytest.raises(asyncio.CancelledError):
        await close_task
    assert close_finished.is_set() is True
