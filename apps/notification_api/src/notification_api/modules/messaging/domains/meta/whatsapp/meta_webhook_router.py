from datetime import UTC, datetime
from uuid import uuid4
import asyncio

import orjson
from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status
from pydantic import ValidationError

from notification_api.infrastructure.settings import settings
from notification_api.modules.messaging.domains.meta.whatsapp.meta_schema import (
    MetaWebhookPayload,
)
from notification_api.modules.messaging.domains.meta.whatsapp.meta_service import (
    claim_meta_message,
    download_meta_media,
    release_meta_message,
    verify_meta_signature,
)
from notification_api.modules.messaging.domains.meta.whatsapp.meta_connection_repository import (
    get_meta_connection_repository,
)
from notification_api.modules.messaging.whatsapp_inbound_events import (
    whatsapp_inbound_publisher,
)
from shared_kernel.security.service_tokens import verify_service_token


router = APIRouter(
    prefix="/webhooks/whatsapp/meta",
    tags=["meta whatsapp webhooks"],
)


@router.get("")
async def verify_meta_whatsapp_webhook(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
) -> Response:
    if (
        hub_mode == "subscribe"
        and settings.META_WHATSAPP_VERIFY_TOKEN
        and verify_service_token(
            hub_verify_token or "",
            settings.META_WHATSAPP_VERIFY_TOKEN,
        )
    ):
        return Response(content=hub_challenge or "", media_type="text/plain")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Meta webhook verification failed",
    )


@router.post("")
async def receive_meta_whatsapp_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
) -> dict[str, str]:
    raw_body = await request.body()
    if not settings.META_APP_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Meta webhook app secret is not configured",
        )
    if not verify_meta_signature(raw_body, x_hub_signature_256):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Meta webhook signature",
        )

    try:
        payload = MetaWebhookPayload.model_validate(orjson.loads(raw_body))
    except (orjson.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Meta webhook payload",
        ) from exc

    if payload.object != "whatsapp_business_account":
        return {"status": "ignored"}

    messages = [
        (
            change.value.metadata,
            message,
            next(
                (
                    contact.profile.name
                    for contact in change.value.contacts
                    if contact.wa_id == message.from_number and contact.profile is not None
                ),
                None,
            ),
        )
        for entry in payload.entry
        for change in entry.changes
        if change.field == "messages"
        for message in change.value.messages
    ]
    delivery_statuses = [
        (change.value.metadata, delivery_status)
        for entry in payload.entry
        for change in entry.changes
        if change.field == "messages"
        for delivery_status in change.value.statuses
    ]
    if not messages and not delivery_statuses:
        return {"status": "accepted"}

    for metadata, delivery_status in delivery_statuses:
        tenant_id = _resolve_tenant_id(
            metadata.phone_number_id if metadata is not None else None
        )
        if tenant_id is None:
            continue
        await whatsapp_inbound_publisher.publish(
            {
                "event_id": str(uuid4()),
                "event_type": "notification.whatsapp_delivery_updated",
                "version": 1,
                "occurred_at": datetime.now(UTC).isoformat(),
                "payload": {
                    "tenant_id": tenant_id,
                    "provider_message_id": delivery_status.id,
                    "status": delivery_status.status,
                    "timestamp": delivery_status.timestamp,
                },
            }
        )

    for metadata, message, profile_name in messages:
        if message.type not in {"text", "image", "audio"}:
            continue
        tenant_id = _resolve_tenant_id(
            metadata.phone_number_id if metadata is not None else None
        )
        if tenant_id is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Meta WhatsApp phone number is not connected to a tenant",
            )
        if not claim_meta_message(message.id):
            continue
        try:
            media = None
            body = message.text.body if message.text is not None else ""
            media_payload = message.image if message.type == "image" else message.audio
            if media_payload is not None:
                media = await asyncio.to_thread(
                    download_meta_media,
                    media_payload.id,
                    tenant_id=tenant_id,
                )
                if message.type == "image" and media_payload.caption:
                    body = media_payload.caption
            await whatsapp_inbound_publisher.publish(
                {
                    "event_id": str(uuid4()),
                    "event_type": "notification.whatsapp_message_received",
                    "version": 1,
                    "occurred_at": datetime.now(UTC).isoformat(),
                    "payload": {
                        "tenant_id": tenant_id,
                        "from_number": message.from_number,
                        "profile_name": profile_name,
                        "body": body,
                        "provider_message_id": message.id,
                        "media": media.model_dump(mode="json") if media else None,
                    },
                }
            )
        except Exception as exc:
            release_meta_message(message.id)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="WhatsApp inbound event publisher is unavailable",
            ) from exc

    return {"status": "accepted"}


def _resolve_tenant_id(phone_number_id: str | None) -> object | None:
    if phone_number_id:
        connection = (
            get_meta_connection_repository().get_connected_by_phone_number_id(
                phone_number_id
            )
        )
        if connection is not None:
            return connection.tenant_id
    if (
        settings.META_WHATSAPP_TENANT_ID
        and (
            not settings.META_WHATSAPP_PHONE_NUMBER_ID
            or settings.META_WHATSAPP_PHONE_NUMBER_ID == phone_number_id
        )
    ):
        return settings.META_WHATSAPP_TENANT_ID
    return None
