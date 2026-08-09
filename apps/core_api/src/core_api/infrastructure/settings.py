from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "Rubrica Core API"
    ENVIRONMENT: str = "development"
    DEBUG: bool = Field(default=True, validation_alias="APP_DEBUG")
    SERVICE_NAME: str = "core_api"
    API_PORT: int = 8000
    POSTGRES_USER: str = "rubrica"
    POSTGRES_PASSWORD: str = "rubrica"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5435
    CORE_POSTGRES_DB: str = "rubrica_core"
    DATABASE_URL: str | None = Field(default=None, validation_alias="CORE_DATABASE_URL")
    AUTH_API_URL: str = "http://localhost:8101"

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
