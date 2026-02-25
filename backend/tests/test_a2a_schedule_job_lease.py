from app.core.config import settings
from app.services.a2a_schedule_job import _effective_run_lease_seconds


def test_effective_run_lease_seconds_clamps_to_invoke_timeout_plus_grace(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "a2a_schedule_task_invoke_timeout", 3600.0)
    monkeypatch.setattr(settings, "a2a_schedule_run_lease_seconds", 2400)
    monkeypatch.setattr(settings, "a2a_schedule_run_lease_grace_seconds", 120)

    assert _effective_run_lease_seconds() == 3720


def test_effective_run_lease_seconds_keeps_larger_configured_lease(monkeypatch) -> None:
    monkeypatch.setattr(settings, "a2a_schedule_task_invoke_timeout", 1800.0)
    monkeypatch.setattr(settings, "a2a_schedule_run_lease_seconds", 4000)
    monkeypatch.setattr(settings, "a2a_schedule_run_lease_grace_seconds", 120)

    assert _effective_run_lease_seconds() == 4000


def test_effective_run_lease_seconds_uses_ceil_for_fractional_invoke_timeout(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "a2a_schedule_task_invoke_timeout", 10.1)
    monkeypatch.setattr(settings, "a2a_schedule_run_lease_seconds", 5)
    monkeypatch.setattr(settings, "a2a_schedule_run_lease_grace_seconds", 0)

    assert _effective_run_lease_seconds() == 11
