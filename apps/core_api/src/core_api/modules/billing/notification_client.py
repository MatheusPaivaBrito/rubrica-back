import httpx

from core_api.infrastructure.settings import settings
from shared_kernel.email_templates import branded_message_email


class BillingEmailDeliveryError(RuntimeError):
    pass


def request_billing_email(
    *,
    recipient: str,
    subject: str,
    body: str,
    idempotency_key: str,
    eyebrow: str = "RUBRICA NOTIFICATION",
) -> None:
    email = branded_message_email(
        subject=subject,
        body=body,
        public_url=settings.PUBLIC_WEB_URL,
        eyebrow=eyebrow,
    )
    try:
        response = httpx.post(
            f"{settings.NOTIFICATION_API_URL.rstrip('/')}/internal/providers/resend/emails",
            json=email.as_payload(
                recipient=recipient,
                idempotency_key=idempotency_key,
            ),
            headers={
                "X-Rubrica-Service": "core_api",
                "X-Rubrica-Service-Key": settings.NOTIFICATION_INTERNAL_SERVICE_KEY,
            },
            timeout=5.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise BillingEmailDeliveryError("Billing e-mail delivery is unavailable") from exc
