from pydantic import BaseModel, Field

from notification_api.modules.messaging.contracts.delivery import DeliveryPolicy


class EmailMessage(BaseModel):
    to: str = Field(min_length=3, max_length=255)
    subject: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1)
    idempotency_key: str | None = Field(default=None, max_length=180)
    metadata: dict[str, object] = Field(default_factory=dict)
    delivery_policy: DeliveryPolicy | None = None
