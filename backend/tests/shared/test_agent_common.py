from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.secret_vault import SecretVaultNotConfiguredError
from app.features.agents_shared.common import (
    AgentValidationMixin,
    delete_agent_credentials,
    encrypt_bearer_token,
    get_agent_credential,
    normalize_auth_type,
    normalize_required_text,
    resolve_agent_auth_fields,
    upsert_agent_credential,
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


class _DummyService(AgentValidationMixin):
    _validation_error_cls = _ValidationError
    _allowed_auth_types = {"none", "bearer"}


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


def test_agent_validation_mixin_normalizes_auth_type():
    service = _DummyService()
    assert service._normalize_auth_type(" BEARER ") == "bearer"


def test_agent_validation_mixin_resolves_auth_fields():
    service = _DummyService()

    class _Existing:
        auth_header = "X-Auth"
        auth_scheme = "Token"

    assert service._resolve_auth_fields("bearer", None, None, _Existing()) == (
        "X-Auth",
        "Token",
    )


@pytest.mark.asyncio
async def test_get_agent_credential_calls_scalar():
    db = AsyncMock()
    agent_id = uuid4()
    await get_agent_credential(db, agent_id=agent_id)
    assert db.scalar.called


@pytest.mark.asyncio
async def test_delete_agent_credentials_calls_execute():
    db = AsyncMock()
    agent_id = uuid4()
    await delete_agent_credentials(db, agent_id=agent_id)
    assert db.execute.called


@pytest.mark.asyncio
async def test_upsert_agent_credential_updates_existing():
    db = AsyncMock()
    vault = _Vault(is_configured=True)
    agent_id = uuid4()
    user_id = uuid4()
    token = "token1234"

    existing_credential = AsyncMock()
    db.scalar.return_value = existing_credential

    last4 = await upsert_agent_credential(
        db,
        vault=vault,
        agent_id=agent_id,
        user_id=user_id,
        token=token,
        validation_error_cls=_ValidationError,
    )

    assert last4 == "1234"
    assert existing_credential.encrypted_token == "enc:token1234"
    assert existing_credential.token_last4 == "1234"
    assert existing_credential.created_by_user_id == user_id


@pytest.mark.asyncio
async def test_upsert_agent_credential_creates_new():
    db = AsyncMock()
    db.add = MagicMock()
    vault = _Vault(is_configured=True)
    agent_id = uuid4()
    user_id = uuid4()
    token = "token1234"

    db.scalar.return_value = None

    # We don't patch A2AAgentCredential to avoid breaking SQLAlchemy select()
    last4 = await upsert_agent_credential(
        db,
        vault=vault,
        agent_id=agent_id,
        user_id=user_id,
        token=token,
        validation_error_cls=_ValidationError,
    )

    assert last4 == "1234"
    assert db.add.called
    new_credential = db.add.call_args[0][0]
    assert new_credential.agent_id == agent_id
    assert new_credential.created_by_user_id == user_id
    assert new_credential.encrypted_token == "enc:token1234"
