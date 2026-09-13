from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from shared_kernel.config import apply_secret_files


class Settings(BaseSettings):
    APP_NAME: str = "Rubrica Core API"
    ENVIRONMENT: str = "development"
    DEBUG: bool = Field(default=True, validation_alias="APP_DEBUG")
    SERVICE_NAME: str = "core_api"
    API_PORT: int = 8000
    POSTGRES_USER: str = "rubrica"
    POSTGRES_PASSWORD: str = "rubrica"
    POSTGRES_PASSWORD_FILE: str | None = None
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5435
    CORE_POSTGRES_DB: str = "rubrica_core"
    DATABASE_URL: str | None = Field(default=None, validation_alias="CORE_DATABASE_URL")
    AUTH_API_URL: str = "http://localhost:8101"
    CORE_INTERNAL_SERVICE_KEY: str = ""
    CORE_INTERNAL_SERVICE_KEY_FILE: str | None = None
    NOTIFICATION_API_URL: str = "http://localhost:8103"
    NOTIFICATION_INTERNAL_SERVICE_KEY: str = ""
    NOTIFICATION_INTERNAL_SERVICE_KEY_FILE: str | None = None
    DOCUMENT_STORAGE_PATH: str = ".rubrica-storage"
    SIGNING_APP_URL: str = "http://localhost:8080/signing"
    EVIDENCE_SECRET: str = "rubrica-development-evidence-secret-change-me"
    EVIDENCE_SECRET_FILE: str | None = None
    PUBLIC_WEB_URL: str = "http://localhost:8080"
    BILLING_PROVIDER: Literal["fake", "stripe"] = "stripe"
    STRIPE_SECRET_KEY: str | None = None
    STRIPE_SECRET_KEY_FILE: str | None = None
    STRIPE_WEBHOOK_SECRET: str | None = None
    STRIPE_WEBHOOK_SECRET_FILE: str | None = None
    STRIPE_PRICE_BRL: str | None = None
    STRIPE_PRICE_USD: str | None = None
    STRIPE_PRICE_JPY: str | None = None
    BILLING_GRACE_PERIOD_DAYS: int = Field(default=10, ge=0, le=30)

    @model_validator(mode="after")
    def load_secret_files(self) -> "Settings":
        return apply_secret_files(
            self,
            {
                "POSTGRES_PASSWORD": "POSTGRES_PASSWORD_FILE",
                "CORE_INTERNAL_SERVICE_KEY": "CORE_INTERNAL_SERVICE_KEY_FILE",
                "NOTIFICATION_INTERNAL_SERVICE_KEY": "NOTIFICATION_INTERNAL_SERVICE_KEY_FILE",
                "EVIDENCE_SECRET": "EVIDENCE_SECRET_FILE",
                "STRIPE_SECRET_KEY": "STRIPE_SECRET_KEY_FILE",
                "STRIPE_WEBHOOK_SECRET": "STRIPE_WEBHOOK_SECRET_FILE",
            },
        )

    @property
    def SQLALCHEMY_DATABASE_URL(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            f"postgresql+psycopg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.CORE_POSTGRES_DB}"
        )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )


settings = Settings()
