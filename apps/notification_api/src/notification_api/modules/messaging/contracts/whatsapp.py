from pydantic import BaseModel, Field, model_validator

from notification_api.modules.messaging.contracts.delivery import DeliveryPolicy
from shared_kernel.media import MediaReference


class WhatsAppMessage(BaseModel):
    to: str = Field(min_length=6, max_length=40)
    body: str = Field(default="", max_length=10000)
    media: MediaReference | None = None
    idempotency_key: str | None = Field(default=None, max_length=180)
    metadata: dict[str, object] = Field(default_factory=dict)
    delivery_policy: DeliveryPolicy | None = None

    @model_validator(mode="after")
    def require_content(self) -> "WhatsAppMessage":
        if not self.body.strip() and self.media is None:
            raise ValueError("WhatsApp delivery requires text or media")
        return self
