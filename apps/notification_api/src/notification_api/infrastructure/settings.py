from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from shared_kernel.config import apply_secret_files


class Settings(BaseSettings):
    APP_NAME: str = "Notification API"
    ENVIRONMENT: str = "development"
    SERVICE_NAME: str = "notification_api"

    NOTIFICATION_PERSISTENCE_MODE: Literal["stateless", "durable"] = "stateless"
    NOTIFICATION_DATABASE_URL: str | None = None
    POSTGRES_USER: str = "rubrica"
    POSTGRES_PASSWORD: str = "rubrica"
    POSTGRES_PASSWORD_FILE: str | None = None
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5435
    NOTIFICATION_POSTGRES_DB: str = "rubrica_notification"
    NOTIFICATION_EMAIL_PROVIDER: str = "local_ack"
    NOTIFICATION_DEFAULT_FROM_EMAIL: str = "no-reply@example.local"
    SENDGRID_API_KEY: str | None = None
    SENDGRID_API_KEY_FILE: str | None = None
    RESEND_API_KEY: str | None = None
    RESEND_API_KEY_FILE: str | None = None
    RESEND_FROM_EMAIL: str = "Rubrica <onboarding@resend.dev>"
    NOTIFICATION_EXTENDED_CHANNELS_ENABLED: bool = False

    SLACK_WEBHOOK_URL: str | None = None
    SLACK_WEBHOOK_URL_FILE: str | None = None

    TWILIO_ACCOUNT_SID: str | None = None
    TWILIO_AUTH_TOKEN: str | None = None
    TWILIO_AUTH_TOKEN_FILE: str | None = None
    TWILIO_WHATSAPP_FROM: str = "whatsapp:+14155238886"

    NOTIFICATION_WHATSAPP_PROVIDER: Literal["fake", "twilio", "meta"] = "fake"
    META_GRAPH_API_VERSION: str = "v26.0"
    META_APP_ID: str | None = None
    META_SYSTEM_USER_ID: str | None = None
    META_EMBEDDED_SIGNUP_CONFIG_ID: str | None = None
    META_WHATSAPP_ACCESS_TOKEN: str | None = None
    META_WHATSAPP_ACCESS_TOKEN_FILE: str | None = None
    META_WHATSAPP_PHONE_NUMBER_ID: str | None = None
    META_WHATSAPP_VERIFY_TOKEN: str | None = None
    META_WHATSAPP_VERIFY_TOKEN_FILE: str | None = None
    META_APP_SECRET: str | None = None
    META_APP_SECRET_FILE: str | None = None
    META_WHATSAPP_TENANT_ID: str | None = None

    NOTIFICATION_REDIS_ENABLED: bool = False
    NOTIFICATION_REDIS_URL: str = "redis://localhost:6379/0"
    NOTIFICATION_REDIS_KEY_PREFIX: str = "notification"
    NOTIFICATION_DELIVERY_DEFAULT_POLICY: str = "reliable"
    NOTIFICATION_DELIVERY_RETENTION_SECONDS: int = 604800

    NOTIFICATION_KAFKA_ENABLED: bool = False
    NOTIFICATION_KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    NOTIFICATION_WHATSAPP_TOPIC: str = "notification.whatsapp.message.requested"
    NOTIFICATION_WHATSAPP_INBOUND_TOPIC: str = "notification.whatsapp.message.received"
    NOTIFICATION_INTERNAL_SERVICE_NAME: str = "core_api"
    NOTIFICATION_INTERNAL_ALLOWED_SERVICES_RAW: str = "core_api,auth_api,bootstrap"
    NOTIFICATION_INTERNAL_SERVICE_KEY: str = ""
    NOTIFICATION_INTERNAL_SERVICE_KEY_FILE: str | None = None
    NOTIFICATION_FAKE_WEBHOOK_KEY: str = ""
    NOTIFICATION_FAKE_WEBHOOK_KEY_FILE: str | None = None
    MEDIA_STORAGE_ROOT: str = ".runtime/media"

    @model_validator(mode="after")
    def load_secret_files(self) -> "Settings":
        return apply_secret_files(
            self,
            {
                "POSTGRES_PASSWORD": "POSTGRES_PASSWORD_FILE",
                "SENDGRID_API_KEY": "SENDGRID_API_KEY_FILE",
                "RESEND_API_KEY": "RESEND_API_KEY_FILE",
                "SLACK_WEBHOOK_URL": "SLACK_WEBHOOK_URL_FILE",
                "TWILIO_AUTH_TOKEN": "TWILIO_AUTH_TOKEN_FILE",
                "META_WHATSAPP_ACCESS_TOKEN": "META_WHATSAPP_ACCESS_TOKEN_FILE",
                "META_WHATSAPP_VERIFY_TOKEN": "META_WHATSAPP_VERIFY_TOKEN_FILE",
                "META_APP_SECRET": "META_APP_SECRET_FILE",
                "NOTIFICATION_INTERNAL_SERVICE_KEY": "NOTIFICATION_INTERNAL_SERVICE_KEY_FILE",
                "NOTIFICATION_FAKE_WEBHOOK_KEY": "NOTIFICATION_FAKE_WEBHOOK_KEY_FILE",
            },
        )

    @property
    def PERSISTENCE_ENABLED(self) -> bool:
        return self.NOTIFICATION_PERSISTENCE_MODE == "durable"

    @property
    def NOTIFICATION_INTERNAL_ALLOWED_SERVICES(self) -> tuple[str, ...]:
        configured = {
            item.strip()
            for item in self.NOTIFICATION_INTERNAL_ALLOWED_SERVICES_RAW.split(",")
            if item.strip()
        }
        configured.add(self.NOTIFICATION_INTERNAL_SERVICE_NAME)
        return tuple(sorted(configured))

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
                "resend_configured": bool(self.RESEND_API_KEY),
            },
            "slack": {
                "enabled": True,
                "provider": "slack_webhook" if self.SLACK_WEBHOOK_URL else "local_ack",
            },
            "whatsapp": {
                "enabled": True,
                "provider": (
                    "fake_whatsapp"
                    if self.NOTIFICATION_WHATSAPP_PROVIDER == "fake"
                    else self.NOTIFICATION_WHATSAPP_PROVIDER
                ),
                "twilio_configured": bool(
                    self.TWILIO_ACCOUNT_SID and self.TWILIO_AUTH_TOKEN
                ),
                "meta_configured": bool(
                    self.META_WHATSAPP_ACCESS_TOKEN
                    and self.META_WHATSAPP_PHONE_NUMBER_ID
                ),
                "meta_webhook_configured": bool(
                    self.META_WHATSAPP_VERIFY_TOKEN
                    and self.META_APP_SECRET
                ),
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
