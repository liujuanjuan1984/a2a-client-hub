from app.core.config import settings
from app.services import a2a_schedule_job
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


def test_effective_run_lease_seconds_logs_clamp_warning_once_for_same_values(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "a2a_schedule_task_invoke_timeout", 3600.0)
    monkeypatch.setattr(settings, "a2a_schedule_run_lease_seconds", 2400)
    monkeypatch.setattr(settings, "a2a_schedule_run_lease_grace_seconds", 120)
    monkeypatch.setattr(
        a2a_schedule_job,
        "_last_clamped_lease_warning_key",
        None,
        raising=False,
    )
    warning_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def _capture_warning(*args, **kwargs) -> None:
        warning_calls.append((args, kwargs))

    monkeypatch.setattr(a2a_schedule_job.logger, "warning", _capture_warning)

    assert _effective_run_lease_seconds() == 3720
    assert _effective_run_lease_seconds() == 3720
    assert len(warning_calls) == 1


def test_effective_run_lease_seconds_resets_warning_state_after_recovery(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "a2a_schedule_task_invoke_timeout", 3600.0)
    monkeypatch.setattr(settings, "a2a_schedule_run_lease_grace_seconds", 120)
    monkeypatch.setattr(
        a2a_schedule_job,
        "_last_clamped_lease_warning_key",
        None,
        raising=False,
    )
    warning_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def _capture_warning(*args, **kwargs) -> None:
        warning_calls.append((args, kwargs))

    monkeypatch.setattr(a2a_schedule_job.logger, "warning", _capture_warning)

    monkeypatch.setattr(settings, "a2a_schedule_run_lease_seconds", 2400)
    assert _effective_run_lease_seconds() == 3720

    monkeypatch.setattr(settings, "a2a_schedule_run_lease_seconds", 4000)
    assert _effective_run_lease_seconds() == 4000

    monkeypatch.setattr(settings, "a2a_schedule_run_lease_seconds", 2400)
    assert _effective_run_lease_seconds() == 3720
    assert len(warning_calls) == 2
