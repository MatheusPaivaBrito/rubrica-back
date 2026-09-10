from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from auth_api.modules.users.user_identifier_service import (
    IdentifierType,
    normalize_identifier_type,
    validate_identifier,
)
from shared_kernel.localization import (
    SupportedLocale,
    normalize_country_code,
    normalize_locale,
)


UserRole = Literal[
    "signature_admin", "signature_operator", "signature_signer", "signature_auditor"
]


class UserCreate(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    email: str = Field(
        min_length=5, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    )
    cpf: str | None = Field(default=None, min_length=11, max_length=14)
    identity_document_type: IdentifierType | None = None
    identity_document_country: str | None = None
    identity_document_value: str | None = Field(
        default=None, min_length=4, max_length=80
    )
    password: str = Field(min_length=8, max_length=128)
    role: UserRole = "signature_signer"
    preferred_locale: SupportedLocale = "en"

    @field_validator("preferred_locale", mode="before")
    @classmethod
    def normalize_preferred_locale(cls, value: object) -> SupportedLocale:
        return normalize_locale(value)

    @field_validator("identity_document_type", mode="before")
    @classmethod
    def normalize_identity_type(cls, value: object) -> object:
        return normalize_identifier_type(str(value)) if value else value

    @field_validator("identity_document_country", mode="before")
    @classmethod
    def normalize_identity_country(cls, value: object) -> str | None:
        return normalize_country_code(value)

    @model_validator(mode="after")
    def validate_identity(self) -> "UserCreate":
        if self.cpf and not self.identity_document_value:
            self.identity_document_type = "BR_CPF"
            self.identity_document_country = "BR"
            self.identity_document_value = self.cpf
        fields = (
            self.identity_document_type,
            self.identity_document_country,
            self.identity_document_value,
        )
        if any(fields) and not all(fields):
            raise ValueError(
                "identity document type, country, and value must be provided together"
            )
        if self.identity_document_type and self.identity_document_value:
            validate_identifier(
                self.identity_document_type, self.identity_document_value
            )
        return self


class UserRead(BaseModel):
    id: UUID
    name: str
    email: str
    role: UserRole
    is_active: bool
    preferred_locale: SupportedLocale


class UserPreferencesUpdate(BaseModel):
    preferred_locale: SupportedLocale

    @field_validator("preferred_locale", mode="before")
    @classmethod
    def normalize_preferred_locale(cls, value: object) -> SupportedLocale:
        return normalize_locale(value)


class UserIdentifierRead(BaseModel):
    id: UUID
    issuing_country: str
    identifier_type: str
    masked_display: str
    verification_status: str
