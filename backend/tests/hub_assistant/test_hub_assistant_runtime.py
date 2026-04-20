from __future__ import annotations

from tests.hub_assistant import hub_assistant_support as support
from tests.hub_assistant.hub_assistant_support import (
    UUID,
    AgentMessage,
    Any,
    HubAssistantFollowUpTaskRequest,
    HubAssistantUnavailableError,
    Path,
    _configure_swival_settings,
    _FakeSwivalSession,
    _install_fake_swival,
    _new_conversation_id,
    _reset_hub_assistant_runtime,
    cast,
    create_user,
    get_hub_assistant_allowed_operations,
    get_hub_assistant_conversation_id,
    hub_assistant_agent_service_module,
    hub_assistant_service,
    pytest,
    select,
    settings,
    sys,
    uuid4,
    verify_jwt_token_claims,
)

pytestmark = support.pytestmark


async def test_hub_assistant_profile_exposes_full_available_tool_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_hub_assistant_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)

    profile = hub_assistant_service.get_profile()

    assert profile.configured is True
    assert profile.resources == ("agents", "followups", "jobs", "sessions")
    assert [item.operation_id for item in profile.tool_definitions] == [
        "hub_assistant.agents.check_health",
        "hub_assistant.agents.check_health_all",
        "hub_assistant.agents.create",
        "hub_assistant.agents.delete",
        "hub_assistant.agents.get",
        "hub_assistant.agents.list",
        "hub_assistant.agents.start_sessions",
        "hub_assistant.agents.update_config",
        "hub_assistant.followups.get",
        "hub_assistant.followups.set_sessions",
        "hub_assistant.jobs.create",
        "hub_assistant.jobs.delete",
        "hub_assistant.jobs.get",
        "hub_assistant.jobs.list",
        "hub_assistant.jobs.pause",
        "hub_assistant.jobs.resume",
        "hub_assistant.jobs.update",
        "hub_assistant.jobs.update_prompt",
        "hub_assistant.jobs.update_schedule",
        "hub_assistant.sessions.archive",
        "hub_assistant.sessions.get",
        "hub_assistant.sessions.get_latest_messages",
        "hub_assistant.sessions.list",
        "hub_assistant.sessions.send_message",
        "hub_assistant.sessions.unarchive",
        "hub_assistant.sessions.update",
    ]


