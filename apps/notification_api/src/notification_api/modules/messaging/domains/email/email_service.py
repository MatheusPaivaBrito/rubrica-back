from notification_api.infrastructure.providers import accept_delivery
from notification_api.modules.messaging.domains.email.email_schema import EmailMessage
from notification_api.modules.messaging.schemas import DeliveryAccepted


def request_email_delivery(payload: EmailMessage) -> DeliveryAccepted:
    accepted = accept_delivery(
        channel="email",
        recipient=payload.to,
        payload=payload.model_dump(),
    )
    return DeliveryAccepted(**accepted)
