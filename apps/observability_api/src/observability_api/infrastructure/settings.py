from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from shared_kernel.http import CorsConfig, parse_cors_origins


class ObservabilitySettings(BaseSettings):
    APP_NAME: str = "Rubrica Observability API"
    ENVIRONMENT: str = "development"
    SERVICE_NAME: str = "observability_api"
    OBSERVABILITY_PERSISTENCE_MODE: Literal["none", "incidents"] = "none"
    OBSERVABILITY_DATABASE_URL: str | None = None
    POSTGRES_USER: str = "rubrica"
    POSTGRES_PASSWORD: str = "rubrica"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5435
    OBSERVABILITY_POSTGRES_DB: str = "rubrica_observability"

    CORS_ENABLED: bool = True
    CORS_ALLOWED_ORIGINS: str = ""
    CORS_ALLOW_CREDENTIALS: bool = True

    LOKI_URL: str = "http://localhost:3100"
    LOKI_READY_URL: str = "http://localhost:3100/ready"
    GRAFANA_URL: str = "http://localhost:3000"
    GRAFANA_HEALTH_URL: str = "http://localhost:3000/api/health"
    ALLOY_ENABLED: bool = False
    ALLOY_URL: str = "http://localhost:12345"
    ALLOY_READY_URL: str = "http://localhost:12345/-/ready"

    SENTRY_DSN: str | None = None
    SENTRY_ENVIRONMENT: str = Field(default="development")

    @property
    def PERSISTENCE_ENABLED(self) -> bool:
        return self.OBSERVABILITY_PERSISTENCE_MODE == "incidents"

    @property
    def DATABASE_URL(self) -> str:
        if self.OBSERVABILITY_DATABASE_URL:
            return self.OBSERVABILITY_DATABASE_URL
        return (
            f"postgresql+psycopg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.OBSERVABILITY_POSTGRES_DB}"
        )

    @property
    def CORS_CONFIG(self) -> CorsConfig:
        return CorsConfig(
            enabled=self.CORS_ENABLED,
            allow_origins=parse_cors_origins(self.CORS_ALLOWED_ORIGINS),
            allow_credentials=self.CORS_ALLOW_CREDENTIALS,
        )

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = ObservabilitySettings()
