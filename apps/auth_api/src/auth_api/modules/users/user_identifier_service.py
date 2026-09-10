from base64 import urlsafe_b64encode
from hashlib import sha256
from hmac import new as hmac_new
from typing import Literal

from cryptography.fernet import Fernet

from auth_api.infrastructure.settings import settings
from auth_api.modules.users.user_identifier_entity import UserIdentifierEntity


IdentifierType = Literal[
    "BR_CPF",
    "PT_NIF",
    "PASSPORT",
    "NATIONAL_ID",
    "RESIDENCE_CARD",
    "DRIVER_LICENSE",
    "TAX_ID",
    "OTHER",
    "JP_MY_NUMBER",
]

ALIASES = {
    "passport": "PASSPORT",
    "national_id": "NATIONAL_ID",
    "residence_card": "RESIDENCE_CARD",
    "driver_license": "DRIVER_LICENSE",
    "tax_id": "TAX_ID",
    "other": "OTHER",
    "br_cpf": "BR_CPF",
    "pt_nif": "PT_NIF",
    "jp_my_number": "JP_MY_NUMBER",
}


class InvalidIdentifierError(ValueError):
    pass


def normalize_identifier_type(value: str) -> str:
    normalized = value.strip().lower()
    return ALIASES.get(normalized, value.strip().upper())


def normalize_identifier(value: str) -> str:
    return "".join(
        character for character in value.upper().strip() if character.isalnum()
    )


def validate_identifier(identifier_type: str, value: str) -> str:
    normalized_type = normalize_identifier_type(identifier_type)
    normalized = normalize_identifier(value)
    if normalized_type == "JP_MY_NUMBER" and not settings.AUTH_JP_MY_NUMBER_ENABLED:
        raise InvalidIdentifierError("JP My Number is not enabled")
    if normalized_type == "BR_CPF":
        if (
            len(normalized) != 11
            or not normalized.isdigit()
            or normalized == normalized[0] * 11
        ):
            raise InvalidIdentifierError("Invalid Brazilian CPF")
        for size in (9, 10):
            total = sum(
                int(digit) * weight
                for digit, weight in zip(
                    normalized[:size], range(size + 1, 1, -1), strict=True
                )
            )
            if (total * 10 % 11) % 10 != int(normalized[size]):
                raise InvalidIdentifierError("Invalid Brazilian CPF")
    elif normalized_type == "PT_NIF":
        if len(normalized) != 9 or not normalized.isdigit():
            raise InvalidIdentifierError("Invalid Portuguese NIF format")
    elif not 4 <= len(normalized) <= 80:
        raise InvalidIdentifierError("Invalid identity document format")
    return normalized


def protect_identifier(value: str) -> tuple[str, str]:
    encryption_key = urlsafe_b64encode(
        sha256(settings.AUTH_IDENTITY_ENCRYPTION_KEY.encode("utf-8")).digest()
    )
    encrypted = Fernet(encryption_key).encrypt(value.encode("utf-8")).decode("ascii")
    lookup = hmac_new(
        settings.AUTH_IDENTITY_HMAC_KEY.encode("utf-8"),
        value.encode("utf-8"),
        "sha256",
    ).hexdigest()
    return encrypted, lookup


def masked_identifier(value: str) -> str:
    visible = value[-4:]
    return f"{'•' * max(len(value) - 4, 4)}{visible}"


def add_identifier(
    database, *, user_id, issuing_country: str, identifier_type: str, value: str
) -> UserIdentifierEntity:
    normalized_type = normalize_identifier_type(identifier_type)
    normalized = validate_identifier(normalized_type, value)
    encrypted, lookup = protect_identifier(normalized)
    item = UserIdentifierEntity(
        user_id=user_id,
        issuing_country=issuing_country,
        identifier_type=normalized_type,
        normalized_value_encrypted=encrypted,
        lookup_hmac=lookup,
        masked_display=masked_identifier(normalized),
        verification_status="format_valid",
        key_version=1,
    )
    database.add(item)
    return item
