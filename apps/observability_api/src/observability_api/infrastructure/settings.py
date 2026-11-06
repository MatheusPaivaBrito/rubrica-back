from pathlib import Path

from pydantic import AliasChoices, Field, PrivateAttr, model_validator
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
    PLATFORM_URL: str = "https://grafana.7f3a9c2e8b.stream"
    PLATFORM_TOKEN: str | None = Field(default=None, repr=False, exclude=True)
    PLATFORM_TOKEN_FILE: str | None = None
    PLATFORM_PROJECT: str = "rubrica"
    PLATFORM_ENVIRONMENT: str = "staging"
    PLATFORM_SERVICE: str = "observability_api"
    PLATFORM_PUBLISH_ENABLED: bool = False
    _platform_secret_errors: tuple[str, ...] = PrivateAttr(default=())
    OBSERVABILITY_INTERNAL_SERVICE_KEY: str = ""
    OBSERVABILITY_INTERNAL_SERVICE_KEY_FILE: str | None = None

    @model_validator(mode="after")
    def load_secret_files(self) -> "ObservabilitySettings":
        apply_secret_files(
            self,
            {
                "POSTGRES_PASSWORD": "POSTGRES_PASSWORD_FILE",
                "OBSERVABILITY_INTERNAL_SERVICE_KEY": "OBSERVABILITY_INTERNAL_SERVICE_KEY_FILE",
            },
        )
        errors = []
        for field in PLATFORM_SECRET_FIELDS:
            filename = getattr(self, f"{field}_FILE")
            if not filename:
                continue
            try:
                path = Path(filename)
                if not path.is_file() or path.stat().st_mode & 0o077:
                    raise ValueError("Invalid protected secret")
                with path.open(encoding="utf-8") as handle:
                    value = handle.read(4097).strip()
                if not value or len(value) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in value):
                    raise ValueError("Invalid protected secret")
                object.__setattr__(self, field, value)
            except (OSError, ValueError):
                object.__setattr__(self, field, None)
                errors.append(field)
        self._platform_secret_errors = tuple(errors)
        return self

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


PLATFORM_SECRET_FIELDS = ("PLATFORM_TOKEN",)

settings = ObservabilitySettings()
