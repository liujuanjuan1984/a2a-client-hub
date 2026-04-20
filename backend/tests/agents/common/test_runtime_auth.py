from types import SimpleNamespace

import pytest

from app.core.secret_vault import SecretVaultNotConfiguredError
from app.features.agents.common.runtime_auth import (
    build_resolved_runtime_agent,
    resolve_runtime_auth_headers,
)


class _ValidationError(RuntimeError):
    pass


class _Vault:
    def __init__(self, *, is_configured: bool, decrypt_outcome):
        self.is_configured = is_configured
        self._decrypt_outcome = decrypt_outcome

    def decrypt(self, token: str):  # noqa: ARG002
        if isinstance(self._decrypt_outcome, Exception):
            raise self._decrypt_outcome
        return self._decrypt_outcome


def test_runtime_auth_none_keeps_headers():
    headers, token_last4 = resolve_runtime_auth_headers(
        headers={"X-A": "1"},
        auth_type="none",
        auth_header=None,
        auth_scheme=None,
        credential=None,
        vault=_Vault(is_configured=True, decrypt_outcome=None),
        validation_error_cls=_ValidationError,
    )
    assert headers == {"X-A": "1"}
    assert token_last4 is None


def test_runtime_auth_rejects_unsupported_type():
    with pytest.raises(_ValidationError, match="Unsupported auth_type"):
        resolve_runtime_auth_headers(
            headers={},
            auth_type="api_key",
            auth_header=None,
            auth_scheme=None,
            credential=None,
            vault=_Vault(is_configured=True, decrypt_outcome=None),
            validation_error_cls=_ValidationError,
        )


def test_runtime_auth_requires_credential_for_bearer():
    with pytest.raises(_ValidationError, match="Bearer token is required"):
        resolve_runtime_auth_headers(
            headers={},
            auth_type="bearer",
            auth_header=None,
            auth_scheme=None,
            credential=None,
            vault=_Vault(is_configured=True, decrypt_outcome=None),
            validation_error_cls=_ValidationError,
        )


def test_runtime_auth_requires_configured_vault():
    with pytest.raises(_ValidationError, match="Credential encryption key is missing"):
        resolve_runtime_auth_headers(
            headers={},
            auth_type="bearer",
            auth_header=None,
            auth_scheme=None,
            credential=SimpleNamespace(encrypted_token="enc", token_last4="1234"),
            vault=_Vault(is_configured=False, decrypt_outcome=None),
            validation_error_cls=_ValidationError,
        )


def test_runtime_auth_builds_header_and_prefers_decrypted_last4():
    headers, token_last4 = resolve_runtime_auth_headers(
        headers={"X-A": "1"},
        auth_type="bearer",
        auth_header="X-Token",
        auth_scheme="Token",
        credential=SimpleNamespace(encrypted_token="enc", token_last4="1234"),
        vault=_Vault(
            is_configured=True,
            decrypt_outcome=SimpleNamespace(value="secret", last4="cret"),
        ),
        validation_error_cls=_ValidationError,
    )
    assert headers["X-A"] == "1"
    assert headers["X-Token"] == "Token secret"
    assert token_last4 == "cret"


def test_runtime_auth_falls_back_to_credential_last4():
    headers, token_last4 = resolve_runtime_auth_headers(
        headers={},
        auth_type="bearer",
        auth_header=None,
        auth_scheme=None,
        credential=SimpleNamespace(encrypted_token="enc", token_last4="1234"),
        vault=_Vault(
            is_configured=True,
            decrypt_outcome=SimpleNamespace(value="secret", last4=None),
        ),
        validation_error_cls=_ValidationError,
    )
    assert headers["Authorization"] == "Bearer secret"
    assert token_last4 == "1234"


def test_runtime_auth_maps_vault_error_to_validation_error():
    with pytest.raises(_ValidationError, match="cannot decrypt"):
        resolve_runtime_auth_headers(
            headers={},
            auth_type="bearer",
            auth_header=None,
            auth_scheme=None,
            credential=SimpleNamespace(encrypted_token="enc", token_last4="1234"),
            vault=_Vault(
                is_configured=True,
                decrypt_outcome=SecretVaultNotConfiguredError("cannot decrypt"),
            ),
            validation_error_cls=_ValidationError,
        )


def test_build_resolved_runtime_agent_builds_resolved_agent():
    resolved, token_last4 = build_resolved_runtime_agent(
        name="demo-agent",
        card_url="https://example.com/card",
        extra_headers={"X-A": "1"},
        auth_type="none",
        auth_header=None,
        auth_scheme=None,
        credential=None,
        vault=_Vault(is_configured=True, decrypt_outcome=None),
        validation_error_cls=_ValidationError,
    )
    assert resolved.name == "demo-agent"
    assert resolved.url == "https://example.com/card"
    assert resolved.headers == {"X-A": "1"}
    assert token_last4 is None


def test_build_resolved_runtime_agent_returns_token_last4_for_bearer():
    resolved, token_last4 = build_resolved_runtime_agent(
        name="demo-agent",
        card_url="https://example.com/card",
        extra_headers={},
        auth_type="bearer",
        auth_header=None,
        auth_scheme=None,
        credential=SimpleNamespace(encrypted_token="enc", token_last4="1234"),
        vault=_Vault(
            is_configured=True,
            decrypt_outcome=SimpleNamespace(value="secret", last4="cret"),
        ),
        validation_error_cls=_ValidationError,
    )
    assert resolved.headers == {"Authorization": "Bearer secret"}
    assert token_last4 == "cret"
