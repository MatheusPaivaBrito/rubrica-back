from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from shared_kernel.config import apply_secret_files


class ObservabilitySettings(BaseSettings):
    APP_NAME: str = "Rubrica Observability API"
    SERVICE_NAME: str = Field(
        default="observability_api",
        validation_alias=AliasChoices("OBSERVABILITY_SERVICE_NAME", "SERVICE_NAME"),
    )
    ENVIRONMENT: str = "development"
    POSTGRES_USER: str = "rubrica"
    POSTGRES_PASSWORD: str = "rubrica"
    POSTGRES_PASSWORD_FILE: str | None = None
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    OBSERVABILITY_POSTGRES_DB: str = "rubrica_observability"
    OBSERVABILITY_DATABASE_URL: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OBSERVABILITY_DATABASE_URL", "DATABASE_URL"),
    )
    PLATFORM_GRAFANA_URL: str = "http://grafana:3000"
    PLATFORM_GRAFANA_TIMEOUT_SECONDS: float = Field(default=3.0, gt=0, le=30)
    PLATFORM_GRAFANA_SERVICE_TOKEN: str | None = None
    PLATFORM_GRAFANA_SERVICE_TOKEN_FILE: str | None = None
    OBSERVABILITY_INTERNAL_SERVICE_KEY: str = ""
    OBSERVABILITY_INTERNAL_SERVICE_KEY_FILE: str | None = None

    @model_validator(mode="after")
    def load_secret_files(self) -> "ObservabilitySettings":
        return apply_secret_files(
            self,
            {
                "POSTGRES_PASSWORD": "POSTGRES_PASSWORD_FILE",
                "PLATFORM_GRAFANA_SERVICE_TOKEN": "PLATFORM_GRAFANA_SERVICE_TOKEN_FILE",
                "OBSERVABILITY_INTERNAL_SERVICE_KEY": "OBSERVABILITY_INTERNAL_SERVICE_KEY_FILE",
            },
        )

    @property
    def DATABASE_URL(self) -> str:
        if self.OBSERVABILITY_DATABASE_URL:
            return self.OBSERVABILITY_DATABASE_URL
        return (
            f"postgresql+psycopg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.OBSERVABILITY_POSTGRES_DB}"
        )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )


settings = ObservabilitySettings()
