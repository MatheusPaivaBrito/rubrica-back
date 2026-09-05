from notification_api.infrastructure.providers import accept_delivery
from notification_api.infrastructure.settings import settings
from notification_api.modules.messaging.domains.whatsapp.whatsapp_events import (
    build_whatsapp_message_requested,
)
from notification_api.modules.messaging.domains.whatsapp.whatsapp_schema import WhatsAppMessage
from notification_api.modules.messaging.schemas import DeliveryAccepted


def request_whatsapp_delivery(payload: WhatsAppMessage) -> DeliveryAccepted:
    accepted = accept_delivery(
        channel="whatsapp",
        recipient=payload.to,
        payload=payload.model_dump(),
    )
    if settings.NOTIFICATION_KAFKA_ENABLED:
        accepted["event"] = build_whatsapp_message_requested(to=payload.to, body=payload.body)
    return DeliveryAccepted(**accepted)
