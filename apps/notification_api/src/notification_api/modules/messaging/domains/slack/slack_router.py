from fastapi import APIRouter

from notification_api.modules.messaging.domains.slack.slack_schema import SlackMessage
from notification_api.modules.messaging.domains.slack.slack_service import request_slack_delivery
from notification_api.modules.messaging.schemas import DeliveryAccepted


router = APIRouter(prefix="/messaging/slack", tags=["slack"])


@router.post("/messages", response_model=DeliveryAccepted, status_code=202)
async def send_slack_message(payload: SlackMessage) -> DeliveryAccepted:
    return request_slack_delivery(payload)
