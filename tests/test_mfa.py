import pyotp
import pytest
from pydantic import ValidationError
from types import SimpleNamespace

from auth_api.infrastructure.settings import Settings
from auth_api.modules.mfa.mfa_crypto import decrypt_secret, encrypt_secret
from auth_api.modules.mfa.mfa_service import MfaService


def test_mfa_secret_is_encrypted_at_rest() -> None:
    secret = pyotp.random_base32()
    ciphertext = encrypt_secret(secret)

    assert ciphertext != secret
    assert decrypt_secret(ciphertext) == secret


def test_microsoft_authenticator_compatible_totp_is_accepted() -> None:
    secret = pyotp.random_base32()
    code = pyotp.TOTP(secret).now()

    assert MfaService._verify_totp(secret, code)


def test_same_totp_step_cannot_be_reused() -> None:
    secret = pyotp.random_base32()
    code = pyotp.TOTP(secret).now()
    user = SimpleNamespace(
        id="user-id",
        mfa_secret_ciphertext=encrypt_secret(secret),
        mfa_last_used_step=None,
    )

    class EmptyResult:
        @staticmethod
        def all() -> list[object]:
            return []

    class Database:
        @staticmethod
        def scalars(_statement) -> EmptyResult:
            return EmptyResult()

    service = MfaService()
    assert service.verify_user_code(Database(), user, code)
    assert not service.verify_user_code(Database(), user, code)


def test_production_rejects_development_mfa_encryption_key() -> None:
    with pytest.raises(ValidationError, match="AUTH_MFA_ENCRYPTION_KEY"):
        Settings(
            ENVIRONMENT="production",
            AUTH_MFA_ENCRYPTION_KEY="rubrica-development-mfa-key-change-me",
        )


def test_production_accepts_distinct_mfa_encryption_key() -> None:
    configured = Settings(
        ENVIRONMENT="production",
        AUTH_MFA_ENCRYPTION_KEY="a-distinct-production-mfa-encryption-secret",
    )

    assert configured.ENVIRONMENT == "production"
