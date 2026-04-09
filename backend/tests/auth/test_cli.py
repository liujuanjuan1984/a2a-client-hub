from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.cli import run_cli
from app.db.models.a2a_schedule_task import A2AScheduleTask
from tests.support.utils import (
    DEFAULT_TEST_PASSWORD,
    create_a2a_agent,
    create_conversation_thread,
    create_schedule_task,
    create_user,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_cli_login_whoami_and_logout(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    user = await create_user(async_db_session, password=DEFAULT_TEST_PASSWORD)
    session_file = tmp_path / "cli-session.json"
    monkeypatch.setenv("A2A_CLIENT_HUB_CLI_SESSION_FILE", str(session_file))

    login_exit_code = await run_cli(
        [
            "login",
            "--email",
            user.email,
            "--password",
            DEFAULT_TEST_PASSWORD,
        ]
    )
    login_output = json.loads(capsys.readouterr().out)

    assert login_exit_code == 0
    assert login_output["user"]["email"] == user.email
    assert session_file.exists()

    whoami_exit_code = await run_cli(["whoami"])
    whoami_output = json.loads(capsys.readouterr().out)

    assert whoami_exit_code == 0
    assert whoami_output["user"]["email"] == user.email
    assert whoami_output["session_file"] == str(session_file)

    logout_exit_code = await run_cli(["logout"])
    logout_output = json.loads(capsys.readouterr().out)

    assert logout_exit_code == 0
    assert logout_output["message"] == "CLI session cleared."
    assert not session_file.exists()


async def test_cli_requires_login_for_job_commands(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(
        "A2A_CLIENT_HUB_CLI_SESSION_FILE",
        str(tmp_path / "missing-session.json"),
    )

    exit_code = await run_cli(["jobs", "list"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Run `a2a-client-hub login` first." in captured.err


async def test_cli_write_commands_require_explicit_confirmation_in_non_tty_mode(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    user = await create_user(async_db_session, password=DEFAULT_TEST_PASSWORD)
    agent = await create_a2a_agent(
        async_db_session, user_id=user.id, suffix="cli-confirm"
    )
    task = await create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
    )
    monkeypatch.setenv(
        "A2A_CLIENT_HUB_CLI_SESSION_FILE",
        str(tmp_path / "cli-session.json"),
    )

    assert (
        await run_cli(
            [
                "login",
                "--email",
                user.email,
                "--password",
                DEFAULT_TEST_PASSWORD,
            ]
        )
        == 0
    )
    capsys.readouterr()

    exit_code = await run_cli(["jobs", "pause", str(task.id)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "requires explicit confirmation" in captured.err


async def test_cli_jobs_commands_use_shared_gateway_and_jobs_service(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    user = await create_user(async_db_session, password=DEFAULT_TEST_PASSWORD)
    agent = await create_a2a_agent(async_db_session, user_id=user.id, suffix="cli")
    task = await create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
        prompt="initial prompt",
    )
    session_file = tmp_path / "cli-session.json"
    monkeypatch.setenv("A2A_CLIENT_HUB_CLI_SESSION_FILE", str(session_file))

    assert (
        await run_cli(
            [
                "login",
                "--email",
                user.email,
                "--password",
                DEFAULT_TEST_PASSWORD,
            ]
        )
        == 0
    )
    capsys.readouterr()

    list_exit_code = await run_cli(["jobs", "list", "--page", "1", "--size", "20"])
    list_output = json.loads(capsys.readouterr().out)

    assert list_exit_code == 0
    assert list_output["total"] >= 1
    assert any(item["id"] == str(task.id) for item in list_output["items"])

    get_exit_code = await run_cli(["jobs", "get", str(task.id)])
    get_output = json.loads(capsys.readouterr().out)

    assert get_exit_code == 0
    assert get_output["job"]["id"] == str(task.id)
    assert get_output["job"]["prompt"] == "initial prompt"

    pause_exit_code = await run_cli(["jobs", "pause", str(task.id), "--confirm"])
    pause_output = json.loads(capsys.readouterr().out)

    assert pause_exit_code == 0
    assert pause_output["job"]["enabled"] is False

    resume_exit_code = await run_cli(["jobs", "resume", str(task.id), "--confirm"])
    resume_output = json.loads(capsys.readouterr().out)

    assert resume_exit_code == 0
    assert resume_output["job"]["enabled"] is True

    update_prompt_exit_code = await run_cli(
        [
            "jobs",
            "update-prompt",
            str(task.id),
            "--prompt",
            "cli updated prompt",
            "--confirm",
        ]
    )
    update_prompt_output = json.loads(capsys.readouterr().out)

    assert update_prompt_exit_code == 0
    assert update_prompt_output["job"]["prompt"] == "cli updated prompt"

    update_schedule_exit_code = await run_cli(
        [
            "jobs",
            "update-schedule",
            str(task.id),
            "--cycle-type",
            "daily",
            "--time-point-json",
            '{"time": "14:45"}',
            "--schedule-timezone",
            "UTC",
            "--confirm",
        ]
    )
    update_schedule_output = json.loads(capsys.readouterr().out)

    assert update_schedule_exit_code == 0
    assert update_schedule_output["job"]["time_point"]["time"] == "14:45"

    refreshed = (
        await async_db_session.execute(
            select(A2AScheduleTask).where(A2AScheduleTask.id == task.id)
        )
    ).scalar_one()
    await async_db_session.refresh(refreshed)

    assert refreshed.prompt == "cli updated prompt"
    assert refreshed.enabled is True
    assert refreshed.time_point["time"] == "14:45"


async def test_cli_update_schedule_validates_payload_shape(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    user = await create_user(async_db_session, password=DEFAULT_TEST_PASSWORD)
    agent = await create_a2a_agent(
        async_db_session, user_id=user.id, suffix="cli-schedule-validate"
    )
    task = await create_schedule_task(
        async_db_session,
        user_id=user.id,
        agent_id=agent.id,
    )
    monkeypatch.setenv(
        "A2A_CLIENT_HUB_CLI_SESSION_FILE",
        str(tmp_path / "cli-session.json"),
    )

    assert (
        await run_cli(
            [
                "login",
                "--email",
                user.email,
                "--password",
                DEFAULT_TEST_PASSWORD,
            ]
        )
        == 0
    )
    capsys.readouterr()

    missing_fields_exit_code = await run_cli(
        ["jobs", "update-schedule", str(task.id), "--confirm"]
    )
    missing_fields_output = capsys.readouterr()

    assert missing_fields_exit_code == 1
    assert "requires at least one schedule field to change" in missing_fields_output.err

    invalid_json_exit_code = await run_cli(
        [
            "jobs",
            "update-schedule",
            str(task.id),
            "--time-point-json",
            "not-json",
            "--confirm",
        ]
    )
    invalid_json_output = capsys.readouterr()

    assert invalid_json_exit_code == 1
    assert "must be valid JSON object text" in invalid_json_output.err


async def test_cli_sessions_commands_use_shared_gateway_and_sessions_service(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    user = await create_user(async_db_session, password=DEFAULT_TEST_PASSWORD)
    manual_thread = await create_conversation_thread(
        async_db_session,
        user_id=user.id,
        title="CLI Manual Session",
    )
    scheduled_thread = await create_conversation_thread(
        async_db_session,
        user_id=user.id,
        source="scheduled",
        title="CLI Scheduled Session",
    )
    monkeypatch.setenv(
        "A2A_CLIENT_HUB_CLI_SESSION_FILE",
        str(tmp_path / "cli-session.json"),
    )

    assert (
        await run_cli(
            [
                "login",
                "--email",
                user.email,
                "--password",
                DEFAULT_TEST_PASSWORD,
            ]
        )
        == 0
    )
    capsys.readouterr()

    list_exit_code = await run_cli(
        ["sessions", "list", "--page", "1", "--size", "20", "--source", "manual"]
    )
    list_output = json.loads(capsys.readouterr().out)

    assert list_exit_code == 0
    assert list_output["pagination"]["total"] >= 1
    returned_ids = {item["conversation_id"] for item in list_output["items"]}
    assert str(manual_thread.id) in returned_ids
    assert str(scheduled_thread.id) not in returned_ids

    get_exit_code = await run_cli(["sessions", "get", str(scheduled_thread.id)])
    get_output = json.loads(capsys.readouterr().out)

    assert get_exit_code == 0
    assert get_output["session"]["conversation_id"] == str(scheduled_thread.id)
    assert get_output["session"]["source"] == "scheduled"
    assert get_output["session"]["title"] == "CLI Scheduled Session"


async def test_cli_agents_commands_use_shared_gateway_and_agents_service(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    user = await create_user(async_db_session, password=DEFAULT_TEST_PASSWORD)
    first = await create_a2a_agent(
        async_db_session,
        user_id=user.id,
        suffix="cli-agent-a",
        tags=["alpha"],
    )
    second = await create_a2a_agent(
        async_db_session,
        user_id=user.id,
        suffix="cli-agent-b",
    )
    monkeypatch.setenv(
        "A2A_CLIENT_HUB_CLI_SESSION_FILE",
        str(tmp_path / "cli-session.json"),
    )

    assert (
        await run_cli(
            [
                "login",
                "--email",
                user.email,
                "--password",
                DEFAULT_TEST_PASSWORD,
            ]
        )
        == 0
    )
    capsys.readouterr()

    list_exit_code = await run_cli(
        ["agents", "list", "--page", "1", "--size", "20", "--health-bucket", "all"]
    )
    list_output = json.loads(capsys.readouterr().out)

    assert list_exit_code == 0
    returned_ids = {item["id"] for item in list_output["items"]}
    assert str(first.id) in returned_ids
    assert str(second.id) in returned_ids

    get_exit_code = await run_cli(["agents", "get", str(first.id)])
    get_output = json.loads(capsys.readouterr().out)

    assert get_exit_code == 0
    assert get_output["agent"]["id"] == str(first.id)
    assert get_output["agent"]["tags"] == ["alpha"]

    update_exit_code = await run_cli(
        [
            "agents",
            "update-config",
            str(first.id),
            "--name",
            "CLI Updated Agent",
            "--enabled",
            "false",
            "--tags-json",
            '["cli","updated"]',
            "--extra-headers-json",
            '{"X-Test":"1"}',
            "--invoke-metadata-defaults-json",
            '{"model":"gpt-5"}',
            "--confirm",
        ]
    )
    update_output = json.loads(capsys.readouterr().out)

    assert update_exit_code == 0
    assert update_output["agent"]["name"] == "CLI Updated Agent"
    assert update_output["agent"]["enabled"] is False
    assert update_output["agent"]["tags"] == ["cli", "updated"]
    assert update_output["agent"]["extra_headers"] == {"X-Test": "1"}
    assert update_output["agent"]["invoke_metadata_defaults"] == {"model": "gpt-5"}


async def test_cli_agent_update_config_validates_payload_shape(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    user = await create_user(async_db_session, password=DEFAULT_TEST_PASSWORD)
    record = await create_a2a_agent(
        async_db_session,
        user_id=user.id,
        suffix="cli-agent-validate",
    )
    monkeypatch.setenv(
        "A2A_CLIENT_HUB_CLI_SESSION_FILE",
        str(tmp_path / "cli-session.json"),
    )

    assert (
        await run_cli(
            [
                "login",
                "--email",
                user.email,
                "--password",
                DEFAULT_TEST_PASSWORD,
            ]
        )
        == 0
    )
    capsys.readouterr()

    missing_fields_exit_code = await run_cli(
        ["agents", "update-config", str(record.id), "--confirm"]
    )
    missing_fields_output = capsys.readouterr()

    assert missing_fields_exit_code == 1
    assert (
        "requires at least one supported config field to change"
        in missing_fields_output.err
    )

    invalid_tags_exit_code = await run_cli(
        [
            "agents",
            "update-config",
            str(record.id),
            "--tags-json",
            '{"bad":"shape"}',
            "--confirm",
        ]
    )
    invalid_tags_output = capsys.readouterr()

    assert invalid_tags_exit_code == 1
    assert "must be valid JSON array text" not in invalid_tags_output.err
    assert "`--tags-json` must decode to a JSON array." in invalid_tags_output.err
