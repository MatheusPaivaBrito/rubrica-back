from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "Notification API"
    ENVIRONMENT: str = "development"
    SERVICE_NAME: str = "notification_api"

    NOTIFICATION_PERSISTENCE_MODE: Literal["stateless", "durable"] = "stateless"
    NOTIFICATION_DATABASE_URL: str | None = None
    POSTGRES_USER: str = "rubrica"
    POSTGRES_PASSWORD: str = "rubrica"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5435
    NOTIFICATION_POSTGRES_DB: str = "rubrica_notification"
    NOTIFICATION_EMAIL_PROVIDER: str = "local_ack"
    NOTIFICATION_DEFAULT_FROM_EMAIL: str = "no-reply@rubrica.local"
    SENDGRID_API_KEY: str | None = None

    NOTIFICATION_REDIS_ENABLED: bool = False
    NOTIFICATION_REDIS_URL: str = "redis://localhost:6379/0"
    NOTIFICATION_REDIS_KEY_PREFIX: str = "notification"
    NOTIFICATION_DELIVERY_DEFAULT_POLICY: str = "reliable"
    NOTIFICATION_DELIVERY_RETENTION_SECONDS: int = 604800


    @property
    def PERSISTENCE_ENABLED(self) -> bool:
        return self.NOTIFICATION_PERSISTENCE_MODE == "durable"

    @property
    def DATABASE_URL(self) -> str:
        if self.NOTIFICATION_DATABASE_URL:
            return self.NOTIFICATION_DATABASE_URL
        return (
            f"postgresql+psycopg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.NOTIFICATION_POSTGRES_DB}"
        )

    def channel_status(self) -> dict[str, object]:
        return {
            "email": {
                "enabled": True,
                "provider": self.NOTIFICATION_EMAIL_PROVIDER,
                "sendgrid_configured": bool(self.SENDGRID_API_KEY),
            },
            "delivery_attempts": {
                "store": "redis" if self.NOTIFICATION_REDIS_ENABLED else "memory",
                "redis_key_prefix": self.NOTIFICATION_REDIS_KEY_PREFIX,
                "default_policy": self.NOTIFICATION_DELIVERY_DEFAULT_POLICY,
                "retention_seconds": self.NOTIFICATION_DELIVERY_RETENTION_SECONDS,
            },
        }

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )


settings = Settings()
