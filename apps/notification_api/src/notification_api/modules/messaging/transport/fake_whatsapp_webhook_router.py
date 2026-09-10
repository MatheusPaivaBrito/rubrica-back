from shared_kernel.identifiers import Identifier

from base64 import b64decode
from binascii import Error as Base64Error
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field, model_validator

from notification_api.infrastructure.settings import settings
from notification_api.modules.messaging.whatsapp_inbound_events import (
    whatsapp_inbound_publisher,
)
from shared_kernel.security.service_tokens import verify_service_token
from shared_kernel.media import LocalMediaStorage, MediaReference, MediaValidationError


class FakeWhatsappMedia(BaseModel):
    mime_type: str = Field(min_length=3, max_length=80)
    filename: str = Field(min_length=1, max_length=255)
    data_base64: str = Field(min_length=4)


class FakeWhatsappInbound(BaseModel):
    tenant_id: Identifier
    from_number: str = Field(min_length=6, max_length=40)
    body: str = Field(default="", max_length=10000)
    media: FakeWhatsappMedia | None = None
    provider_message_id: str = Field(min_length=4, max_length=255)

    @model_validator(mode="after")
    def require_content(self) -> "FakeWhatsappInbound":
        if not self.body.strip() and self.media is None:
            raise ValueError("Fake WhatsApp message requires text or media")
        return self


class FakeWhatsappAccepted(BaseModel):
    event_id: str
    status: str = "accepted"


router = APIRouter(prefix="/webhooks/whatsapp", tags=["whatsapp webhooks"])


@router.post(
    "/fake",
    response_model=FakeWhatsappAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def receive_fake_whatsapp(
    payload: FakeWhatsappInbound,
    x_fake_webhook_key: str | None = Header(default=None),
) -> FakeWhatsappAccepted:
    if (
        not settings.NOTIFICATION_FAKE_WEBHOOK_KEY
        or not verify_service_token(
            x_fake_webhook_key or "",
            settings.NOTIFICATION_FAKE_WEBHOOK_KEY,
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid fake webhook signature",
        )
    event_id = str(uuid4())
    media_reference: MediaReference | None = None
    try:
        if payload.media is not None:
            try:
                media_bytes = b64decode(payload.media.data_base64, validate=True)
            except Base64Error as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="Invalid base64 media payload",
                ) from exc
            media_reference = LocalMediaStorage(settings.MEDIA_STORAGE_ROOT).store_bytes(
                media_bytes,
                tenant_id=payload.tenant_id,
                scope=f"inbound-{event_id}",
                mime_type=payload.media.mime_type,
                filename=payload.media.filename,
            )
        await whatsapp_inbound_publisher.publish(
            {
                "event_id": event_id,
                "event_type": "notification.whatsapp_message_received",
                "version": 1,
                "occurred_at": datetime.now(UTC).isoformat(),
                "payload": {
                    "tenant_id": payload.tenant_id,
                    "from_number": payload.from_number,
                    "body": payload.body,
                    "provider_message_id": payload.provider_message_id,
                    "media": (
                        media_reference.model_dump(mode="json")
                        if media_reference is not None
                        else None
                    ),
                },
            }
        )
    except MediaValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        if media_reference is not None:
            LocalMediaStorage(settings.MEDIA_STORAGE_ROOT).delete(
                media_reference.object_key
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return FakeWhatsappAccepted(event_id=event_id)
