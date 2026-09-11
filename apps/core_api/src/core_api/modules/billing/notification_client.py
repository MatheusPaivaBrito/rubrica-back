import httpx

from core_api.infrastructure.settings import settings


class BillingEmailDeliveryError(RuntimeError):
    pass


def request_billing_email(
    *,
    recipient: str,
    subject: str,
    body: str,
    idempotency_key: str,
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
                "X-Rubrica-Service": "core_api",
                "X-Rubrica-Service-Key": settings.NOTIFICATION_INTERNAL_SERVICE_KEY,
            },
            timeout=5.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise BillingEmailDeliveryError("Billing e-mail delivery is unavailable") from exc
