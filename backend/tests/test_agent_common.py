import pytest

from app.core.secret_vault import SecretVaultNotConfiguredError
from app.services.agent_common import (
    encrypt_bearer_token,
    normalize_auth_type,
    normalize_required_text,
    resolve_agent_auth_fields,
)


class _ValidationError(RuntimeError):
    pass


class _Vault:
    def __init__(self, *, is_configured: bool, raise_encrypt_error: bool = False):
        self.is_configured = is_configured
        self._raise_encrypt_error = raise_encrypt_error

    def encrypt(self, value: str) -> tuple[str, str]:
        if self._raise_encrypt_error:
            raise SecretVaultNotConfiguredError("vault is unavailable")
        return f"enc:{value}", value[-4:]


def test_normalize_required_text_returns_trimmed_value():
    assert (
        normalize_required_text(
            value="  hello  ",
            field_label="Name",
            validation_error_cls=_ValidationError,
        )
        == "hello"
    )


def test_normalize_required_text_raises_on_blank():
    with pytest.raises(_ValidationError, match="Name is required"):
        normalize_required_text(
            value="   ",
            field_label="Name",
            validation_error_cls=_ValidationError,
        )


def test_normalize_auth_type_returns_lowercase_value():
    assert (
        normalize_auth_type(
            value="  BEARER ",
            allowed_auth_types={"none", "bearer"},
            validation_error_cls=_ValidationError,
        )
        == "bearer"
    )


def test_normalize_auth_type_raises_on_invalid_value():
    with pytest.raises(_ValidationError, match="Unsupported auth_type"):
        normalize_auth_type(
            value="api-key",
            allowed_auth_types={"none", "bearer"},
            validation_error_cls=_ValidationError,
        )


def test_resolve_agent_auth_fields_for_none_returns_empty_tuple():
    assert resolve_agent_auth_fields(
        auth_type="none",
        auth_header=None,
        auth_scheme=None,
        existing_auth_header="Authorization",
        existing_auth_scheme="Bearer",
        validation_error_cls=_ValidationError,
    ) == (None, None)


def test_resolve_agent_auth_fields_for_bearer_uses_existing_defaults():
    assert resolve_agent_auth_fields(
        auth_type="bearer",
        auth_header=None,
        auth_scheme="",
        existing_auth_header="X-Auth",
        existing_auth_scheme="Token",
        validation_error_cls=_ValidationError,
    ) == ("X-Auth", "Token")


def test_resolve_agent_auth_fields_raises_on_invalid_auth_type():
    with pytest.raises(_ValidationError, match="Unsupported auth_type"):
        resolve_agent_auth_fields(
            auth_type="api_key",
            auth_header=None,
            auth_scheme=None,
            existing_auth_header=None,
            existing_auth_scheme=None,
            validation_error_cls=_ValidationError,
        )


def test_encrypt_bearer_token_returns_encrypted_value_and_last4():
    encrypted_value, last4 = encrypt_bearer_token(
        vault=_Vault(is_configured=True),
        token="  token1234 ",
        validation_error_cls=_ValidationError,
    )
    assert encrypted_value == "enc:token1234"
    assert last4 == "1234"


@pytest.mark.parametrize("token", [None, "", "   "])
def test_encrypt_bearer_token_raises_when_token_missing(token):
    with pytest.raises(_ValidationError, match="Bearer token is required"):
        encrypt_bearer_token(
            vault=_Vault(is_configured=True),
            token=token,
            validation_error_cls=_ValidationError,
        )


def test_encrypt_bearer_token_raises_when_vault_not_configured():
    with pytest.raises(_ValidationError, match="Credential encryption key is missing"):
        encrypt_bearer_token(
            vault=_Vault(is_configured=False),
            token="token1234",
            validation_error_cls=_ValidationError,
        )


def test_encrypt_bearer_token_re_raises_vault_error_as_validation_error():
    with pytest.raises(_ValidationError, match="vault is unavailable"):
        encrypt_bearer_token(
            vault=_Vault(is_configured=True, raise_encrypt_error=True),
            token="token1234",
            validation_error_cls=_ValidationError,
        )
