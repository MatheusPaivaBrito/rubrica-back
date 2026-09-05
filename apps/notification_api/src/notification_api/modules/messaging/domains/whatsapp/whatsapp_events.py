from uuid import uuid4

from notification_api.infrastructure.settings import settings


def build_whatsapp_message_requested(*, to: str, body: str) -> dict[str, object]:
    return {
        "event_id": str(uuid4()),
        "event_type": "notification.whatsapp_message_requested",
        "topic": settings.NOTIFICATION_WHATSAPP_TOPIC,
        "version": 1,
        "payload": {
            "to": to,
            "body": body,
        },
    }
