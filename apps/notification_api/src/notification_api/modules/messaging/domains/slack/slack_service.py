from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

import orjson

from notification_api.infrastructure.providers import accept_delivery
from notification_api.infrastructure.settings import settings
from notification_api.modules.messaging.contracts.provider import ProviderDelivery
from notification_api.modules.messaging.domains.slack.slack_schema import SlackMessage
from notification_api.modules.messaging.contracts.delivery import DeliveryAccepted
from shared_kernel.media import MediaReference


class SlackWebhookProvider:
    name = "slack"

    def deliver(
        self,
        *,
        recipient: str,
        content: str,
        media: MediaReference | None,
    ) -> ProviderDelivery:
        del recipient
        if not settings.SLACK_WEBHOOK_URL:
            raise RuntimeError("Slack webhook is not configured")
        if media is not None:
            raise RuntimeError("Slack support delivery does not accept media")

        request = Request(
            settings.SLACK_WEBHOOK_URL,
            data=orjson.dumps({"text": content}),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=5.0) as response:
                response.read(16)
        except HTTPError as exc:
            raise RuntimeError(
                f"Slack webhook delivery failed with HTTP {exc.code}"
            ) from exc
        except (OSError, URLError) as exc:
            raise RuntimeError("Slack webhook provider is unavailable") from exc

        return ProviderDelivery(
            provider_message_id=f"slack-{uuid4()}",
            status="accepted",
        )


def request_slack_delivery(payload: SlackMessage) -> DeliveryAccepted:
    accepted = accept_delivery(
        channel="slack",
        recipient=payload.channel,
        payload=payload.model_dump(),
    )
    return DeliveryAccepted(**accepted)
