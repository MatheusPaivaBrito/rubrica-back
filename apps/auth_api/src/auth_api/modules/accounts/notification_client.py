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
            f"{settings.NOTIFICATION_API_URL.rstrip('/')}/internal/providers/resend/emails",
            json={
                "recipient": recipient,
                "subject": subject,
                "content": body,
                "idempotency_key": idempotency_key,
            },
            headers={
                "X-Rubrica-Service": "auth_api",
                "X-Rubrica-Service-Key": settings.NOTIFICATION_INTERNAL_SERVICE_KEY,
            },
            timeout=5.0,
        )
        response.raise_for_status()
    except httpx.HTTPError:
        logger.exception("Account email delivery request failed")
