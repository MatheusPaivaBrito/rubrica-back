import pyotp

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
