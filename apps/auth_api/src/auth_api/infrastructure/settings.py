from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
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
