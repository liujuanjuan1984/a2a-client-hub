from app.api.error_handlers import normalize_error_detail


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
