from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from shared_kernel.localization import SupportedLocale, normalize_locale


UserRole = Literal["signature_admin", "signature_operator", "signature_signer", "signature_auditor"]


class UserCreate(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    email: str = Field(min_length=5, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    cpf: str = Field(min_length=11, max_length=14)
    password: str = Field(min_length=8, max_length=128)
    role: UserRole = "signature_signer"
    preferred_locale: SupportedLocale = "en"

    @field_validator("preferred_locale", mode="before")
    @classmethod
    def normalize_preferred_locale(cls, value: object) -> SupportedLocale:
        return normalize_locale(value)

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
