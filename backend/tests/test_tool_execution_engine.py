from uuid import uuid4

from app.agents.services.tool_executor import ToolExecutionEngine


def make_engine():
    class DummyPolicy:
        def register_start(self, *args, **kwargs):
            pass

        def register_finish(self, *args, **kwargs):
            pass

        def should_execute(self, *args, **kwargs):
            return True, None

    return ToolExecutionEngine(tool_policy=DummyPolicy())


def test_sanitize_tool_runs_removes_private_keys():
    run = {
        "tool_call_id": "abc",
        "tool_name": "demo",
        "status": "started",
        "message": "hi",
        "_started_ts": 1.23,
    }

    sanitized = ToolExecutionEngine.sanitize_tool_runs([run])

    assert sanitized == [
        {
            "tool_call_id": "abc",
            "tool_name": "demo",
            "status": "started",
            "message": "hi",
        }
    ]


def test_complete_tool_run_sets_finished_and_duration(monkeypatch):
    from datetime import datetime, timezone

    record = {"_started_ts": 1.0}

    fixed_now = datetime(2025, 10, 14, 0, 0, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(
        "app.agents.services.tool_executor.utc_now_iso",
        lambda: fixed_now.isoformat().replace("+00:00", "Z"),
    )
    monkeypatch.setattr(
        "app.agents.services.tool_executor.time.perf_counter", lambda: 5.0
    )

    ToolExecutionEngine._complete_tool_run(record)

    assert record["finished_at"] == "2025-10-14T00:00:00Z"
    assert record["duration_ms"] == 4000
    assert "_started_ts" not in record


def test_create_tool_run_record_populates_fields():
    engine = make_engine()
    record = engine.create_tool_run_record(
        tool_call_id="abc",
        tool_name="demo",
        arguments={"foo": "bar"},
        sequence=2,
    )

    assert record["tool_call_id"] == "abc"
    assert record["sequence"] == 2
    assert record["status"] == "started"
    assert record["arguments"] == {"foo": "bar"}
    assert record["started_at"].startswith("20")
    assert record["run_id"] is not None


def test_create_tool_run_record_respects_run_id():
    engine = make_engine()
    explicit = uuid4()
    record = engine.create_tool_run_record(
        tool_call_id="abc",
        tool_name="demo",
        arguments={},
        sequence=1,
        run_id=explicit,
    )
    assert record["run_id"] == explicit


def test_compose_tool_failure_message_formats_entries():
    engine = make_engine()
    failures = [
        {"tool": "search", "reason": "timeout"},
        {"tool": "calendar", "reason": "bad input"},
    ]

    message = engine.compose_tool_failure_message(failures)

    assert "search" in message and "timeout" in message
    assert "calendar" in message and "bad input" in message
