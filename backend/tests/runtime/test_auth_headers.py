from app.utils.auth_headers import build_auth_header_pair, resolve_stored_auth_fields


def test_resolve_stored_auth_fields_uses_existing_when_input_is_empty_string():
    header, scheme = resolve_stored_auth_fields(
        auth_header="",
        auth_scheme="",
        existing_auth_header="X-Api-Key",
        existing_auth_scheme="Token",
    )
    assert header == "X-Api-Key"
    assert scheme == "Token"


def test_resolve_stored_auth_fields_uses_defaults_when_input_is_whitespace():
    header, scheme = resolve_stored_auth_fields(
        auth_header="   ",
        auth_scheme="   ",
        existing_auth_header="X-Api-Key",
        existing_auth_scheme="Token",
    )
    assert header == "Authorization"
    assert scheme == "Bearer"


def test_resolve_stored_auth_fields_uses_defaults_without_existing():
    header, scheme = resolve_stored_auth_fields(
        auth_header=None,
        auth_scheme=None,
        existing_auth_header=None,
        existing_auth_scheme=None,
    )
    assert header == "Authorization"
    assert scheme == "Bearer"


def test_build_auth_header_pair_defaults_to_bearer():
    name, value = build_auth_header_pair(
        auth_header=None,
        auth_scheme=None,
        token="abc",
    )
    assert name == "Authorization"
    assert value == "Bearer abc"


def test_build_auth_header_pair_allows_token_only_for_whitespace_scheme():
    name, value = build_auth_header_pair(
        auth_header="X-Token",
        auth_scheme="   ",
        token="abc",
    )
    assert name == "X-Token"
    assert value == "abc"
