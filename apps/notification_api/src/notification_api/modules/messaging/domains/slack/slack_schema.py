from pydantic import BaseModel, Field

from notification_api.modules.messaging.schemas import DeliveryPolicy


class SlackMessage(BaseModel):
    channel: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1)
    idempotency_key: str | None = Field(default=None, max_length=180)
    metadata: dict[str, object] = Field(default_factory=dict)
    delivery_policy: DeliveryPolicy | None = None
