from typing import ClassVar

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DEVELOPMENT_MFA_KEY: ClassVar[str] = "rubrica-development-mfa-key-change-me"
    APP_NAME: str = "Rubrica Auth API"
    ENVIRONMENT: str = "development"
    DEBUG: bool = Field(default=True, validation_alias="APP_DEBUG")
    SERVICE_NAME: str = "auth_api"
    API_PORT: int = 8001
    POSTGRES_USER: str = "rubrica"
    POSTGRES_PASSWORD: str = "rubrica"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5435
    AUTH_POSTGRES_DB: str = "rubrica_auth"
    DATABASE_URL: str | None = Field(default=None, validation_alias="AUTH_DATABASE_URL")
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    AUTH_REDIS_DB: int = 1
    AUTH_REDIS_KEY_PREFIX: str = "auth"
    AUTH_ACCESS_TTL_SECONDS: int = 900
    AUTH_SESSION_TTL_SECONDS: int = 604800
    AUTH_EMAIL_VERIFICATION_TTL_SECONDS: int = 86400
    AUTH_PASSWORD_RESET_TTL_SECONDS: int = 3600
    AUTH_PUBLIC_WEB_URL: str = "http://localhost:8080"
    NOTIFICATION_API_URL: str = "http://localhost:8103"
    NOTIFICATION_INTERNAL_SERVICE_KEY: str = ""
    AUTH_MFA_ISSUER: str = "Rubrica"
    AUTH_MFA_ENCRYPTION_KEY: str = "rubrica-development-mfa-key-change-me"
    AUTH_MFA_CHALLENGE_TTL_SECONDS: int = 300

    @model_validator(mode="after")
    def validate_production_mfa_key(self) -> "Settings":
        if self.ENVIRONMENT.lower() in {"production", "prod"} and (
            not self.AUTH_MFA_ENCRYPTION_KEY
            or self.AUTH_MFA_ENCRYPTION_KEY == self.DEVELOPMENT_MFA_KEY
            or len(self.AUTH_MFA_ENCRYPTION_KEY) < 32
        ):
            raise ValueError(
                "AUTH_MFA_ENCRYPTION_KEY must be set to a secure value in production"
            )
        return self

    @property
    def SQLALCHEMY_DATABASE_URL(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            f"postgresql+psycopg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.AUTH_POSTGRES_DB}"
        )

    @property
    def REDIS_URL(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.AUTH_REDIS_DB}"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )


settings = Settings()
