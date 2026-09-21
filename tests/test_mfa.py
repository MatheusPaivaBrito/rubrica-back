import pyotp
import pytest
from pydantic import ValidationError
from types import SimpleNamespace

from auth_api.infrastructure.settings import Settings
from auth_api.modules.mfa.mfa_crypto import decrypt_secret, encrypt_secret
from auth_api.modules.mfa.mfa_service import MfaError, MfaService


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


def test_mfa_cannot_be_disabled_for_any_account() -> None:
    with pytest.raises(MfaError, match="required for every account"):
        MfaService().disable("user@example.com", "password", "123456")


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
        AUTH_IDENTITY_ENCRYPTION_KEY="a-distinct-production-identity-encryption-secret",
        AUTH_IDENTITY_HMAC_KEY="a-distinct-production-identity-hmac-secret",
    )

    assert configured.ENVIRONMENT == "production"


@pytest.mark.parametrize("duplicate", ["encryption_hmac", "encryption_mfa", "hmac_mfa"])
def test_production_rejects_reused_identity_keys(duplicate: str) -> None:
    mfa_key = "a-distinct-production-mfa-encryption-secret"
    encryption_key = "a-distinct-production-identity-encryption-secret"
    hmac_key = "a-distinct-production-identity-hmac-secret"
    if duplicate == "encryption_hmac":
        hmac_key = encryption_key
    elif duplicate == "encryption_mfa":
        encryption_key = mfa_key
    else:
        hmac_key = mfa_key

    with pytest.raises(ValidationError, match="distinct Auth identity keys"):
        Settings(
            _env_file=None,
            ENVIRONMENT="production",
            AUTH_MFA_ENCRYPTION_KEY=mfa_key,
            AUTH_IDENTITY_ENCRYPTION_KEY=encryption_key,
            AUTH_IDENTITY_HMAC_KEY=hmac_key,
        )
