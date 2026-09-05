from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "Notification API"
    ENVIRONMENT: str = "development"
    SERVICE_NAME: str = "notification_api"

    NOTIFICATION_PERSISTENCE_MODE: Literal["stateless", "durable"] = "stateless"
    NOTIFICATION_DATABASE_URL: str | None = None
    POSTGRES_USER: str = "atlas"
    POSTGRES_PASSWORD: str = "atlas"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5435
    NOTIFICATION_POSTGRES_DB: str = "rubrica_notification"
    NOTIFICATION_EMAIL_PROVIDER: str = "local_ack"
    NOTIFICATION_DEFAULT_FROM_EMAIL: str = "no-reply@example.local"
    SENDGRID_API_KEY: str | None = None

    SLACK_WEBHOOK_URL: str | None = None

    TWILIO_ACCOUNT_SID: str | None = None
    TWILIO_AUTH_TOKEN: str | None = None
    TWILIO_WHATSAPP_FROM: str = "whatsapp:+14155238886"

    NOTIFICATION_REDIS_ENABLED: bool = False
    NOTIFICATION_REDIS_URL: str = "redis://localhost:6379/0"
    NOTIFICATION_REDIS_KEY_PREFIX: str = "notification"
    NOTIFICATION_DELIVERY_DEFAULT_POLICY: str = "reliable"
    NOTIFICATION_DELIVERY_RETENTION_SECONDS: int = 604800

    NOTIFICATION_KAFKA_ENABLED: bool = False
    NOTIFICATION_KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    NOTIFICATION_WHATSAPP_TOPIC: str = "notification.whatsapp.message.requested"

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
            "slack": {
                "enabled": True,
                "provider": "slack_webhook" if self.SLACK_WEBHOOK_URL else "local_ack",
            },
            "whatsapp": {
                "enabled": True,
                "provider": "twilio" if self.TWILIO_ACCOUNT_SID and self.TWILIO_AUTH_TOKEN else "local_ack",
                "kafka_enabled": self.NOTIFICATION_KAFKA_ENABLED,
                "topic": self.NOTIFICATION_WHATSAPP_TOPIC,
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
