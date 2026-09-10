from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from shared_kernel.localization import (
    SupportedLocale,
    normalize_country_code,
    normalize_locale,
)
from auth_api.modules.users.user_identifier_service import (
    normalize_identifier_type,
    validate_identifier,
)


IdentityDocumentType = Literal[
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


class PublicRegistration(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    email: str = Field(
        min_length=5, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    )
    password: str = Field(min_length=8, max_length=128)
    preferred_locale: SupportedLocale = "en"
    identity_document_type: IdentityDocumentType | None = None
    identity_document_country: str | None = None
    identity_document_value: str | None = Field(
        default=None, min_length=4, max_length=80
    )

    @field_validator("preferred_locale", mode="before")
    @classmethod
    def normalize_preferred_locale(cls, value: object) -> SupportedLocale:
        return normalize_locale(value)

    @field_validator("identity_document_country", mode="before")
    @classmethod
    def normalize_identity_country(cls, value: object) -> str | None:
        return normalize_country_code(value)

    @field_validator("identity_document_type", mode="before")
    @classmethod
    def normalize_identity_type(cls, value: object) -> object:
        return normalize_identifier_type(str(value)) if value else value

    @model_validator(mode="after")
    def validate_identity_fields(self) -> "PublicRegistration":
        provided = (
            self.identity_document_type,
            self.identity_document_country,
            self.identity_document_value,
        )
        if any(provided) and not all(provided):
            raise ValueError(
                "identity document type, country, and value must be provided together"
            )
        if self.identity_document_type and self.identity_document_value:
            validate_identifier(
                self.identity_document_type, self.identity_document_value
            )
        return self


class AccountActionAccepted(BaseModel):
    accepted: bool = True


class EmailVerification(BaseModel):
    token: str = Field(min_length=32, max_length=255)


class EmailVerificationRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)


class PasswordRecoveryRequest(EmailVerificationRequest):
    pass


class PasswordReset(BaseModel):
    token: str = Field(min_length=32, max_length=255)
    new_password: str = Field(min_length=8, max_length=128)
