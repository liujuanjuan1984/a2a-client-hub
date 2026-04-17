"""
Utility helpers for encrypting/decrypting sensitive user-provided secrets.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class SecretVaultNotConfiguredError(RuntimeError):
    """Raised when attempting to encrypt/decrypt without a configured key."""


@dataclass(frozen=True)
class DecryptionResult:
    value: str
    last4: Optional[str]


class SecretVault:
    """Thin wrapper around Fernet encryption with graceful fallbacks."""

    def __init__(self, raw_key: Optional[str]) -> None:
        key_material = (raw_key or "").strip()
        if not key_material:
            self._fernet: Optional[Fernet] = None
            logger.info(
                "SecretVault initialized without encryption key; secret features disabled"
            )
            return
        try:
            # Fernet expects urlsafe base64 bytes
            self._fernet = Fernet(key_material.encode("utf-8"))
        except (ValueError, TypeError) as exc:
            self._fernet = None
            logger.error("Invalid USER_LLM_TOKEN_ENCRYPTION_KEY: %s", exc)

    @property
    def is_configured(self) -> bool:
        return self._fernet is not None

    def encrypt(self, plaintext: str) -> tuple[str, Optional[str]]:
        if not self._fernet:
            raise SecretVaultNotConfiguredError(
                "Encryption key missing; cannot store user secrets"
            )
        token = self._fernet.encrypt(plaintext.encode("utf-8"))
        preview = plaintext[-4:] if plaintext else None
        return token.decode("utf-8"), preview

    def decrypt(self, token: str) -> DecryptionResult:
        if not self._fernet:
            raise SecretVaultNotConfiguredError(
                "Encryption key missing; cannot decrypt user secrets"
            )
        try:
            decrypted = self._fernet.decrypt(token.encode("utf-8"))
        except InvalidToken as exc:  # pragma: no cover - defensive
            raise SecretVaultNotConfiguredError("Failed to decrypt credential") from exc
        secret = decrypted.decode("utf-8")
        return DecryptionResult(value=secret, last4=secret[-4:] if secret else None)


user_llm_secret_vault = SecretVault(settings.user_llm_token_encryption_key)
hub_a2a_secret_vault = SecretVault(
    settings.hub_a2a_token_encryption_key or settings.user_llm_token_encryption_key
)
