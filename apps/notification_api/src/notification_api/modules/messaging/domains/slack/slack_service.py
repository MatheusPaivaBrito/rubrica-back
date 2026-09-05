from notification_api.infrastructure.providers import accept_delivery
from notification_api.modules.messaging.domains.slack.slack_schema import SlackMessage
from notification_api.modules.messaging.schemas import DeliveryAccepted


def request_slack_delivery(payload: SlackMessage) -> DeliveryAccepted:
    accepted = accept_delivery(
        channel="slack",
        recipient=payload.channel,
        payload=payload.model_dump(),
    )
    return DeliveryAccepted(**accepted)
