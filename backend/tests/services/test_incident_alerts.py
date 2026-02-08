from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.db.models.agent_message import AgentMessage
from app.services import incident_alerts


class DummyAsyncContext:
    def __init__(self) -> None:
        self.obj = SimpleNamespace()

    async def __aenter__(self):
        return self.obj

    async def __aexit__(self, _exc_type, _exc, _tb) -> None:
        return False


@pytest.fixture(autouse=True)
def reset_incident_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(incident_alerts, "_INCIDENT_CACHE", {})


@pytest.mark.asyncio
async def test_notify_admins_of_incident_dispatches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin_ids = [uuid4()]
    captured = []

    monkeypatch.setattr(
        incident_alerts,
        "AsyncSessionLocal",
        lambda: DummyAsyncContext(),
    )

    async def fake_list(_db):
        return admin_ids

    monkeypatch.setattr(incident_alerts, "_list_admin_user_ids", fake_list)
    monkeypatch.setattr(incident_alerts, "_now", lambda: 100.0)

    async def fake_send_notification(
        db, *, user_ids, body, title, severity, metadata, sync_cardbox
    ):
        captured.append(
            {
                "user_ids": user_ids,
                "body": body,
                "title": title,
                "severity": severity,
                "metadata": metadata,
                "sync_cardbox": sync_cardbox,
            }
        )

    monkeypatch.setattr(incident_alerts, "send_notification", fake_send_notification)

    sent = await incident_alerts.notify_admins_of_incident(
        "test-incident",
        "Test Incident",
        "Something happened.",
    )

    assert sent is True
    assert len(captured) == 1
    assert captured[0]["user_ids"] == admin_ids


@pytest.mark.asyncio
async def test_notify_admins_of_incident_dedupes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin_ids = [uuid4()]
    call_count = 0

    monkeypatch.setattr(
        incident_alerts,
        "AsyncSessionLocal",
        lambda: DummyAsyncContext(),
    )

    async def fake_list(_db):
        return admin_ids

    monkeypatch.setattr(incident_alerts, "_list_admin_user_ids", fake_list)

    current_time = {"value": 100.0}

    def fake_now() -> float:
        return current_time["value"]

    monkeypatch.setattr(incident_alerts, "_now", fake_now)

    async def fake_send_notification(*args, **kwargs):
        nonlocal call_count
        call_count += 1

    monkeypatch.setattr(incident_alerts, "send_notification", fake_send_notification)

    assert await incident_alerts.notify_admins_of_incident(
        "test-incident",
        "Test Incident",
        "Something happened.",
    )
    assert call_count == 1

    # Within the dedupe window: no new notification.
    current_time["value"] += 150.0
    assert (
        await incident_alerts.notify_admins_of_incident(
            "test-incident",
            "Test Incident",
            "Something happened.",
        )
        is False
    )
    assert call_count == 1

    # After the dedupe window: notification is sent again.
    current_time["value"] += 600.0
    assert await incident_alerts.notify_admins_of_incident(
        "test-incident",
        "Test Incident",
        "Something happened.",
    )
    assert call_count == 2


@pytest.mark.asyncio
async def test_report_llm_failure_uses_classification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}

    async def fake_notify(
        incident_key,
        title,
        body,
        *,
        severity,
        metadata,
        dedupe_seconds,
    ):
        captured.update(
            {
                "incident_key": incident_key,
                "title": title,
                "body": body,
                "severity": severity,
                "metadata": metadata,
                "dedupe_seconds": dedupe_seconds,
            }
        )
        return True

    monkeypatch.setattr(incident_alerts, "notify_admins_of_incident", fake_notify)

    class FakeAuthError(Exception):
        pass

    monkeypatch.setattr(
        incident_alerts,
        "litellm_exceptions",
        SimpleNamespace(AuthenticationError=FakeAuthError),
    )

    await incident_alerts.report_llm_failure(
        "LiteLLM call",
        FakeAuthError("invalid key"),
        context={"model": "test-model", "tools_count": 2, "duration": 0.5},
        dedupe_seconds=60,
    )

    assert captured["incident_key"] == "llm-auth:test-model"
    assert captured["severity"] == AgentMessage.SEVERITY_CRITICAL
    assert captured["metadata"]["model"] == "test-model"
    assert captured["metadata"]["tools_count"] == 2
    assert "invalid key" in captured["body"]
