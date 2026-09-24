from base64 import urlsafe_b64encode
from hashlib import sha256
from hmac import new as hmac_new

from cryptography.fernet import Fernet

from core_api.infrastructure.settings import settings


class InvalidBusinessIdentifierError(ValueError):
    pass


def normalize_cnpj(value: str) -> str:
    normalized = "".join(character for character in value if character.isdigit())
    if len(normalized) != 14 or normalized == normalized[0] * 14:
        raise InvalidBusinessIdentifierError("Invalid Brazilian CNPJ")
    weights = (
        (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2),
        (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2),
    )
    for index, current_weights in enumerate(weights, start=12):
        remainder = sum(
            int(digit) * weight
            for digit, weight in zip(normalized[:index], current_weights, strict=True)
        ) % 11
        expected = 0 if remainder < 2 else 11 - remainder
        if expected != int(normalized[index]):
            raise InvalidBusinessIdentifierError("Invalid Brazilian CNPJ")
    return normalized


def protect_cnpj(value: str) -> tuple[str, str, str]:
    normalized = normalize_cnpj(value)
    encryption_key = urlsafe_b64encode(
        sha256(settings.TENANT_IDENTITY_ENCRYPTION_KEY.encode("utf-8")).digest()
    )
    encrypted = Fernet(encryption_key).encrypt(normalized.encode("utf-8")).decode("ascii")
    lookup = hmac_new(
        settings.TENANT_IDENTITY_HMAC_KEY.encode("utf-8"),
        normalized.encode("utf-8"),
        "sha256",
    ).hexdigest()
    masked = f"••.•••.•••/••••-{normalized[-2:]}"
    return encrypted, lookup, masked
