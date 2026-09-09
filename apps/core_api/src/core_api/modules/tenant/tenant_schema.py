from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from shared_kernel.localization import (
    SupportedLocale,
    normalize_country_code,
    normalize_currency,
    normalize_locale,
    normalize_timezone,
)


class TenantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    slug: str = Field(min_length=2, max_length=120, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    default_locale: SupportedLocale = "en"
    country_code: str | None = None
    timezone: str = "UTC"
    currency: str = "USD"

    @field_validator("default_locale", mode="before")
    @classmethod
    def normalize_default_locale(cls, value: object) -> SupportedLocale:
        return normalize_locale(value)

    @field_validator("country_code", mode="before")
    @classmethod
    def validate_country_code(cls, value: object) -> str | None:
        return normalize_country_code(value)

    @field_validator("timezone", mode="before")
    @classmethod
    def validate_timezone(cls, value: object) -> str:
        return normalize_timezone(value)

    @field_validator("currency", mode="before")
    @classmethod
    def validate_currency(cls, value: object) -> str:
        return normalize_currency(value)


class TenantRead(BaseModel):
    id: UUID
    name: str
    slug: str
    status: str
    role: str
    created_at: datetime
    default_locale: SupportedLocale
    country_code: str | None
    timezone: str
    currency: str


class TenantPreferencesUpdate(BaseModel):
    default_locale: SupportedLocale
    country_code: str | None = None
    timezone: str
    currency: str

    @field_validator("default_locale", mode="before")
    @classmethod
    def normalize_default_locale(cls, value: object) -> SupportedLocale:
        return normalize_locale(value)

    @field_validator("country_code", mode="before")
    @classmethod
    def validate_country_code(cls, value: object) -> str | None:
        return normalize_country_code(value)

    @field_validator("timezone", mode="before")
    @classmethod
    def validate_timezone(cls, value: object) -> str:
        return normalize_timezone(value)

    @field_validator("currency", mode="before")
    @classmethod
    def validate_currency(cls, value: object) -> str:
        return normalize_currency(value)


class TenantMemberCreate(BaseModel):
    auth_user_id: str = Field(min_length=3, max_length=255)
    role: str = Field(default="member", pattern=r"^(admin|member|auditor)$")
