from base64 import urlsafe_b64encode
from hashlib import sha256

from cryptography.fernet import Fernet

from auth_api.infrastructure.settings import settings


def _fernet() -> Fernet:
    key = urlsafe_b64encode(sha256(settings.AUTH_MFA_ENCRYPTION_KEY.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
