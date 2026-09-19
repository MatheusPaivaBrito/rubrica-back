import httpx

from core_api.infrastructure.settings import settings
from shared_kernel.email_templates import signature_invitation_email


class SignatureInvitationDeliveryError(RuntimeError):
    pass


def send_signature_invitation(
    *, recipient: str, signer_name: str, document_title: str, signing_url: str, idempotency_key: str
) -> None:
    email = signature_invitation_email(
        signer_name=signer_name,
        document_title=document_title,
        signing_url=signing_url,
        public_url=settings.PUBLIC_WEB_URL,
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
        raise SignatureInvitationDeliveryError(
            "Signature invitation delivery is unavailable"
        ) from exc
