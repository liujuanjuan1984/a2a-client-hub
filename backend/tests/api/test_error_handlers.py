import pytest
from starlette.requests import Request

from app.api import error_handlers
from app.api.error_handlers import normalize_error_detail, unhandled_exception_handler


def test_normalize_error_detail_preserves_canonical_structured_error_fields() -> None:
    detail = normalize_error_detail(
        {
            "message": "Card URL host is not allowed",
            "error_code": "card_url_host_not_allowed",
            "source": "upstream_a2a",
            "jsonrpc_code": -32602,
            "missing_params": [{"name": "project_id", "required": True}],
            "upstream_error": {"message": "project_id required"},
        },
        default_message="Forbidden",
    )

    assert detail == {
        "message": "Card URL host is not allowed",
        "error_code": "card_url_host_not_allowed",
        "source": "upstream_a2a",
        "jsonrpc_code": -32602,
        "missing_params": [{"name": "project_id", "required": True}],
        "upstream_error": {"message": "project_id required"},
    }


def test_normalize_error_detail_maps_legacy_code_to_error_code() -> None:
    detail = normalize_error_detail(
        {
            "message": "Legacy error",
            "code": "legacy_error_code",
            "meta": {"foo": "bar"},
        },
        default_message="Bad Request",
    )

    assert detail == {
        "message": "Legacy error",
        "error_code": "legacy_error_code",
        "meta": {"foo": "bar"},
    }


@pytest.mark.asyncio
async def test_unhandled_exception_handler_logs_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logged: list[dict[str, object]] = []

    def _capture(message: str, *args: object, **kwargs: object) -> None:
        logged.append({"message": message, **kwargs})

    monkeypatch.setattr(error_handlers.logger, "exception", _capture)
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/test",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 12345),
            "query_string": b"",
        }
    )

    response = await unhandled_exception_handler(request, RuntimeError("boom"))

    assert response.status_code == 500
    assert len(logged) == 1
    assert logged[0]["message"] == "Unhandled application exception"
    assert logged[0]["extra"] == {"path": "/api/v1/test", "method": "POST"}
