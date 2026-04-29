from app.integrations.a2a_extensions.negotiation import (
    build_extension_request_headers,
)


def test_build_extension_request_headers_merges_requested_extensions() -> None:
    headers = build_extension_request_headers(
        base_headers={
            "Authorization": "Bearer test-token",
            "A2A-Extensions": "urn:a2a:session-binding/v1",
        },
        requested_extensions=[
            "urn:a2a:session-query/v1",
            "urn:a2a:session-binding/v1",
        ],
    )

    assert headers["Authorization"] == "Bearer test-token"
    assert headers["A2A-Extensions"] == (
        "urn:a2a:session-binding/v1,urn:a2a:session-query/v1"
    )
