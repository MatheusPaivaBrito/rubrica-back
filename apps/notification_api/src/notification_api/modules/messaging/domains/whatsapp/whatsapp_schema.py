from pydantic import BaseModel, Field

from notification_api.modules.messaging.schemas import DeliveryPolicy


class WhatsAppMessage(BaseModel):
    to: str = Field(min_length=6, max_length=40)
    body: str = Field(min_length=1)
    idempotency_key: str | None = Field(default=None, max_length=180)
    metadata: dict[str, object] = Field(default_factory=dict)
    delivery_policy: DeliveryPolicy | None = None
