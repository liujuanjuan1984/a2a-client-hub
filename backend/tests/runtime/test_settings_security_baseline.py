from __future__ import annotations

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from app.core.config import Settings


def _generate_rsa_key_pair_pem() -> tuple[str, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    return private_pem, public_pem


def _generate_ec_key_pair_pem() -> tuple[str, str]:
    private_key = ec.generate_private_key(ec.SECP256R1())
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    return private_pem, public_pem


RSA_PRIVATE_KEY_PEM, RSA_PUBLIC_KEY_PEM = _generate_rsa_key_pair_pem()
_, OTHER_RSA_PUBLIC_KEY_PEM = _generate_rsa_key_pair_pem()
EC_PRIVATE_KEY_PEM, EC_PUBLIC_KEY_PEM = _generate_ec_key_pair_pem()


def _set_base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SCHEMA_NAME", "test_a2a_client_hub_schema")
    monkeypatch.setenv("JWT_ALGORITHM", "RS256")
    monkeypatch.setenv("JWT_PRIVATE_KEY_PEM", RSA_PRIVATE_KEY_PEM)
    monkeypatch.setenv("JWT_PUBLIC_KEY_PEM", RSA_PUBLIC_KEY_PEM)
    monkeypatch.setenv("WS_TICKET_SECRET_KEY", "another-strong-test-key-1234567890")
    monkeypatch.setenv("AUTH_REFRESH_COOKIE_SECURE", "true")
    monkeypatch.setenv("AUTH_REFRESH_COOKIE_SAMESITE", "lax")
    monkeypatch.setenv("BACKEND_CORS_ORIGINS", '["https://app.example.com"]')
    monkeypatch.setenv("AUTH_COOKIE_TRUSTED_ORIGINS", '["https://app.example.com"]')
    monkeypatch.setenv("WS_ALLOWED_ORIGINS", '["https://app.example.com"]')
    monkeypatch.setenv("WS_REQUIRE_ORIGIN", "true")
    monkeypatch.setenv("A2A_PROXY_ALLOWED_HOSTS", '["agent.example.com"]')


def test_production_does_not_require_legacy_jwt_secret_for_asymmetric_jwt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_base_env(monkeypatch)

    settings = Settings()

    assert settings.jwt_algorithm == "RS256"


def test_rejects_unsupported_symmetric_jwt_algorithm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_base_env(monkeypatch)
    monkeypatch.setenv("JWT_ALGORITHM", "HS512")

    with pytest.raises(ValueError, match="JWT_ALGORITHM must be one of"):
        Settings()


def test_rejects_invalid_jwt_private_key_pem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_base_env(monkeypatch)
    monkeypatch.setenv(
        "JWT_PRIVATE_KEY_PEM",
        (
            "-----BEGIN PRIVATE KEY-----\n"
            "not-valid-pem\n"
            "-----END PRIVATE KEY-----\n"
        ),
    )

    with pytest.raises(
        ValueError,
        match="JWT_PRIVATE_KEY_PEM must be a valid unencrypted PEM private key",
    ):
        Settings()


def test_rejects_mismatched_jwt_key_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_base_env(monkeypatch)
    monkeypatch.setenv("JWT_PUBLIC_KEY_PEM", OTHER_RSA_PUBLIC_KEY_PEM)

    with pytest.raises(
        ValueError,
        match="JWT_PRIVATE_KEY_PEM and JWT_PUBLIC_KEY_PEM must be a matching key pair",
    ):
        Settings()


def test_rejects_algorithm_and_key_type_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_base_env(monkeypatch)
    monkeypatch.setenv("JWT_ALGORITHM", "RS256")
    monkeypatch.setenv("JWT_PRIVATE_KEY_PEM", EC_PRIVATE_KEY_PEM)
    monkeypatch.setenv("JWT_PUBLIC_KEY_PEM", EC_PUBLIC_KEY_PEM)

    with pytest.raises(
        ValueError,
        match="JWT_ALGORITHM with RS\\* requires RSA private/public key PEM values",
    ):
        Settings()


def test_accepts_ec_keys_for_es_algorithm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_base_env(monkeypatch)
    monkeypatch.setenv("JWT_ALGORITHM", "ES256")
    monkeypatch.setenv("JWT_PRIVATE_KEY_PEM", EC_PRIVATE_KEY_PEM)
    monkeypatch.setenv("JWT_PUBLIC_KEY_PEM", EC_PUBLIC_KEY_PEM)

    settings = Settings()

    assert settings.jwt_algorithm == "ES256"


def test_production_rejects_relaxed_network_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_base_env(monkeypatch)
    monkeypatch.setenv("BACKEND_CORS_ORIGINS", '["http://localhost:3000"]')
    monkeypatch.setenv("WS_ALLOWED_ORIGINS", "[]")
    monkeypatch.setenv("A2A_PROXY_ALLOWED_HOSTS", "[]")

    with pytest.raises(ValueError) as exc_info:
        Settings()

    message = str(exc_info.value)
    assert "BACKEND_CORS_ORIGINS" in message
    assert "WS_ALLOWED_ORIGINS" in message
    assert "A2A_PROXY_ALLOWED_HOSTS" in message


def test_development_allows_localhost_and_dev_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_base_env(monkeypatch)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("WS_TICKET_SECRET_KEY", "change-me-ws-ticket-secret")
    monkeypatch.setenv("AUTH_REFRESH_COOKIE_SECURE", "false")
    monkeypatch.setenv("BACKEND_CORS_ORIGINS", '["http://localhost:3000"]')
    monkeypatch.setenv("WS_ALLOWED_ORIGINS", "[]")
    monkeypatch.setenv("WS_REQUIRE_ORIGIN", "false")
    monkeypatch.setenv("A2A_PROXY_ALLOWED_HOSTS", "[]")

    settings = Settings()

    assert settings.app_env == "development"


def test_invalid_app_env_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_base_env(monkeypatch)
    monkeypatch.setenv("APP_ENV", "prod")

    with pytest.raises(ValueError, match="APP_ENV must be one of"):
        Settings()


def test_rejects_schedule_invoke_timeout_not_greater_than_heartbeat_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_base_env(monkeypatch)
    monkeypatch.setenv("A2A_SCHEDULE_TASK_INVOKE_TIMEOUT", "30")
    monkeypatch.setenv("A2A_SCHEDULE_RUN_HEARTBEAT_INTERVAL_SECONDS", "30")

    with pytest.raises(
        ValueError,
        match=(
            "A2A_SCHEDULE_TASK_INVOKE_TIMEOUT must be greater than "
            "A2A_SCHEDULE_RUN_HEARTBEAT_INTERVAL_SECONDS"
        ),
    ):
        Settings()


def test_rejects_schedule_heartbeat_interval_too_small(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_base_env(monkeypatch)
    monkeypatch.setenv("A2A_SCHEDULE_RUN_HEARTBEAT_INTERVAL_SECONDS", "5")

    with pytest.raises(
        ValueError,
        match="A2A schedule heartbeat interval must be at least 15 seconds",
    ):
        Settings()
