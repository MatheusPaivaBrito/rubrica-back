from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "Eventing API"
    ENVIRONMENT: str = "development"
    SERVICE_NAME: str = Field(default="eventing_api", validation_alias=AliasChoices("EVENTING_SERVICE_NAME", "SERVICE_NAME"))
    POSTGRES_USER: str = "atlas"
    POSTGRES_PASSWORD: str = "atlas"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5435
    EVENTING_POSTGRES_DB: str = "rubrica_eventing"
    DATABASE_URL: str | None = Field(default=None, validation_alias="EVENTING_DATABASE_URL")
    EVENTING_KAFKA_ENABLED: bool = False
    KAFKA_HOST: str = "localhost"
    KAFKA_PORT: int = 9092
    KAFKA_BOOTSTRAP_SERVERS: str | None = None
    EVENTING_DEFAULT_EVENT_TOPIC: str = "atlas.events"
    EVENTING_DEAD_LETTER_TOPIC: str = "atlas.events.dead_letter"

    @property
    def SQLALCHEMY_DATABASE_URL(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            f"postgresql+psycopg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.EVENTING_POSTGRES_DB}"
        )

    @property
    def DEFAULT_EVENT_TOPIC(self) -> str:
        return self.EVENTING_DEFAULT_EVENT_TOPIC

    @property
    def DEAD_LETTER_TOPIC(self) -> str:
        return self.EVENTING_DEAD_LETTER_TOPIC

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", populate_by_name=True)


settings = Settings()
