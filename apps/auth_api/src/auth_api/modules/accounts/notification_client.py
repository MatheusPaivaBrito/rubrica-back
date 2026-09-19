import logging

import httpx

from auth_api.infrastructure.settings import settings
from shared_kernel.email_templates import RenderedEmail


logger = logging.getLogger(__name__)


class AccountEmailDeliveryError(RuntimeError):
    pass


def request_account_email(
    *,
    recipient: str,
    email: RenderedEmail,
    idempotency_key: str,
) -> None:
    try:
        response = httpx.post(
            f"{settings.NOTIFICATION_API_URL.rstrip('/')}/internal/providers/resend/emails",
            json=email.as_payload(
                recipient=recipient,
                idempotency_key=idempotency_key,
            ),
            headers={
                "X-Rubrica-Service": "auth_api",
                "X-Rubrica-Service-Key": settings.NOTIFICATION_INTERNAL_SERVICE_KEY,
            },
            timeout=5.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.exception("Account email delivery request failed")
        raise AccountEmailDeliveryError("Account e-mail delivery is unavailable") from exc
