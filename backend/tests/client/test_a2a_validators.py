import pytest

from app.integrations.a2a_client import validators


@pytest.fixture
def valid_card_data():
    return {
        "name": "Test Agent",
        "description": "An agent for testing.",
        "version": "1.0.0",
        "supportedInterfaces": [
            {
                "url": "https://example.com/agent",
                "protocolBinding": "JSONRPC",
            }
        ],
        "capabilities": {"streaming": True},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [{"name": "test_skill"}],
    }


class TestValidateAgentCard:
    def test_valid_card(self, valid_card_data):
        result = validators.validate_agent_card(valid_card_data)
        assert not result.errors
        assert not result.warnings

    @pytest.mark.parametrize(
        "missing_field",
        [
            "name",
            "description",
            "version",
            "supportedInterfaces",
            "capabilities",
            "defaultInputModes",
            "defaultOutputModes",
            "skills",
        ],
    )
    def test_missing_required_field(self, valid_card_data, missing_field):
        card_data = valid_card_data.copy()
        del card_data[missing_field]
        result = validators.validate_agent_card(card_data)
        assert f"Required field is missing: '{missing_field}'." in result.errors

    @pytest.mark.parametrize(
        "invalid_url",
        ["ftp://invalid-url.com", "example.com", "/relative/path"],
    )
    def test_invalid_url(self, valid_card_data, invalid_url):
        card_data = valid_card_data.copy()
        card_data["supportedInterfaces"] = [
            {
                "url": invalid_url,
                "protocolBinding": "JSONRPC",
            }
        ]
        result = validators.validate_agent_card(card_data)
        assert (
            "Each supported interface must declare an absolute 'url'." in result.errors
        )

    def test_invalid_capabilities_type(self, valid_card_data):
        card_data = valid_card_data.copy()
        card_data["capabilities"] = "not-an-object"
        result = validators.validate_agent_card(card_data)
        assert "Field 'capabilities' must be an object." in result.errors

    @pytest.mark.parametrize("field", ["defaultInputModes", "defaultOutputModes"])
    def test_invalid_modes_type_not_array(self, valid_card_data, field):
        card_data = valid_card_data.copy()
        card_data[field] = "not-a-list"
        result = validators.validate_agent_card(card_data)
        assert f"Field '{field}' must be an array of strings." in result.errors

    @pytest.mark.parametrize("field", ["defaultInputModes", "defaultOutputModes"])
    def test_invalid_modes_type_item_not_string(self, valid_card_data, field):
        card_data = valid_card_data.copy()
        card_data[field] = [123, "string"]
        result = validators.validate_agent_card(card_data)
        assert f"All items in '{field}' must be strings." in result.errors

    def test_invalid_skills_type(self, valid_card_data):
        card_data = valid_card_data.copy()
        card_data["skills"] = "not-a-list"
        result = validators.validate_agent_card(card_data)
        assert "Field 'skills' must be an array of AgentSkill objects." in result.errors

    def test_empty_skills_array(self, valid_card_data):
        card_data = valid_card_data.copy()
        card_data["skills"] = []
        result = validators.validate_agent_card(card_data)
        assert not result.errors
        assert (
            "Field 'skills' array is empty. Agent must have at least one skill if it performs actions."
            in result.warnings
        )

    def test_rejects_legacy_agent_card_url_field(self, valid_card_data):
        card_data = valid_card_data.copy()
        card_data["url"] = "https://example.com/legacy"
        result = validators.validate_agent_card(card_data)
        assert (
            "Legacy field 'url' is not supported in A2A 1.0; use "
            "'supportedInterfaces' instead." in result.errors
        )

    def test_rejects_legacy_capability_modes(self, valid_card_data):
        card_data = valid_card_data.copy()
        card_data["capabilities"] = {
            "streaming": True,
            "inputModes": ["text/plain"],
        }
        result = validators.validate_agent_card(card_data)
        assert (
            "Legacy field 'capabilities.inputModes' is not supported in A2A 1.0; "
            "use 'defaultInputModes' or per-skill 'inputModes' instead."
            in result.errors
        )

    def test_rejects_unsupported_protocol_binding(self, valid_card_data):
        card_data = valid_card_data.copy()
        card_data["supportedInterfaces"] = [
            {
                "url": "https://example.com/agent",
                "protocolBinding": "WEBSOCKET",
            }
        ]
        result = validators.validate_agent_card(card_data)
        assert (
            "Each supported interface must declare a supported "
            "'protocolBinding' (JSONRPC, HTTP+JSON, GRPC)." in result.errors
        )

    def test_rejects_legacy_protocol_version(self, valid_card_data):
        card_data = valid_card_data.copy()
        card_data["supportedInterfaces"] = [
            {
                "url": "https://example.com/agent",
                "protocolBinding": "JSONRPC",
                "protocolVersion": "0.3.0",
            }
        ]
        result = validators.validate_agent_card(card_data)
        assert (
            "Legacy A2A protocolVersion '0.3' is not supported; "
            "upgrade the peer to A2A 1.0." in result.errors
        )


