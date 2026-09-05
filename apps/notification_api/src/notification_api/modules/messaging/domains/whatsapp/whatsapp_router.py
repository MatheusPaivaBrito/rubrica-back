from fastapi import APIRouter

from notification_api.modules.messaging.domains.whatsapp.whatsapp_schema import WhatsAppMessage
from notification_api.modules.messaging.domains.whatsapp.whatsapp_service import request_whatsapp_delivery
from notification_api.modules.messaging.schemas import DeliveryAccepted


router = APIRouter(prefix="/messaging/whatsapp/bot", tags=["whatsapp"])


@router.post("/messages", response_model=DeliveryAccepted, status_code=202)
async def send_whatsapp_message(payload: WhatsAppMessage) -> DeliveryAccepted:
    return request_whatsapp_delivery(payload)
