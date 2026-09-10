from notification_api.infrastructure.providers import accept_delivery
from notification_api.infrastructure.settings import settings
from notification_api.modules.messaging.contracts.whatsapp_events import (
    build_whatsapp_message_requested,
)
from notification_api.modules.messaging.contracts.whatsapp import WhatsAppMessage
from notification_api.modules.messaging.contracts.delivery import DeliveryAccepted


def request_whatsapp_delivery(payload: WhatsAppMessage) -> DeliveryAccepted:
    accepted = accept_delivery(
        channel="whatsapp",
        recipient=payload.to,
        payload=payload.model_dump(),
    )
    if settings.NOTIFICATION_KAFKA_ENABLED:
        accepted["event"] = build_whatsapp_message_requested(
            to=payload.to,
            body=payload.body,
            media=(
                payload.media.model_dump(mode="json")
                if payload.media is not None
                else None
            ),
        )
    return DeliveryAccepted(**accepted)
