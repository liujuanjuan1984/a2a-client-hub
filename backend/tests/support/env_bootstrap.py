from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

TEST_BACKEND_ENV_FILE = "BACKEND_ENV_FILE"

_AMBIENT_SETTING_PREFIXES = (
    "A2A_",
    "AUTH_",
    "BACKEND_",
    "DATABASE_",
    "HUB_ASSISTANT_",
    "JWT_",
    "WS_",
)

_AMBIENT_SETTING_NAMES = {
    "APP_ENV",
    TEST_BACKEND_ENV_FILE,
    "DATABASE_URL",
    "FIRST_USER_SUPERUSER",
    "HUB_A2A_TOKEN_ENCRYPTION_KEY",
    "INVITATION_CODE_LENGTH",
    "LOG_FORMAT",
    "REQUIRE_INVITATION_FOR_REGISTRATION",
    "SCHEMA_NAME",
    "USER_LLM_TOKEN_ENCRYPTION_KEY",
    "UVICORN_WORKERS",
}


def _is_ambient_setting_name(name: str) -> bool:
    return name in _AMBIENT_SETTING_NAMES or any(
        name.startswith(prefix) for prefix in _AMBIENT_SETTING_PREFIXES
    )


def _clear_ambient_application_settings() -> None:
    for name in list(os.environ):
        if _is_ambient_setting_name(name):
            os.environ.pop(name, None)


def _resolve_test_database_url() -> str:
    explicit_database_url = os.getenv("TEST_DATABASE_URL")
    if explicit_database_url:
        return explicit_database_url

    default_db_name = os.getenv("TEST_DATABASE_NAME") or os.getenv("USER") or "postgres"
    return f"postgresql:///{default_db_name}"


def _build_test_jwt_key_pair() -> tuple[str, str]:
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


def apply_test_environment() -> None:
    """Install a controlled application environment for backend tests."""

    _clear_ambient_application_settings()

    os.environ[TEST_BACKEND_ENV_FILE] = ""
    os.environ["APP_ENV"] = "development"
    os.environ["SCHEMA_NAME"] = os.getenv(
        "TEST_SCHEMA_NAME", "test_a2a_client_hub_schema"
    )
    os.environ["DATABASE_URL"] = _resolve_test_database_url()

    default_test_secret_key = base64.urlsafe_b64encode(b"0" * 32).decode("utf-8")
    os.environ["USER_LLM_TOKEN_ENCRYPTION_KEY"] = default_test_secret_key
    os.environ["HUB_A2A_TOKEN_ENCRYPTION_KEY"] = default_test_secret_key
    os.environ["WS_TICKET_SECRET_KEY"] = default_test_secret_key

    private_pem = os.getenv("TEST_JWT_PRIVATE_KEY_PEM")
    public_pem = os.getenv("TEST_JWT_PUBLIC_KEY_PEM")
    if not private_pem or not public_pem:
        private_pem, public_pem = _build_test_jwt_key_pair()

    os.environ["JWT_ALGORITHM"] = "RS256"
    os.environ["JWT_PRIVATE_KEY_PEM"] = private_pem
    os.environ["JWT_PUBLIC_KEY_PEM"] = public_pem
    os.environ["JWT_ISSUER"] = "common-compass-test"
    os.environ["JWT_ACCESS_TOKEN_TTL_SECONDS"] = "1800"
    os.environ["JWT_REFRESH_TOKEN_TTL_SECONDS"] = "1209600"
    os.environ["AUTH_REFRESH_COOKIE_SECURE"] = "false"
