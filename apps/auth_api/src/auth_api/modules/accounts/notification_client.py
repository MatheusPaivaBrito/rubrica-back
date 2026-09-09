import logging

import httpx

from auth_api.infrastructure.settings import settings


logger = logging.getLogger(__name__)


def request_account_email(
    *,
    recipient: str,
    subject: str,
    body: str,
    idempotency_key: str,
    metadata: dict[str, object],
) -> None:
    try:
        response = httpx.post(
            f"{settings.NOTIFICATION_API_URL.rstrip('/')}/messaging/email/messages",
            json={
                "to": recipient,
                "subject": subject,
                "body": body,
                "idempotency_key": idempotency_key,
                "metadata": metadata,
            },
            timeout=5.0,
        )
        response.raise_for_status()
    except httpx.HTTPError:
        logger.exception("Account email delivery request failed")
