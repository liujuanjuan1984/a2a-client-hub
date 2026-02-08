import pytest
from cryptography.fernet import Fernet

from app.core.secret_vault import SecretVault
from app.services.user_llm_credentials import user_llm_credential_service
from backend.tests.utils import create_user


@pytest.fixture(autouse=True)
def configure_secret_vault(monkeypatch):
    key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setattr(
        "app.core.config.settings.user_llm_token_encryption_key", key, raising=False
    )
    monkeypatch.setattr(
        "app.core.config.settings.user_llm_credentials_enabled", True, raising=False
    )
    user_llm_credential_service._vault = SecretVault(key)
    yield


@pytest.mark.asyncio
async def test_create_and_resolve_credential(async_session_maker):
    async with async_session_maker() as session:
        user = await create_user(session, skip_onboarding_defaults=True)
        credential = await user_llm_credential_service.create_credential(
            session,
            user_id=user.id,
            provider="openai",
            api_key="sk-test-123456",
            display_name="Primary",
            api_base="https://api.openai.com/v1",
            model_override="gpt-4.1",
        )

        assert credential.is_default
        assert credential.token_last4 == "3456"

        resolved = await user_llm_credential_service.resolve_active_credential(
            session, user_id=user.id
        )
        assert resolved is not None
        assert resolved.provider == "openai"
        assert resolved.api_key == "sk-test-123456"
        assert resolved.api_base == "https://api.openai.com/v1"
        assert resolved.model_override == "gpt-4.1"


@pytest.mark.asyncio
async def test_multiple_credentials_and_default_switch(async_session_maker):
    async with async_session_maker() as session:
        user = await create_user(session, skip_onboarding_defaults=True)

        first = await user_llm_credential_service.create_credential(
            session,
            user_id=user.id,
            provider="openai",
            api_key="sk-first",
            display_name="First Token",
        )
        second = await user_llm_credential_service.create_credential(
            session,
            user_id=user.id,
            provider="azure-openai",
            api_key="sk-second",
            display_name="Azure Token",
            make_default=False,
        )

        assert first.is_default
        assert not second.is_default

        await user_llm_credential_service.set_default(
            session, user_id=user.id, credential_id=second.id
        )
        refreshed = await user_llm_credential_service.list_credentials(
            session, user_id=user.id
        )

        defaults = [cred for cred in refreshed if cred.is_default]
        assert len(defaults) == 1
        assert defaults[0].id == second.id