class TestValidateMessage:
    def test_missing_stream_response_field(self):
        errors = validators.validate_message({})
        assert (
            "Response from agent must be a canonical A2A 1.0 StreamResponse payload."
            in errors
        )

    def test_multiple_stream_response_fields(self):
        errors = validators.validate_message(
            {
                "message": {"parts": [{"text": "hello"}], "role": "ROLE_AGENT"},
                "statusUpdate": {"status": {"state": "TASK_STATE_WORKING"}},
            }
        )
        assert (
            "StreamResponse payload must set exactly one of 'task', 'message', "
            "'statusUpdate', or 'artifactUpdate'." in errors
        )

    def test_valid_task(self):
        data = {"task": {"id": "123", "status": {"state": "TASK_STATE_WORKING"}}}
        errors = validators.validate_message(data)
        assert not errors

    def test_task_missing_id(self):
        data = {"task": {"status": {"state": "TASK_STATE_WORKING"}}}
        errors = validators.validate_message(data)
        assert "Task object missing required field: 'id'." in errors

    def test_task_missing_status(self):
        data = {"task": {"id": "123"}}
        errors = validators.validate_message(data)
        assert "Task object missing required field: 'status.state'." in errors

    def test_task_rejects_legacy_state_value(self):
        data = {"task": {"id": "123", "status": {"state": "running"}}}
        errors = validators.validate_message(data)
        assert (
            "Task object must use canonical A2A 1.0 task states (TASK_STATE_*)."
            in errors
        )

    def test_valid_status_update(self):
        data = {"statusUpdate": {"status": {"state": "TASK_STATE_WORKING"}}}
        errors = validators.validate_message(data)
        assert not errors

    def test_status_update_missing_status(self):
        data = {"statusUpdate": {}}
        errors = validators.validate_message(data)
        assert "StatusUpdate object missing required field: 'status.state'." in errors

    def test_status_update_rejects_legacy_state_value(self):
        data = {"statusUpdate": {"status": {"state": "thinking"}}}
        errors = validators.validate_message(data)
        assert (
            "StatusUpdate object must use canonical A2A 1.0 task states "
            "(TASK_STATE_*)." in errors
        )

    def test_valid_artifact_update(self):
        data = {
            "artifactUpdate": {
                "artifact": {"parts": [{"text": "result"}]},
                "metadata": {
                    "shared": {
                        "stream": {
                            "messageId": "msg-1",
                            "eventId": "evt-1",
                            "seq": 1,
                        }
                    }
                },
            }
        }
        errors = validators.validate_message(data)
        assert not errors

    def test_valid_artifact_update_with_identity_in_artifact_metadata(self):
        data = {
            "artifactUpdate": {
                "artifact": {
                    "parts": [{"text": "result"}],
                    "metadata": {
                        "shared": {
                            "stream": {
                                "messageId": "msg-1",
                                "eventId": "evt-1",
                                "seq": 1,
                            }
                        }
                    },
                },
            }
        }
        errors = validators.validate_message(data)
        assert not errors

    def test_artifact_update_missing_artifact(self):
        data = {"artifactUpdate": {}}
        errors = validators.validate_message(data)
        assert "ArtifactUpdate object missing required field: 'artifact'." in errors

    @pytest.mark.parametrize(
        "parts_value",
        [None, "not-a-list", []],
        ids=["missing", "wrong_type", "empty"],
    )
    def test_artifact_update_invalid_parts(self, parts_value):
        data = {
            "artifactUpdate": {
                "metadata": {
                    "shared": {
                        "stream": {
                            "messageId": "msg-1",
                            "eventId": "evt-1",
                            "seq": 1,
                        }
                    }
                },
                "artifact": {},
            }
        }
        if parts_value is not None:
            data["artifactUpdate"]["artifact"]["parts"] = parts_value
        errors = validators.validate_message(data)
        assert "Artifact object must have a non-empty 'parts' array." in errors

    def test_artifact_update_missing_message_id_and_event_id_is_allowed(self):
        data = {
            "artifactUpdate": {
                "metadata": {"shared": {"stream": {"seq": 1}}},
                "artifact": {"parts": [{"text": "result"}]},
            }
        }
        errors = validators.validate_message(data)
        assert not errors

    def test_artifact_update_missing_seq_is_allowed(self):
        data = {
            "artifactUpdate": {
                "metadata": {
                    "shared": {
                        "stream": {
                            "messageId": "msg-1",
                            "eventId": "evt-1",
                        }
                    }
                },
                "artifact": {"parts": [{"text": "result"}]},
            }
        }
        errors = validators.validate_message(data)
        assert not errors

    def test_valid_message(self):
        data = {"message": {"parts": [{"text": "hello"}], "role": "ROLE_AGENT"}}
        errors = validators.validate_message(data)
        assert not errors

    @pytest.mark.parametrize(
        "parts_value",
        [None, "not-a-list", []],
        ids=["missing", "wrong_type", "empty"],
    )
    def test_message_invalid_parts(self, parts_value):
        data = {"message": {"role": "ROLE_AGENT"}}
        if parts_value is not None:
            data["message"]["parts"] = parts_value
        errors = validators.validate_message(data)
        assert "Message object must have a non-empty 'parts' array." in errors

    @pytest.mark.parametrize(
        "role_value",
        [None, "user", "system"],
        ids=["missing", "wrong_role_user", "wrong_role_system"],
    )
    def test_message_invalid_role(self, role_value):
        data = {"message": {"parts": [{"text": "hello"}]}}
        if role_value is not None:
            data["message"]["role"] = role_value
        errors = validators.validate_message(data)
        assert (
            "Message from agent must have canonical A2A 1.0 role 'ROLE_AGENT'."
            in errors
        )
