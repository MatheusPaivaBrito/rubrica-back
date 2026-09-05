from fastapi import APIRouter

from notification_api.modules.messaging.domains.email.email_schema import EmailMessage
from notification_api.modules.messaging.domains.email.email_service import request_email_delivery
from notification_api.modules.messaging.schemas import DeliveryAccepted


router = APIRouter(prefix="/messaging/email", tags=["email"])


@router.post("/messages", response_model=DeliveryAccepted, status_code=202)
async def send_email(payload: EmailMessage) -> DeliveryAccepted:
    return request_email_delivery(payload)
