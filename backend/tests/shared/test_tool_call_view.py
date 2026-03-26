from app.features.invoke.tool_call_view import (
    build_tool_call_detail,
    build_tool_call_view,
)


def test_build_tool_call_view_uses_last_event_for_summary():
    raw_content = (
        '{"call_id":"call-1","tool":"bash","status":"pending","input":{}}'
        '{"call_id":"call-1","tool":"bash","status":"running",'
        '"input":{"command":"pwd","description":"Inspect repository state."}}'
        '{"call_id":"call-1","tool":"bash","status":"completed",'
        '"title":"Inspect repository state.","output":"main\\nclean"}'
    )

    assert build_tool_call_view(raw_content, is_finished=True) == {
        "name": "bash",
        "status": "success",
        "callId": "call-1",
        "arguments": {
            "command": "pwd",
            "description": "Inspect repository state.",
        },
        "result": "main\nclean",
        "error": None,
    }


def test_build_tool_call_detail_emits_timeline_and_raw_payload():
    raw_content = (
        '{"call_id":"call-1","tool":"bash","status":"pending","input":{}}'
        '{"call_id":"call-1","tool":"bash","status":"running",'
        '"input":{"command":"pwd","description":"Inspect repository state."}}'
        '{"call_id":"call-1","tool":"bash","status":"completed",'
        '"title":"Inspect repository state.","output":"main\\nclean"}'
    )

    assert build_tool_call_detail(raw_content, is_finished=True) == {
        "name": "bash",
        "status": "success",
        "callId": "call-1",
        "title": "Inspect repository state.",
        "arguments": {
            "command": "pwd",
            "description": "Inspect repository state.",
        },
        "result": "main\nclean",
        "error": None,
        "timeline": [
            {"status": "pending", "input": {}},
            {
                "status": "running",
                "title": "Inspect repository state.",
                "input": {
                    "command": "pwd",
                    "description": "Inspect repository state.",
                },
            },
            {
                "status": "completed",
                "title": "Inspect repository state.",
                "output": "main\nclean",
            },
        ],
        "raw": raw_content,
    }


def test_build_tool_call_view_treats_finished_running_status_as_success():
    raw_content = '{"call_id":"call-2","tool":"bash","status":"running","input":{}}'

    assert build_tool_call_view(raw_content, is_finished=True) == {
        "name": "bash",
        "status": "success",
        "callId": "call-2",
        "arguments": {},
        "result": None,
        "error": None,
    }