async def test_hub_assistant_profile_reports_unconfigured_without_importable_swival(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_hub_assistant_runtime()
    _configure_swival_settings(monkeypatch)
    monkeypatch.setattr(
        hub_assistant_service,
        "_is_swival_importable",
        lambda: False,
    )

    profile = hub_assistant_service.get_profile()

    assert profile.configured is False


async def test_hub_assistant_loads_swival_from_tool_installed_site_packages(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _reset_hub_assistant_runtime()
    _configure_swival_settings(monkeypatch)

    tool_root = tmp_path / "tool-runtime"
    executable = tool_root / "bin" / "swival"
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    executable.chmod(0o755)

    site_packages = tool_root / "lib" / "python3.13" / "site-packages"
    package_dir = site_packages / "swival"
    package_dir.mkdir(parents=True)
    package_dir.joinpath("__init__.py").write_text(
        "class Session:\n"
        "    def __init__(self, **kwargs):\n"
        "        self.kwargs = kwargs\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        settings,
        "hub_assistant_swival_tool_executable",
        str(executable),
    )
    monkeypatch.delitem(sys.modules, "swival", raising=False)

    session_cls = hub_assistant_service._load_swival_session_cls()

    assert session_cls.__name__ == "Session"
    assert str(site_packages.resolve()) in sys.path


async def test_hub_assistant_run_uses_swival_with_authenticated_mcp_server(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _reset_hub_assistant_runtime()
    _configure_swival_settings(monkeypatch)
    monkeypatch.setattr(
        settings,
        "hub_assistant_swival_runtime_root",
        str(tmp_path / "swival-runtime"),
    )
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()

    result = await hub_assistant_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="List my jobs",
        allow_write_tools=False,
    )

    assert result.answer == "Hub Assistant reply"
    assert result.status == "completed"
    assert result.exhausted is False
    assert result.runtime == "swival"
    assert result.resources == ("agents", "followups", "jobs", "sessions")
    assert result.tool_names == (
        "hub_assistant.agents.get",
        "hub_assistant.agents.list",
        "hub_assistant.followups.get",
        "hub_assistant.followups.set_sessions",
        "hub_assistant.jobs.get",
        "hub_assistant.jobs.list",
        "hub_assistant.sessions.get",
        "hub_assistant.sessions.get_latest_messages",
        "hub_assistant.sessions.list",
    )
    assert result.write_tools_enabled is False
    assert result.interrupt is None
    assert _FakeSwivalSession.last_message == "List my jobs"
    assert _FakeSwivalSession.ask_call_count == 1
    assert _FakeSwivalSession.last_init_kwargs is not None
    assert _FakeSwivalSession.last_init_kwargs["provider"] == "openai"
    assert _FakeSwivalSession.last_init_kwargs["model"] == "gpt-test"
    assert _FakeSwivalSession.last_init_kwargs["base_url"] == "https://example.com/v1"
    assert (
        _FakeSwivalSession.last_init_kwargs["api_key"]
        == "test-api-key"  # pragma: allowlist secret
    )
    assert _FakeSwivalSession.last_init_kwargs["reasoning_effort"] == "medium"
    assert _FakeSwivalSession.last_init_kwargs["max_turns"] == 6
    assert _FakeSwivalSession.last_init_kwargs["max_output_tokens"] == 2048
    assert _FakeSwivalSession.last_init_kwargs["files"] == "none"
    assert _FakeSwivalSession.last_init_kwargs["commands"] == "none"
    assert _FakeSwivalSession.last_init_kwargs["no_skills"] is True
    assert _FakeSwivalSession.last_init_kwargs["history"] is False
    assert _FakeSwivalSession.last_init_kwargs["memory"] is False
    assert _FakeSwivalSession.last_init_kwargs["base_dir"] == str(
        (tmp_path / "swival-runtime" / str(user.id)).resolve()
    )
    assert "You are the Hub Assistant for a2a-client-hub." in cast(
        str,
        _FakeSwivalSession.last_init_kwargs["system_prompt"],
    )
    assert "This run is read-only." in cast(
        str,
        _FakeSwivalSession.last_init_kwargs["system_prompt"],
    )
    assert "treat them as handoff operations" in cast(
        str,
        _FakeSwivalSession.last_init_kwargs["system_prompt"],
    )
    assert "inspect or manage their own agents, scheduled jobs, sessions" in cast(
        str,
        _FakeSwivalSession.last_init_kwargs["system_prompt"],
    )
    assert (
        "You do not need to wait inline for the target side's live transport"
        in cast(
            str,
            _FakeSwivalSession.last_init_kwargs["system_prompt"],
        )
    )
    assert "the host will resume you so you can read and continue processing" in cast(
        str,
        _FakeSwivalSession.last_init_kwargs["system_prompt"],
    )
    mcp_servers = cast(
        dict[str, dict[str, Any]],
        _FakeSwivalSession.last_init_kwargs["mcp_servers"],
    )
    server_config = mcp_servers["a2a-client-hub"]
    assert server_config["url"] == "http://internal-mcp/mcp/"
    auth_header = cast(str, server_config["headers"]["Authorization"])
    assert auth_header.startswith("Bearer ")
    raw_token = auth_header.split("Bearer ", 1)[1]
    claims = verify_jwt_token_claims(raw_token, expected_type="access")
    assert claims is not None
    assert claims.subject == str(user.id)
    assert get_hub_assistant_conversation_id(claims) == conversation_id
    assert get_hub_assistant_allowed_operations(claims) == frozenset(result.tool_names)


async def test_hub_assistant_can_resume_one_durable_follow_up_run(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_hub_assistant_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    request = HubAssistantFollowUpTaskRequest(
        task_id=uuid4(),
        user_id=cast(UUID, user.id),
        hub_assistant_conversation_id=_new_conversation_id(),
        tracked_conversation_ids=("tracked-session-1", "tracked-session-2"),
        previous_target_agent_message_anchors={
            "tracked-session-1": {
                "message_id": "agent-msg-1",
                "updated_at": "2026-04-16T12:00:00+00:00",
                "status": "done",
            },
        },
        observed_target_agent_message_anchors={
            "tracked-session-1": {
                "message_id": "agent-msg-2",
                "updated_at": "2026-04-16T12:05:00+00:00",
                "status": "done",
            },
            "tracked-session-2": {
                "message_id": "agent-msg-9",
                "updated_at": "2026-04-16T12:06:00+00:00",
                "status": "streaming",
            },
        },
        changed_conversation_ids=("tracked-session-1",),
    )

    result = await hub_assistant_service.run_durable_follow_up(
        db=async_db_session,
        current_user=user,
        request=request,
    )
    await async_db_session.commit()

    assert result.status == "completed"
    assert result.write_tools_enabled is False
    assert _FakeSwivalSession.last_message is not None
    assert "System follow-up wakeup" in _FakeSwivalSession.last_message
    assert "tracked-session-1" in _FakeSwivalSession.last_message
    assert "hub_assistant.followups.get" in _FakeSwivalSession.last_message

    persisted = await async_db_session.scalar(
        select(AgentMessage).where(
            AgentMessage.user_id == user.id,
            AgentMessage.sender == "agent",
            AgentMessage.message_metadata["message_kind"].astext
            == "durable_follow_up_summary",
        )
    )
    assert persisted is not None
    assert persisted.status == "done"


async def test_hub_assistant_rebuilds_session_when_delegated_token_expires(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_hub_assistant_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    monkeypatch.setattr(settings, "jwt_access_token_ttl_seconds", 5)
    monkeypatch.setattr(settings, "hub_assistant_swival_delegated_token_ttl_seconds", 5)
    monotonic_time = {"value": 100.0}
    monkeypatch.setattr(
        hub_assistant_agent_service_module.time,
        "monotonic",
        lambda: monotonic_time["value"],
    )
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()

    first = await hub_assistant_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="List my jobs",
        allow_write_tools=False,
    )
    assert first.answer == "Hub Assistant reply"
    assert _FakeSwivalSession.instance_count == 1

    monotonic_time["value"] += 10.0
    _FakeSwivalSession.next_answer = "Second Hub Assistant reply"
    second = await hub_assistant_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="List my agents",
        allow_write_tools=False,
    )

    assert second.answer == "Second Hub Assistant reply"
    assert _FakeSwivalSession.instance_count == 2
    assert _FakeSwivalSession.instances[0].closed is True
    assert _FakeSwivalSession.instances[1]._conv_state is not None
    transferred_messages = cast(
        list[dict[str, str]], _FakeSwivalSession.instances[1]._conv_state["messages"]
    )
    assert transferred_messages[0]["role"] == "system"
    assert cast(
        list[dict[str, str]], _FakeSwivalSession.instances[1]._conv_state["messages"]
    )[1:3] == [
        {"role": "user", "content": "List my jobs"},
        {"role": "assistant", "content": "Hub Assistant reply"},
    ]


async def test_hub_assistant_raises_when_mcp_runtime_returns_transport_error(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_hub_assistant_runtime()
    _configure_swival_settings(monkeypatch)
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)

    _FakeSwivalSession.next_answer = "Backend appears unavailable."
    _FakeSwivalSession.next_messages = [
        {"role": "user", "content": "List my agents"},
        {
            "role": "tool",
            "content": (
                "error: MCP server 'a2a-client-hub' failed: "
                "Client error '401 Unauthorized'"
            ),
        },
        {"role": "assistant", "content": "Backend appears unavailable."},
    ]

    with pytest.raises(HubAssistantUnavailableError) as excinfo:
        await hub_assistant_service.run(
            db=async_db_session,
            current_user=user,
            conversation_id=_new_conversation_id(),
            message="List my agents",
            allow_write_tools=False,
        )

    assert "MCP call failed" in str(excinfo.value)
    assert "401 Unauthorized" in str(excinfo.value)


async def test_hub_assistant_reuses_same_swival_base_dir_for_same_user(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _reset_hub_assistant_runtime()
    _configure_swival_settings(monkeypatch)
    monkeypatch.setattr(
        settings,
        "hub_assistant_swival_runtime_root",
        str(tmp_path / "swival-runtime"),
    )
    user = await create_user(async_db_session)

    first_dir = hub_assistant_service._resolve_swival_base_dir(user)
    second_dir = hub_assistant_service._resolve_swival_base_dir(user)

    assert first_dir == second_dir
    assert first_dir == str((tmp_path / "swival-runtime" / str(user.id)).resolve())


async def test_hub_assistant_uses_distinct_swival_base_dirs_per_user(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _reset_hub_assistant_runtime()
    _configure_swival_settings(monkeypatch)
    monkeypatch.setattr(
        settings,
        "hub_assistant_swival_runtime_root",
        str(tmp_path / "swival-runtime"),
    )
    first_user = await create_user(async_db_session)
    second_user = await create_user(async_db_session)

    first_dir = hub_assistant_service._resolve_swival_base_dir(first_user)
    second_dir = hub_assistant_service._resolve_swival_base_dir(second_user)

    assert first_dir != second_dir
    assert first_dir.endswith(str(first_user.id))
    assert second_dir.endswith(str(second_user.id))


async def test_hub_assistant_write_approved_run_uses_write_enabled_mcp_surface(
    async_db_session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _reset_hub_assistant_runtime()
    _configure_swival_settings(monkeypatch)
    monkeypatch.setattr(
        settings,
        "hub_assistant_swival_runtime_root",
        str(tmp_path / "swival-runtime"),
    )
    _install_fake_swival(monkeypatch)
    user = await create_user(async_db_session)
    conversation_id = _new_conversation_id()

    result = await hub_assistant_service.run(
        db=async_db_session,
        current_user=user,
        conversation_id=conversation_id,
        message="Pause my job",
        allow_write_tools=True,
    )

    assert result.tool_names == (
        "hub_assistant.agents.check_health",
        "hub_assistant.agents.check_health_all",
        "hub_assistant.agents.create",
        "hub_assistant.agents.delete",
        "hub_assistant.agents.get",
        "hub_assistant.agents.list",
        "hub_assistant.agents.start_sessions",
        "hub_assistant.agents.update_config",
        "hub_assistant.followups.get",
        "hub_assistant.followups.set_sessions",
        "hub_assistant.jobs.create",
        "hub_assistant.jobs.delete",
        "hub_assistant.jobs.get",
        "hub_assistant.jobs.list",
        "hub_assistant.jobs.pause",
        "hub_assistant.jobs.resume",
        "hub_assistant.jobs.update",
        "hub_assistant.jobs.update_prompt",
        "hub_assistant.jobs.update_schedule",
        "hub_assistant.sessions.archive",
        "hub_assistant.sessions.get",
        "hub_assistant.sessions.get_latest_messages",
        "hub_assistant.sessions.list",
        "hub_assistant.sessions.send_message",
        "hub_assistant.sessions.unarchive",
        "hub_assistant.sessions.update",
    )
    assert result.status == "completed"
    assert result.write_tools_enabled is True
    assert _FakeSwivalSession.last_init_kwargs is not None
    assert _FakeSwivalSession.last_init_kwargs["mcp_servers"]["a2a-client-hub"][
        "url"
    ] == ("http://internal-mcp/mcp-write/")
    assert "explicitly approved write tools" in cast(
        str,
        _FakeSwivalSession.last_init_kwargs["system_prompt"],
    )
