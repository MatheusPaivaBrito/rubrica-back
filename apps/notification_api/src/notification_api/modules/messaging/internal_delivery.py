from shared_kernel.identifiers import Identifier

from typing import Literal

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field, model_validator

from notification_api.infrastructure.settings import settings
from notification_api.modules.messaging.domains.twilio.email.email_schema import EmailMessage
from notification_api.modules.messaging.domains.twilio.email.email_service import (
    request_email_delivery,
)
from notification_api.modules.messaging.contracts.whatsapp import (
    WhatsAppMessage,
)
from notification_api.modules.messaging.whatsapp_delivery import (
    request_whatsapp_delivery,
)
from notification_api.modules.messaging.domains.slack.slack_schema import SlackMessage
from notification_api.modules.messaging.domains.slack.slack_service import (
    request_slack_delivery,
)
from notification_api.modules.messaging.contracts.delivery import DeliveryAccepted
from shared_kernel.security.service_tokens import verify_service_token
from shared_kernel.media import MediaReference


class InternalDeliveryRequest(BaseModel):
    tenant_id: Identifier | None = None
    channel: Literal["email", "slack", "whatsapp"]
    recipient: str = Field(min_length=3, max_length=255)
    subject: str | None = Field(default=None, min_length=1, max_length=160)
    content: str = Field(default="", max_length=10000)
    media: MediaReference | None = None
    idempotency_key: str = Field(min_length=8, max_length=180)
    metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_content(self) -> "InternalDeliveryRequest":
        if not self.content.strip() and self.media is None:
            raise ValueError("Delivery requires text or media")
        if self.channel == "email" and not self.subject:
            raise ValueError("Email delivery requires a subject")
        if self.media is not None:
            if self.channel != "whatsapp" or self.tenant_id is None:
                raise ValueError("Media delivery requires a WhatsApp tenant")
            if not self.media.object_key.startswith(f"{self.tenant_id}/"):
                raise ValueError("Media reference does not belong to tenant")
        return self


router = APIRouter(tags=["internal deliveries"])


@router.post(
    "/internal/deliveries",
    response_model=DeliveryAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    include_in_schema=False,
)
def request_internal_delivery(
    payload: InternalDeliveryRequest,
    x_atlas_service: str | None = Header(default=None),
    x_atlas_service_key: str | None = Header(default=None),
) -> DeliveryAccepted:
    if (
        x_atlas_service not in settings.NOTIFICATION_INTERNAL_ALLOWED_SERVICES
        or not settings.NOTIFICATION_INTERNAL_SERVICE_KEY
        or not verify_service_token(
            x_atlas_service_key or "",
            settings.NOTIFICATION_INTERNAL_SERVICE_KEY,
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Service authentication failed",
        )
    if payload.channel == "email":
        return request_email_delivery(
            EmailMessage(
                to=payload.recipient,
                subject=payload.subject or "NexoDesk",
                body=payload.content,
                idempotency_key=payload.idempotency_key,
                metadata=payload.metadata,
            )
        )
    if payload.channel == "slack":
        return request_slack_delivery(
            SlackMessage(
                channel=payload.recipient,
                text=payload.content,
                idempotency_key=payload.idempotency_key,
                metadata=payload.metadata,
            )
        )
    return request_whatsapp_delivery(
        WhatsAppMessage(
            to=payload.recipient,
            body=payload.content,
            media=payload.media,
            idempotency_key=payload.idempotency_key,
            metadata={"tenant_id": payload.tenant_id, **payload.metadata},
        )
    )
