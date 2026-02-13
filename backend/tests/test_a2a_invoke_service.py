from __future__ import annotations

import json
import logging

import pytest

from app.services.a2a_invoke_service import a2a_invoke_service


class _BrokenGateway:
    async def stream(self, **kwargs):
        raise RuntimeError("stream failed")
        yield  # pragma: no cover


@pytest.mark.asyncio
async def test_sse_error_event_contains_unified_error_code():
    response = a2a_invoke_service.stream_sse(
        gateway=_BrokenGateway(),
        resolved=object(),
        query="hello",
        context_id=None,
        metadata=None,
        validate_message=lambda _: [],
        logger=logging.getLogger(__name__),
        log_extra={},
    )
    chunks: list[str] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)

    payload = "".join(chunks)
    assert "event: error" in payload
    error_data_line = next(
        line for line in payload.splitlines() if line.startswith("data: {")
    )
    error_data = json.loads(error_data_line.removeprefix("data: "))
    assert error_data["message"] == "Upstream streaming failed"
    assert error_data["error_code"] == "upstream_stream_error"


def test_extract_binding_hints_from_serialized_event():
    (
        context_id,
        metadata,
    ) = a2a_invoke_service.extract_binding_hints_from_serialized_event(
        {
            "contextId": "ctx-1",
            "metadata": {
                "provider": "OpenCode",
                "externalSessionId": "upstream-1",
            },
        }
    )
    assert context_id == "ctx-1"
    assert metadata["provider"] == "opencode"
    assert metadata["externalSessionId"] == "upstream-1"


def test_extract_binding_hints_from_invoke_result_merges_raw_payload():
    class _RawPayload:
        def model_dump(self, **kwargs):
            return {
                "contextId": "ctx-from-raw",
                "metadata": {
                    "provider": "opencode",
                    "externalSessionId": "raw-upstream",
                },
            }

    context_id, metadata = a2a_invoke_service.extract_binding_hints_from_invoke_result(
        {
            "success": True,
            "content": "ok",
            "contextId": "ctx-from-result",
            "metadata": {"externalSessionId": "result-upstream"},
            "raw": _RawPayload(),
        }
    )
    assert context_id == "ctx-from-raw"
    assert metadata["provider"] == "opencode"
    assert metadata["externalSessionId"] == "raw-upstream"
